-- ============================================================================
-- GPS Financial SQL #14: Recursive Account/Merchant Hierarchy with Running Totals
-- ============================================================================
-- Extreme complexity: WITH RECURSIVE CTE traversing a multi-level merchant
-- hierarchy, computing running balances at each tree level, with nested
-- aggregation, conditional rollup, and depth-limited traversal.
--
-- Real patterns:
--   * WITH RECURSIVE — hierarchical tree traversal (anchor + recursive member)
--   * UNION ALL inside recursive CTE (anchor + recursion)
--   * Depth tracking and cycle detection
--   * Running SUM at each hierarchy level
--   * Conditional aggregation based on tree depth
--   * Multi-level subquery correlation through the hierarchy
-- ============================================================================

WITH RECURSIVE
-- ── Anchor: top-level entities (no parent) ────────────────────────────────
merchant_tree AS (
    SELECT
        a.account_id                                             AS node_id,
        a.entity_id                                              AS merchant_id,
        a.entity_type                                            AS node_type,
        CAST(NULL AS VARCHAR(26))                                AS parent_id,
        0                                                        AS depth,
        CAST(a.entity_id AS VARCHAR(500))                        AS path,
        a.balance                                                AS account_balance,
        a.currency_code,
        a.risk_rating,
        -- Running total at this node (initially just this account)
        a.balance                                                AS subtree_balance,
        -- Count of nodes in subtree (initially 1)
        1                                                        AS subtree_node_count,
        -- Flag: is this a leaf? (will be updated)
        CAST(0 AS SIGNED)                                        AS has_children
    FROM gps_accounts a
    WHERE a.entity_type IN ('MERCHANT', 'ISSUER', 'ACQUIRER')
      AND a.parent_entity_id IS NULL
      AND a.account_status = 'ACTIVE'

    UNION ALL

    -- ── Recursive member: children of current nodes ──────────────────────
    SELECT
        child.account_id                                         AS node_id,
        child.entity_id                                          AS merchant_id,
        child.entity_type                                        AS node_type,
        parent.node_id                                           AS parent_id,
        parent.depth + 1                                         AS depth,
        CONCAT(parent.path, '/', child.entity_id)                AS path,
        child.balance                                            AS account_balance,
        child.currency_code,
        child.risk_rating,
        -- Subtree balance = parent's running total + this child's balance
        parent.subtree_balance + child.balance                   AS subtree_balance,
        parent.subtree_node_count + 1                            AS subtree_node_count,
        -- Check if this node has children (via correlated subquery)
        CAST(
            (SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END
             FROM gps_accounts gc
             WHERE gc.parent_entity_id = child.entity_id
               AND gc.account_status = 'ACTIVE')
            AS SIGNED
        )                                                        AS has_children
    FROM gps_accounts child
    INNER JOIN merchant_tree parent
        ON child.parent_entity_id = parent.merchant_id
       AND child.account_status = 'ACTIVE'
    WHERE parent.depth < 5  -- Depth limit: prevent infinite recursion
),

-- ── Step 2: Attach transaction volume per node ──────────────────────────
node_transactions AS (
    SELECT
        mt.node_id,
        mt.merchant_id,
        mt.node_type,
        mt.parent_id,
        mt.depth,
        mt.path,
        mt.account_balance,
        mt.currency_code,
        mt.risk_rating,
        mt.subtree_balance,
        mt.subtree_node_count,
        mt.has_children,
        COALESCE(txn.txn_count, 0)                               AS node_txn_count,
        COALESCE(txn.total_volume, 0)                            AS node_total_volume,
        COALESCE(txn.total_fees, 0)                              AS node_total_fees,
        COALESCE(txn.chargeback_count, 0)                        AS node_chargeback_count
    FROM merchant_tree mt
    LEFT JOIN (
        SELECT
            t.merchant_id,
            COUNT(t.txn_id)                                      AS txn_count,
            SUM(t.settlement_amount)                             AS total_volume,
            SUM(COALESCE(t.merchant_discount, 0)
              + COALESCE(t.interchange_fee, 0)
              + COALESCE(t.network_fee, 0)
              + COALESCE(t.processing_fee, 0))                   AS total_fees,
            SUM(CASE WHEN t.txn_type = 'CHARGEBACK'
                     THEN 1 ELSE 0 END)                          AS chargeback_count
        FROM gps_transactions t
        WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
          AND t.txn_status = 'SETTLED'
        GROUP BY t.merchant_id
    ) txn ON mt.merchant_id = txn.merchant_id
),

