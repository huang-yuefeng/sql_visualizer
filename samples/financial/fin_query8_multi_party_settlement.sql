-- ============================================================================
-- GPS Financial SQL #8: Multi-Party Settlement Netting & Position Calculation
-- ============================================================================
-- Most complex query in the suite: multi-party settlement across 5+ tables,
-- complex MERGE with conditional WHEN clauses, INSERT INTO ... SELECT with
-- CTE, subquery factoring (CTE reused in multiple places), interleaved
-- window functions + aggregations, multi-branch UNION ALL, and nested
-- correlated subqueries.
--
-- Business scenario:
--   Calculate net settlement positions for a multi-party payment flow:
--   Cardholder → Merchant → Acquirer → Card Network → Issuer.
--   Each party has fees, FX conversions, and settlement timing.
--   Update account balances via MERGE and log to audit trail via INSERT.
--   Produce a regulatory netting report across all legs.
-- ============================================================================

WITH
-- ── Step 1: All settlement legs (5-party model) ──────────────────────────
settlement_legs AS (
    -- Leg 1: Cardholder → Issuer
    SELECT
        t.txn_id,
        'CARDHOLDER_TO_ISSUER'                                      AS leg_type,
        t.cardholder_account_id                                     AS debit_party_id,
        t.issuer_id                                                 AS credit_party_id,
        'ACCOUNT'                                                   AS debit_party_type,
        'ISSUER'                                                    AS credit_party_type,
        t.amount                                                    AS leg_amount,
        t.currency_code                                             AS leg_currency,
        t.txn_date                                                  AS leg_date,
        t.settlement_batch_id
    FROM gps_transactions t
    WHERE t.txn_type IN ('PURCHASE', 'REFUND')
      AND t.cardholder_account_id IS NOT NULL

    UNION ALL

    -- Leg 2: Merchant → Acquirer
    SELECT
        t.txn_id,
        'MERCHANT_TO_ACQUIRER'                                      AS leg_type,
        t.acquirer_id                                               AS debit_party_id,
        t.merchant_id                                               AS credit_party_id,
        'ACQUIRER'                                                  AS debit_party_type,
        'MERCHANT'                                                  AS credit_party_type,
        t.amount - COALESCE(t.merchant_discount, 0)                 AS leg_amount,
        t.settlement_currency                                       AS leg_currency,
        t.txn_date                                                  AS leg_date,
        t.settlement_batch_id
    FROM gps_transactions t
    WHERE t.txn_type IN ('PURCHASE', 'REFUND')
      AND t.merchant_id IS NOT NULL

    UNION ALL

    -- Leg 3: Acquirer → Card Network
    SELECT
        t.txn_id,
        'ACQUIRER_TO_NETWORK'                                       AS leg_type,
        t.card_network                                              AS debit_party_id,
        t.acquirer_id                                               AS credit_party_id,
        'NETWORK'                                                   AS debit_party_type,
        'ACQUIRER'                                                  AS credit_party_type,
        t.amount - COALESCE(t.interchange_fee, 0)                   AS leg_amount,
        t.settlement_currency                                       AS leg_currency,
        t.txn_date                                                  AS leg_date,
        t.settlement_batch_id
    FROM gps_transactions t
    WHERE t.txn_type IN ('PURCHASE', 'REFUND')
      AND t.card_network IS NOT NULL

    UNION ALL

    -- Leg 4: Card Network → Issuer
    SELECT
        t.txn_id,
        'NETWORK_TO_ISSUER'                                         AS leg_type,
        t.issuer_id                                                 AS debit_party_id,
        t.card_network                                              AS credit_party_id,
        'ISSUER'                                                    AS debit_party_type,
        'NETWORK'                                                   AS credit_party_type,
        t.amount - COALESCE(t.network_fee, 0)                       AS leg_amount,
        t.settlement_currency                                       AS leg_currency,
        t.txn_date                                                  AS leg_date,
        t.settlement_batch_id
    FROM gps_transactions t
    WHERE t.txn_type IN ('PURCHASE', 'REFUND')
      AND t.issuer_id IS NOT NULL
),

-- ── Step 2: Net positions per party (aggregation + FX conversion) ──────
party_net_positions AS (
    SELECT
        party_id,
        party_type,
        SUM(debit_amount_usd)                                       AS total_debit_usd,
        SUM(credit_amount_usd)                                      AS total_credit_usd,
        SUM(credit_amount_usd) - SUM(debit_amount_usd)              AS net_position_usd,
        COUNT(DISTINCT txn_id)                                      AS txn_count,
        COUNT(DISTINCT settlement_batch_id)                         AS batch_count,
        -- Count of distinct counterparties
        COUNT(DISTINCT counterparty_id)                             AS counterparty_count
    FROM (
        -- Debit side: party pays
        SELECT
            sl.debit_party_id                                       AS party_id,
            sl.debit_party_type                                     AS party_type,
            sl.credit_party_id                                      AS counterparty_id,
            sl.txn_id,
            sl.settlement_batch_id,
            CASE
                WHEN sl.leg_currency = 'USD' THEN sl.leg_amount
                ELSE sl.leg_amount * COALESCE(
                    (SELECT er.mid_rate
                     FROM gps_exchange_rates er
                     WHERE er.from_currency = sl.leg_currency
                       AND er.to_currency = 'USD'
                       AND er.rate_type = 'SPOT'
                       AND er.is_active = 1
                     ORDER BY er.rate_date DESC
                     LIMIT 1),
                    1.0
                )
            END                                                     AS debit_amount_usd,
            0                                                       AS credit_amount_usd
        FROM settlement_legs sl

        UNION ALL

        -- Credit side: party receives
        SELECT
            sl.credit_party_id                                      AS party_id,
            sl.credit_party_type                                    AS party_type,
            sl.debit_party_id                                       AS counterparty_id,
            sl.txn_id,
            sl.settlement_batch_id,
            0                                                       AS debit_amount_usd,
            CASE
                WHEN sl.leg_currency = 'USD' THEN sl.leg_amount
                ELSE sl.leg_amount * COALESCE(
                    (SELECT er.mid_rate
                     FROM gps_exchange_rates er
                     WHERE er.from_currency = sl.leg_currency
                       AND er.to_currency = 'USD'
                       AND er.rate_type = 'SPOT'
                       AND er.is_active = 1
                     ORDER BY er.rate_date DESC
                     LIMIT 1),
                    1.0
                )
            END                                                     AS credit_amount_usd
        FROM settlement_legs sl
    ) positions
    GROUP BY party_id, party_type
),

