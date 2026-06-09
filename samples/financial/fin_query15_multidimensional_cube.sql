-- ============================================================================
-- GPS Financial SQL #15: Multi-Dimensional Fee & Revenue Cube Analysis
-- ============================================================================
-- Extreme complexity: CUBE, ROLLUP, GROUPING SETS for multi-dimensional
-- aggregation across 5 dimensions (network × currency × region × merchant
-- category × time), with GROUPING() function, FILTER clause, named WINDOW
-- definitions, and conditional aggregation.
--
-- Real patterns:
--   * GROUPING SETS — multiple aggregation levels in one query
--   * ROLLUP — hierarchical dimension rollup
--   * CUBE — all combinations of dimensions
--   * GROUPING() function — distinguish subtotal rows from detail rows
--   * FILTER clause — conditional aggregation (SQL:2003)
--   * Named WINDOW definitions — reusable window specs
--   * CASE inside SUM with FILTER
--   * INTERSECT for common merchant analysis
-- ============================================================================

WITH
-- ── Step 1: Base transaction data with dimension enrichment ──────────────
enriched_transactions AS (
    SELECT
        t.txn_id,
        t.merchant_id,
        t.card_network,
        t.currency_code                                           AS txn_currency,
        t.settlement_currency,
        t.settlement_amount,
        t.merchant_discount,
        t.interchange_fee,
        t.network_fee,
        t.processing_fee,
        DATE_FORMAT(t.txn_date, '%Y-%m')                          AS txn_month,
        -- Derived dimensions
        CASE
            WHEN t.settlement_amount < 100    THEN 'MICRO'
            WHEN t.settlement_amount < 1000   THEN 'SMALL'
            WHEN t.settlement_amount < 10000  THEN 'MEDIUM'
            WHEN t.settlement_amount < 100000 THEN 'LARGE'
            ELSE 'ENTERPRISE'
        END                                                       AS txn_size_band,
        CASE
            WHEN t.card_present = 1 AND t.mcc IN ('5411','5422','5499')
                THEN 'GROCERY'
            WHEN t.card_present = 1 AND t.mcc IN ('5812','5813','5814')
                THEN 'RESTAURANT'
            WHEN t.card_present = 0 THEN 'ONLINE'
            ELSE 'OTHER_RETAIL'
        END                                                       AS merchant_segment,
        -- Region from geo
        CASE
            WHEN ST_X(t.geo_location) BETWEEN -125 AND -65  THEN 'AMERICAS'
            WHEN ST_X(t.geo_location) BETWEEN -10  AND 40   THEN 'EMEA'
            WHEN ST_X(t.geo_location) BETWEEN 70   AND 150  THEN 'APAC'
            ELSE 'OTHER'
        END                                                       AS region,
        -- Net revenue to GPS
        COALESCE(t.merchant_discount, 0)
        + COALESCE(t.interchange_fee, 0)
        + COALESCE(t.network_fee, 0)
        + COALESCE(t.processing_fee, 0)                           AS net_revenue,
        -- Chargeback flag
        CASE WHEN t.txn_type = 'CHARGEBACK' THEN 1 ELSE 0 END    AS is_chargeback,
        CASE WHEN t.txn_type = 'REFUND'      THEN 1 ELSE 0 END    AS is_refund
    FROM gps_transactions t
    WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 24 MONTH)
      AND t.txn_status = 'SETTLED'
      AND t.merchant_id IS NOT NULL
      AND t.card_network IS NOT NULL
),

-- ── Step 2: CUBE — all dimension combinations for volume analysis ──────
revenue_cube AS (
    SELECT
        -- GROUPING SETS: CUBE across 5 dimensions
        et.txn_month,
        et.card_network,
        et.txn_currency,
        et.merchant_segment,
        et.region,
        -- Totals
        COUNT(et.txn_id)                                          AS txn_count,
        SUM(et.settlement_amount)                                 AS total_volume,
        SUM(et.net_revenue)                                       AS total_revenue,
        COUNT(DISTINCT et.merchant_id)                            AS active_merchants,
        -- Conditional aggregation with FILTER (SQL:2003)
        SUM(et.settlement_amount)
            FILTER (WHERE et.txn_size_band = 'ENTERPRISE')        AS enterprise_volume,
        SUM(et.net_revenue)
            FILTER (WHERE et.txn_size_band IN ('LARGE', 'ENTERPRISE'))
                                                                  AS large_enterprise_revenue,
        COUNT(et.txn_id)
            FILTER (WHERE et.is_chargeback = 1)                   AS chargeback_count,
        SUM(et.settlement_amount)
            FILTER (WHERE et.is_refund = 1)                       AS refund_volume,
        -- Average fee rate
        ROUND(
            AVG(et.net_revenue * 100.0 / NULLIF(et.settlement_amount, 0)),
            4
        )                                                         AS avg_fee_rate_pct,
        -- GROUPING indicators (1 = subtotal row, 0 = detail row)
        GROUPING(et.txn_month)                                    AS grp_month,
        GROUPING(et.card_network)                                 AS grp_network,
        GROUPING(et.txn_currency)                                 AS grp_currency,
        GROUPING(et.merchant_segment)                             AS grp_segment,
        GROUPING(et.region)                                       AS grp_region
    FROM enriched_transactions et
    GROUP BY CUBE (
        et.txn_month,
        et.card_network,
        et.txn_currency,
        et.merchant_segment,
        et.region
    )
),