-- ── Step 3: Compute tree-level aggregate statistics ─────────────────────
tree_stats AS (
    SELECT
        nt.*,
        -- Volume per child (for leaf nodes)
        CASE
            WHEN nt.has_children = 0
            THEN nt.node_total_volume
            ELSE NULL
        END                                                       AS leaf_volume,
        -- Fee rate at this node
        ROUND(
            nt.node_total_fees * 100.0 / NULLIF(nt.node_total_volume, 0),
            4
        )                                                         AS node_fee_rate_pct,
        -- Risk-weighted balance
        CASE nt.risk_rating
            WHEN 'LOW'    THEN nt.account_balance * 1.0
            WHEN 'MEDIUM' THEN nt.account_balance * 0.8
            WHEN 'HIGH'   THEN nt.account_balance * 0.5
            ELSE nt.account_balance * 0.3
        END                                                       AS risk_weighted_balance,
        -- Depth label
        CASE
            WHEN nt.depth = 0 THEN 'ROOT'
            WHEN nt.depth = 1 THEN 'TIER_1'
            WHEN nt.depth = 2 THEN 'TIER_2'
            WHEN nt.depth = 3 THEN 'TIER_3'
            ELSE 'DEEP'
        END                                                       AS depth_label,
        -- Cumulative volume along the path (running total down the tree)
        SUM(nt.node_total_volume) OVER (
            PARTITION BY SUBSTRING_INDEX(nt.path, '/', 1)  -- root ancestor
            ORDER BY nt.depth, nt.node_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                         AS path_cumulative_volume,
        -- Rank within same depth and currency
        RANK() OVER (
            PARTITION BY nt.depth, nt.currency_code
            ORDER BY nt.subtree_balance DESC
        )                                                         AS depth_currency_rank,
        -- Percentage of parent's subtree balance
        ROUND(
            nt.account_balance * 100.0 / NULLIF(
                nt.subtree_balance - nt.account_balance, 0
            ),
            2
        )                                                         AS pct_of_sibling_total
    FROM node_transactions nt
)

-- ── Final: Hierarchy with aggregate rollups ────────────────────────────
SELECT
    ts.node_id,
    ts.merchant_id,
    ts.node_type,
    ts.parent_id,
    ts.depth,
    ts.depth_label,
    ts.path,
    ts.currency_code,
    ts.risk_rating,
    ts.account_balance,
    ts.risk_weighted_balance,
    ts.subtree_balance,
    ts.subtree_node_count,
    ts.has_children,
    ts.node_txn_count,
    ts.node_total_volume,
    ts.leaf_volume,
    ts.node_total_fees,
    ts.node_fee_rate_pct,
    ts.node_chargeback_count,
    ts.depth_currency_rank,
    ts.path_cumulative_volume,
    ts.pct_of_sibling_total,
    -- Alert if this node is a disproportionate part of its subtree
    CASE
        WHEN ts.subtree_node_count > 1
         AND ts.pct_of_sibling_total > 90
        THEN 'CONCENTRATION_RISK'
        WHEN ts.node_chargeback_count > 50 AND ts.risk_rating = 'HIGH'
        THEN 'CHARGEBACK_ESCALATION'
        WHEN ts.account_balance > 1000000 AND ts.has_children = 0
        THEN 'LARGE_LEAF'
        ELSE 'OK'
    END                                                           AS alert_flag,
    -- Rolling 3-level fee rate average along the path
    AVG(ts.node_fee_rate_pct) OVER (
        PARTITION BY SUBSTRING_INDEX(ts.path, '/', 1)
        ORDER BY ts.depth
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    )                                                             AS rolling_3level_avg_fee_pct,
    CURRENT_TIMESTAMP                                             AS analyzed_at
FROM tree_stats ts
ORDER BY
    SUBSTRING_INDEX(ts.path, '/', 1),
    ts.depth,
    ts.subtree_balance DESC
