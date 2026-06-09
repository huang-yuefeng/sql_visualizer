-- ============================================================================
-- GPS Financial SQL #16: LATERAL Joins + INTERSECT/EXCEPT + Correlated Analysis
-- ============================================================================
-- Extreme complexity: LATERAL subqueries (CROSS APPLY pattern), INTERSECT
-- and EXCEPT set operations for merchant cohort comparison, correlated
-- lateral joins for per-row top-N computation, multi-level nested CASE
-- with window functions, and complex date-range intersection logic.
--
-- Real patterns:
--   * LATERAL JOIN — correlated per-row subquery execution
--   * INTERSECT — merchants active in ALL specified periods
--   * EXCEPT — merchants lost between periods
--   * CROSS JOIN LATERAL — per-row top-N + running computation
--   * Nested CASE inside LATERAL subqueries
--   * Multi-period cohort comparison with set operations
--   * Complex date range overlap detection
-- ============================================================================

WITH
-- ── Step 1: Active merchants in each quarter ─────────────────────────────
q1_2025_merchants AS (
    SELECT DISTINCT t.merchant_id, t.card_network, t.acquirer_id
    FROM gps_transactions t
    WHERE t.txn_date >= '2025-01-01' AND t.txn_date < '2025-04-01'
      AND t.txn_type = 'PURCHASE' AND t.txn_status = 'SETTLED'
      AND t.merchant_id IS NOT NULL
),
q2_2025_merchants AS (
    SELECT DISTINCT t.merchant_id, t.card_network, t.acquirer_id
    FROM gps_transactions t
    WHERE t.txn_date >= '2025-04-01' AND t.txn_date < '2025-07-01'
      AND t.txn_type = 'PURCHASE' AND t.txn_status = 'SETTLED'
      AND t.merchant_id IS NOT NULL
),
q3_2025_merchants AS (
    SELECT DISTINCT t.merchant_id, t.card_network, t.acquirer_id
    FROM gps_transactions t
    WHERE t.txn_date >= '2025-07-01' AND t.txn_date < '2025-10-01'
      AND t.txn_type = 'PURCHASE' AND t.txn_status = 'SETTLED'
      AND t.merchant_id IS NOT NULL
),
q4_2025_merchants AS (
    SELECT DISTINCT t.merchant_id, t.card_network, t.acquirer_id
    FROM gps_transactions t
    WHERE t.txn_date >= '2025-10-01' AND t.txn_date < '2026-01-01'
      AND t.txn_type = 'PURCHASE' AND t.txn_status = 'SETTLED'
      AND t.merchant_id IS NOT NULL
),

-- ── Step 2: INTERSECT — merchants active in ALL 4 quarters (continuously active) ──
continuously_active AS (
    SELECT merchant_id, card_network, acquirer_id FROM q1_2025_merchants
    INTERSECT
    SELECT merchant_id, card_network, acquirer_id FROM q2_2025_merchants
    INTERSECT
    SELECT merchant_id, card_network, acquirer_id FROM q3_2025_merchants
    INTERSECT
    SELECT merchant_id, card_network, acquirer_id FROM q4_2025_merchants
),

-- ── Step 3: EXCEPT — merchants lost after Q1 (in Q1 but NOT in Q4) ─────
lost_merchants AS (
    SELECT merchant_id, card_network, acquirer_id FROM q1_2025_merchants
    EXCEPT
    SELECT merchant_id, card_network, acquirer_id FROM q4_2025_merchants
),

-- ── Step 4: New merchants in Q4 (NOT in Q1-Q3) ─────────────────────────
new_q4_merchants AS (
    SELECT merchant_id, card_network, acquirer_id FROM q4_2025_merchants
    EXCEPT
    (SELECT merchant_id, card_network, acquirer_id FROM q1_2025_merchants
     UNION
     SELECT merchant_id, card_network, acquirer_id FROM q2_2025_merchants
     UNION
     SELECT merchant_id, card_network, acquirer_id FROM q3_2025_merchants)
),

-- ── Step 5: LATERAL JOIN — per-merchant top-3 settlement batches ───────
merchant_top_batches AS (
    SELECT
        ca.merchant_id,
        ca.card_network,
        ca.acquirer_id,
        top3.batch_id,
        top3.batch_total,
        top3.batch_txn_count,
        top3.batch_settlement_date,
        top3.batch_rank
    FROM continuously_active ca
    CROSS JOIN LATERAL (
        SELECT
            sb.batch_id,
            sb.total_amount                                       AS batch_total,
            sb.total_transactions                                 AS batch_txn_count,
            sb.settlement_date                                    AS batch_settlement_date,
            ROW_NUMBER() OVER (
                ORDER BY sb.total_amount DESC
            )                                                     AS batch_rank
        FROM gps_settlement_batches sb
        WHERE (sb.counterparty_a = ca.merchant_id
               OR sb.counterparty_b = ca.merchant_id)
          AND sb.batch_status = 'CLOSED'
          AND sb.settlement_date >= '2025-01-01'
        ORDER BY sb.total_amount DESC
        LIMIT 3
    ) AS top3
    WHERE top3.batch_rank <= 3
),