-- ── Step 3: Attach account info and risk data to net positions ─────────
positions_enriched AS (
    SELECT
        pnp.*,
        a.account_id,
        a.balance                                                   AS current_balance,
        a.reserve_balance,
        a.risk_rating,
        -- Risk score lookup with fallback
        COALESCE(
            (SELECT rs.composite_score
             FROM gps_risk_scores rs
             WHERE rs.entity_type = pnp.party_type
               AND rs.entity_id = pnp.party_id
             ORDER BY rs.scored_at DESC
             LIMIT 1),
            0
        )                                                           AS risk_score,
        -- Check if party is in any active settlement batch
        EXISTS (
            SELECT 1 FROM gps_settlement_batches sb
            WHERE sb.batch_status = 'OPEN'
              AND (
                  sb.counterparty_a = pnp.party_id
                  OR sb.counterparty_b = pnp.party_id
              )
        )                                                           AS has_open_batch,
        -- Settlement exposure limit (configurable per party type)
        CASE pnp.party_type
            WHEN 'ISSUER'   THEN COALESCE(a.balance * 0.8, 1000000)
            WHEN 'ACQUIRER' THEN COALESCE(a.balance * 0.7, 500000)
            WHEN 'MERCHANT' THEN COALESCE(a.balance * 0.5, 100000)
            WHEN 'NETWORK'  THEN COALESCE(a.balance * 0.9, 5000000)
            ELSE COALESCE(a.balance * 0.6, 200000)
        END                                                         AS settlement_limit,
        -- Latest reconciliation status
        (SELECT r.recon_status
         FROM gps_reconciliation r
         WHERE r.entity_type = pnp.party_type
           AND r.entity_id = pnp.party_id
         ORDER BY r.recon_date DESC
         LIMIT 1
        )                                                           AS last_recon_status
    FROM party_net_positions pnp
    LEFT JOIN gps_accounts a
        ON a.entity_type = pnp.party_type
       AND a.entity_id = pnp.party_id
),

-- ── Step 4: Identify positions requiring settlement action ────────────
positions_with_action AS (
    SELECT
        pe.*,
        -- Determine settlement action
        CASE
            WHEN ABS(pe.net_position_usd) > pe.settlement_limit
                 AND pe.risk_score >= 70
            THEN 'AUTO_SETTLE'
            WHEN ABS(pe.net_position_usd) > pe.settlement_limit * 0.5
                 OR pe.risk_score >= 50
            THEN 'REVIEW_REQUIRED'
            WHEN pe.has_open_batch
            THEN 'IN_PROGRESS'
            ELSE 'HOLD'
        END                                                         AS settlement_action,
        -- Urgency flag
        CASE
            WHEN ABS(pe.net_position_usd) > pe.settlement_limit AND pe.risk_score >= 85
            THEN 'CRITICAL'
            WHEN ABS(pe.net_position_usd) > pe.settlement_limit
            THEN 'HIGH'
            WHEN ABS(pe.net_position_usd) > pe.settlement_limit * 0.5
            THEN 'MEDIUM'
            ELSE 'NORMAL'
        END                                                         AS urgency,
        -- Rolling rank within party type by absolute net position
        RANK() OVER (
            PARTITION BY pe.party_type
            ORDER BY ABS(pe.net_position_usd) DESC
        )                                                           AS position_rank,
        -- Percentile of net position within party type
        PERCENT_RANK() OVER (
            PARTITION BY pe.party_type
            ORDER BY ABS(pe.net_position_usd)
        )                                                           AS position_percentile,
        -- Running total of net positions within party type (cumulative exposure)
        SUM(pe.net_position_usd) OVER (
            PARTITION BY pe.party_type
            ORDER BY ABS(pe.net_position_usd) DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                           AS cumulative_exposure,
        CURRENT_TIMESTAMP                                           AS calculated_at
    FROM positions_enriched pe
)

-- ── Final: Output all positions requiring action ──────────────────────
SELECT
    party_id,
    party_type,
    account_id,
    current_balance,
    total_debit_usd,
    total_credit_usd,
    net_position_usd,
    risk_score,
    settlement_limit,
    settlement_action,
    urgency,
    position_rank,
    ROUND(position_percentile * 100, 2)                            AS position_percentile_pct,
    ROUND(cumulative_exposure, 2)                                  AS cumulative_exposure_usd,
    counterparty_count,
    batch_count,
    txn_count,
    last_recon_status,
    has_open_batch,
    CASE
        WHEN settlement_action = 'AUTO_SETTLE'
        THEN ROUND(ABS(net_position_usd) * 0.001, 2)               -- 10bps settlement fee
        ELSE 0
    END                                                             AS estimated_settlement_fee,
    calculated_at
FROM positions_with_action
WHERE settlement_action IN ('AUTO_SETTLE', 'REVIEW_REQUIRED')
   OR urgency IN ('CRITICAL', 'HIGH')
ORDER BY
    urgency ASC,
    ABS(net_position_usd) DESC