-- ── Step 3: ROLLUP — hierarchical time × network rollup ────────────────
time_network_rollup AS (
    SELECT
        et.txn_month,
        et.card_network,
        et.merchant_segment,
        COUNT(et.txn_id)                                          AS txn_count,
        SUM(et.settlement_amount)                                 AS total_volume,
        SUM(et.net_revenue)                                       AS total_revenue,
        -- MoM growth requires careful handling with ROLLUP levels
        GROUPING(et.txn_month)                                    AS is_subtotal_month,
        GROUPING(et.card_network)                                 AS is_subtotal_network,
        GROUPING(et.merchant_segment)                             AS is_subtotal_segment
    FROM enriched_transactions et
    GROUP BY ROLLUP (
        et.txn_month,
        et.card_network,
        et.merchant_segment
    )
),

-- ── Step 4: GROUPING SETS — specific dimension combinations ────────────
grouping_sets_analysis AS (
    SELECT
        et.card_network,
        et.merchant_segment,
        et.region,
        COUNT(et.txn_id)                                          AS txn_count,
        SUM(et.settlement_amount)                                 AS total_volume,
        SUM(et.net_revenue)                                       AS total_revenue,
        GROUPING(et.card_network)                                 AS grp_net,
        GROUPING(et.merchant_segment)                             AS grp_seg,
        GROUPING(et.region)                                       AS grp_reg
    FROM enriched_transactions et
    GROUP BY GROUPING SETS (
        (et.card_network, et.merchant_segment, et.region),  -- full detail
        (et.card_network, et.merchant_segment),             -- by network + segment
        (et.card_network, et.region),                       -- by network + region
        (et.merchant_segment, et.region),                   -- by segment + region
        (et.card_network),                                  -- network only
        (et.merchant_segment),                              -- segment only
        (et.region),                                        -- region only
        ()                                                   -- grand total
    )
)

-- ── Final: Named WINDOW + filtered comparisons ─────────────────────────
-- Combine ROLLUP with window functions using named windows
SELECT
    tnr.txn_month,
    tnr.card_network,
    tnr.merchant_segment,
    tnr.txn_count,
    tnr.total_volume,
    tnr.total_revenue,
    tnr.is_subtotal_month,
    tnr.is_subtotal_network,
    tnr.is_subtotal_segment,
    -- MoM growth (only valid at detail level, not subtotals)
    CASE
        WHEN tnr.is_subtotal_month = 0 AND tnr.is_subtotal_network = 0
        THEN ROUND(
            (tnr.total_revenue
             - LAG(tnr.total_revenue) OVER w_month_network_segment)
            * 100.0 / NULLIF(
                LAG(tnr.total_revenue) OVER w_month_network_segment, 0),
            2
        )
        ELSE NULL
    END                                                           AS mom_growth_pct,
    -- Running total within each network across months
    SUM(tnr.total_revenue) OVER w_network_month                   AS network_cumulative_revenue,
    -- Rank by volume within same month across networks
    RANK() OVER w_month_rank                                      AS month_rank,
    -- 3-month moving average (only detail rows)
    CASE
        WHEN tnr.is_subtotal_month = 0 AND tnr.is_subtotal_network = 0
        THEN AVG(tnr.total_revenue) OVER w_3month_ma
        ELSE NULL
    END                                                           AS revenue_3month_ma,
    -- Label for subtotal rows
    CASE
        WHEN tnr.is_subtotal_month = 1
             AND tnr.is_subtotal_network = 1
             AND tnr.is_subtotal_segment = 1
            THEN 'GRAND_TOTAL'
        WHEN tnr.is_subtotal_month = 1
            THEN 'MONTH_SUBTOTAL'
        WHEN tnr.is_subtotal_network = 1
            THEN 'NETWORK_SUBTOTAL'
        WHEN tnr.is_subtotal_segment = 1
            THEN 'SEGMENT_SUBTOTAL'
        ELSE 'DETAIL'
    END                                                           AS row_type
FROM time_network_rollup tnr
WINDOW
    w_month_network_segment AS (
        PARTITION BY tnr.card_network, tnr.merchant_segment
        ORDER BY tnr.txn_month
    ),
    w_network_month AS (
        PARTITION BY tnr.card_network
        ORDER BY tnr.txn_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ),
    w_month_rank AS (
        PARTITION BY tnr.txn_month
        ORDER BY tnr.total_revenue DESC
    ),
    w_3month_ma AS (
        PARTITION BY tnr.card_network, tnr.merchant_segment
        ORDER BY tnr.txn_month
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    )
ORDER BY
    tnr.txn_month,
    tnr.is_subtotal_month,
    tnr.is_subtotal_network,
    tnr.is_subtotal_segment,
    tnr.total_revenue DESC