-- ── Step 6: Another LATERAL — per-merchant risk trend (last 5 scores) ──
merchant_risk_trend AS (
    SELECT
        ca.merchant_id,
        ca.card_network,
        risk_score_trend.avg_risk_score,
        risk_score_trend.max_risk_score,
        risk_score_trend.risk_trend_direction,
        risk_score_trend.oldest_score,
        risk_score_trend.newest_score
    FROM continuously_active ca
    CROSS JOIN LATERAL (
        SELECT
            ROUND(AVG(rs.composite_score), 1)                     AS avg_risk_score,
            MAX(rs.composite_score)                               AS max_risk_score,
            CASE
                WHEN MAX(rs.composite_score) - MIN(rs.composite_score) > 10
                    THEN 'WORSENING'
                WHEN MIN(rs.composite_score) - MAX(rs.composite_score) > 10
                    THEN 'IMPROVING'
                ELSE 'STABLE'
            END                                                   AS risk_trend_direction,
            FIRST_VALUE(rs.composite_score) OVER (
                ORDER BY rs.scored_at ASC
            )                                                     AS oldest_score,
            FIRST_VALUE(rs.composite_score) OVER (
                ORDER BY rs.scored_at DESC
            )                                                     AS newest_score
        FROM gps_risk_scores rs
        WHERE rs.entity_type = 'MERCHANT'
          AND rs.entity_id = ca.merchant_id
          AND rs.scored_at >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
        LIMIT 5
    ) AS risk_score_trend
),

-- ── Step 7: LATERAL — per-merchant fee schedule with effective rate ────
merchant_fee_details AS (
    SELECT
        ca.merchant_id,
        ca.card_network,
        ca.acquirer_id,
        fee_info.fee_type,
        fee_info.effective_rate,
        fee_info.monthly_fee_estimate,
        fee_info.is_preferred_pricing
    FROM continuously_active ca
    CROSS JOIN LATERAL (
        SELECT
            fs.fee_type,
            CASE
                WHEN fs.fee_type = 'PERCENTAGE'
                THEN CAST(JSON_EXTRACT(fs.fee_structure, '$.percentage_rate')
                          AS DECIMAL(10,6))
                WHEN fs.fee_type = 'TIERED'
                THEN CAST(JSON_EXTRACT(fs.fee_structure, '$.tiers[0].rate')
                          AS DECIMAL(10,6))
                ELSE NULL
            END                                                   AS effective_rate,
            CASE
                WHEN fs.fee_type = 'HYBRID'
                THEN CAST(JSON_EXTRACT(fs.fee_structure, '$.flat_fee')
                          AS DECIMAL(15,4))
                     * 1000  -- estimate: ~1000 txns/month
                WHEN fs.fee_type = 'PERCENTAGE'
                THEN CAST(JSON_EXTRACT(fs.fee_structure, '$.percentage_rate')
                          AS DECIMAL(10,6))
                     * (SELECT AVG(mtb.batch_total)
                        FROM merchant_top_batches mtb
                        WHERE mtb.merchant_id = ca.merchant_id
                        LIMIT 1)
                ELSE 0
            END                                                   AS monthly_fee_estimate,
            CASE
                WHEN fs.fee_structure->>'$.preferred' = 'true'
                THEN TRUE ELSE FALSE
            END                                                   AS is_preferred_pricing
        FROM gps_fee_schedules fs
        WHERE fs.applicable_entity_type = 'MERCHANT'
          AND fs.applicable_entity_id = ca.merchant_id
          AND fs.card_network = ca.card_network
          AND fs.effective_from <= CURRENT_DATE
          AND (fs.effective_to IS NULL OR fs.effective_to >= CURRENT_DATE)
        ORDER BY fs.effective_from DESC
        LIMIT 1
    ) AS fee_info
)

-- ── Final: Comprehensive merchant health dashboard ─────────────────────
SELECT
    ca.merchant_id,
    ca.card_network,
    ca.acquirer_id,
    'CONTINUOUSLY_ACTIVE'                                         AS merchant_status,
    -- Risk metrics
    mrt.avg_risk_score,
    mrt.max_risk_score,
    mrt.risk_trend_direction,
    mrt.oldest_score                                              AS risk_score_12mo_ago,
    mrt.newest_score                                              AS risk_score_latest,
    -- Fee metrics
    mfd.fee_type,
    mfd.effective_rate,
    mfd.monthly_fee_estimate,
    mfd.is_preferred_pricing,
    -- Top batch info
    mtb.batch_id                                                  AS largest_batch_id,
    mtb.batch_total                                               AS largest_batch_amount,
    mtb.batch_txn_count                                           AS largest_batch_txns,
    -- Multi-dimension score
    (
        COALESCE((100 - mrt.avg_risk_score), 50) * 0.40
        + CASE WHEN mfd.is_preferred_pricing THEN 100 ELSE 50 END * 0.20
        + CASE
            WHEN mtb.batch_total > 100000 THEN 100
            WHEN mtb.batch_total > 10000  THEN 60
            ELSE 30
          END * 0.40
    )                                                             AS merchant_health_score,
    -- Categorize health
    CASE
        WHEN (COALESCE((100 - mrt.avg_risk_score), 50) * 0.40
             + CASE WHEN mfd.is_preferred_pricing THEN 100 ELSE 50 END * 0.20
             + CASE WHEN mtb.batch_total > 100000 THEN 100
                    WHEN mtb.batch_total > 10000  THEN 60 ELSE 30 END * 0.40) >= 80
            THEN 'EXCELLENT'
        WHEN (COALESCE((100 - mrt.avg_risk_score), 50) * 0.40
             + CASE WHEN mfd.is_preferred_pricing THEN 100 ELSE 50 END * 0.20
             + CASE WHEN mtb.batch_total > 100000 THEN 100
                    WHEN mtb.batch_total > 10000  THEN 60 ELSE 30 END * 0.40) >= 60
            THEN 'HEALTHY'
        WHEN (COALESCE((100 - mrt.avg_risk_score), 50) * 0.40
             + CASE WHEN mfd.is_preferred_pricing THEN 100 ELSE 50 END * 0.20
             + CASE WHEN mtb.batch_total > 100000 THEN 100
                    WHEN mtb.batch_total > 10000  THEN 60 ELSE 30 END * 0.40) >= 40
            THEN 'MONITOR'
        ELSE 'AT_RISK'
    END                                                           AS health_category,
    CURRENT_TIMESTAMP                                             AS evaluated_at
FROM continuously_active ca
LEFT JOIN merchant_risk_trend mrt
    ON ca.merchant_id = mrt.merchant_id AND ca.card_network = mrt.card_network
LEFT JOIN merchant_fee_details mfd
    ON ca.merchant_id = mfd.merchant_id AND ca.card_network = mfd.card_network
LEFT JOIN merchant_top_batches mtb
    ON ca.merchant_id = mtb.merchant_id
   AND ca.card_network = mtb.card_network
   AND mtb.batch_rank = 1

UNION ALL

-- ── Lost merchants (churned) ─────────────────────────────────────────────
SELECT
    lm.merchant_id,
    lm.card_network,
    lm.acquirer_id,
    'CHURNED'                                                     AS merchant_status,
    NULL                                                          AS avg_risk_score,
    NULL                                                          AS max_risk_score,
    'DEPARTED'                                                    AS risk_trend_direction,
    NULL                                                          AS risk_score_12mo_ago,
    NULL                                                          AS risk_score_latest,
    NULL                                                          AS fee_type,
    NULL                                                          AS effective_rate,
    NULL                                                          AS monthly_fee_estimate,
    NULL                                                          AS is_preferred_pricing,
    NULL                                                          AS largest_batch_id,
    NULL                                                          AS largest_batch_amount,
    NULL                                                          AS largest_batch_txns,
    0                                                             AS merchant_health_score,
    'LOST'                                                        AS health_category,
    CURRENT_TIMESTAMP                                             AS evaluated_at
FROM lost_merchants lm

UNION ALL

-- ── New Q4 merchants (acquisition) ───────────────────────────────────────
SELECT
    nq.merchant_id,
    nq.card_network,
    nq.acquirer_id,
    'NEW_Q4'                                                      AS merchant_status,
    NULL                                                          AS avg_risk_score,
    NULL                                                          AS max_risk_score,
    'NEW'                                                         AS risk_trend_direction,
    NULL                                                          AS risk_score_12mo_ago,
    NULL                                                          AS risk_score_latest,
    NULL                                                          AS fee_type,
    NULL                                                          AS effective_rate,
    NULL                                                          AS monthly_fee_estimate,
    NULL                                                          AS is_preferred_pricing,
    NULL                                                          AS largest_batch_id,
    NULL                                                          AS largest_batch_amount,
    NULL                                                          AS largest_batch_txns,
    50                                                            AS merchant_health_score,
    'ONBOARDING'                                                  AS health_category,
    CURRENT_TIMESTAMP                                             AS evaluated_at
FROM new_q4_merchants nq

ORDER BY
    merchant_status,
    merchant_health_score DESC
