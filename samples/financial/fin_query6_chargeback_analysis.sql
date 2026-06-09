-- ============================================================================
-- GPS Financial SQL #6: Chargeback Dispute Resolution Analysis
-- ============================================================================
-- Complex chargeback analysis with correlated subqueries, multi-level CASE,
-- EXISTS/NOT EXISTS chains, scalar subqueries, and multi-table aggregation.
--
-- Business scenario:
--   Analyze chargeback disputes to identify high-risk merchants, compute
--   win/loss ratios, and flag accounts requiring manual review. Cross-
--   references transactions, accounts, risk scores, and audit trail.
-- ============================================================================

WITH
-- ── Step 1: Aggregate chargeback metrics per merchant ────────────────────
merchant_chargeback_stats AS (
    SELECT
        t.merchant_id,
        t.acquirer_id,
        COUNT(DISTINCT t.txn_id)                                     AS total_txns,
        COUNT(DISTINCT CASE WHEN t.txn_type = 'CHARGEBACK'
                       THEN t.txn_id END)                            AS chargeback_count,
        SUM(CASE WHEN t.txn_type = 'CHARGEBACK'
                 THEN t.amount ELSE 0 END)                           AS chargeback_amount,
        SUM(t.amount)                                                AS total_volume,
        -- Scalar subquery: merchant's risk score at time of latest chargeback
        (SELECT rs.composite_score
         FROM gps_risk_scores rs
         WHERE rs.entity_type = 'MERCHANT'
           AND rs.entity_id = t.merchant_id
           AND rs.scored_at <= (
               SELECT MAX(t2.txn_date)
               FROM gps_transactions t2
               WHERE t2.merchant_id = t.merchant_id
                 AND t2.txn_type = 'CHARGEBACK'
           )
         ORDER BY rs.scored_at DESC
         LIMIT 1
        )                                                             AS latest_risk_score,
        -- Correlated subquery: count of disputes won by this merchant
        (SELECT COUNT(*)
         FROM gps_reconciliation r
         WHERE r.entity_type = 'CHARGEBACK'
           AND r.entity_id LIKE CONCAT(t.merchant_id, '-%')
           AND r.recon_status = 'MATCHED'
           AND r.resolution = 'MERCHANT_FAVOR'
        )                                                             AS disputes_won,
        (SELECT COUNT(*)
         FROM gps_reconciliation r
         WHERE r.entity_type = 'CHARGEBACK'
           AND r.entity_id LIKE CONCAT(t.merchant_id, '-%')
           AND r.recon_status = 'MATCHED'
           AND r.resolution = 'CUSTOMER_FAVOR'
        )                                                             AS disputes_lost
    FROM gps_transactions t
    WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
      AND t.merchant_id IS NOT NULL
    GROUP BY t.merchant_id, t.acquirer_id
),

-- ── Step 2: Attach merchant account and fee data ───────────────────────
merchant_with_accounts AS (
    SELECT
        mcs.*,
        a.account_status,
        a.risk_rating,
        a.compliance_flags,
        a.balance                                                     AS account_balance,
        a.reserve_balance,
        -- Check if merchant has ever been flagged by AML
        EXISTS (
            SELECT 1 FROM gps_audit_trail at2
            WHERE at2.entity_type = 'ACCOUNT'
              AND at2.entity_id = a.account_id
              AND at2.field_name = 'aml_review'
              AND at2.new_value = 'FLAGGED'
        )                                                             AS has_aml_flag,
        -- Latest fee schedule applicable
        (SELECT fs.fee_id
         FROM gps_fee_schedules fs
         WHERE fs.applicable_entity_type = 'MERCHANT'
           AND fs.applicable_entity_id = mcs.merchant_id
           AND fs.effective_from <= CURRENT_DATE
           AND (fs.effective_to IS NULL OR fs.effective_to >= CURRENT_DATE)
         ORDER BY fs.effective_from DESC
         LIMIT 1
        )                                                             AS active_fee_schedule_id
    FROM merchant_chargeback_stats mcs
    INNER JOIN gps_accounts a
        ON a.entity_type = 'MERCHANT'
       AND a.entity_id = mcs.merchant_id
    WHERE a.account_status IN ('ACTIVE', 'RESTRICTED')
      AND NOT EXISTS (
          -- Exclude merchants with pending compliance review
          SELECT 1 FROM gps_audit_trail at3
          WHERE at3.entity_type = 'ACCOUNT'
            AND at3.entity_id = a.account_id
            AND at3.field_name = 'compliance_review'
            AND at3.new_value = 'PENDING'
            AND at3.change_timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
      )
),

-- ── Step 3: Compute risk categorization and dispute metrics ───────────
risk_categorized AS (
    SELECT
        mwa.*,
        -- Multi-level nested CASE for risk tiering
        CASE
            WHEN mwa.chargeback_count = 0 THEN 'NO_DISPUTES'
            WHEN mwa.chargeback_count = 0 THEN 'NO_DISPUTES'
            WHEN mwa.latest_risk_score IS NULL THEN 'UNSCORED'
            WHEN mwa.latest_risk_score >= 85 THEN
                CASE
                    WHEN mwa.chargeback_amount > 500000 THEN 'CRITICAL_HIGH_VALUE'
                    WHEN mwa.disputes_lost > mwa.disputes_won * 2 THEN 'CRITICAL_LOSING'
                    ELSE 'CRITICAL_MONITOR'
                END
            WHEN mwa.latest_risk_score >= 60 THEN
                CASE
                    WHEN (mwa.disputes_won + mwa.disputes_lost) > 0
                         AND (mwa.disputes_lost * 1.0 / NULLIF(mwa.disputes_won + mwa.disputes_lost, 0)) > 0.7
                    THEN 'HIGH_LOSS_RATE'
                    WHEN mwa.chargeback_amount > 100000 THEN 'HIGH_VALUE'
                    WHEN mwa.has_aml_flag THEN 'HIGH_AML_CONCERN'
                    ELSE 'HIGH_STANDARD'
                END
            WHEN mwa.latest_risk_score >= 30 THEN 'MEDIUM'
            ELSE 'LOW'
        END                                                           AS risk_tier,
        -- Chargeback ratio as percentage of total volume
        ROUND(
            (mwa.chargeback_amount * 100.0) / NULLIF(mwa.total_volume, 0),
            2
        )                                                             AS chargeback_ratio_pct,
        -- Win rate
        CASE
            WHEN (mwa.disputes_won + mwa.disputes_lost) > 0
            THEN ROUND(
                (mwa.disputes_won * 100.0) / (mwa.disputes_won + mwa.disputes_lost),
                2
            )
            ELSE NULL
        END                                                           AS dispute_win_rate_pct,
        -- Composite health score: weighted combination of risk, chargeback ratio, and win rate
        (
            COALESCE(mwa.latest_risk_score, 50) * 0.4
            + LEAST(COALESCE(
                (mwa.chargeback_amount * 100.0) / NULLIF(mwa.total_volume, 0), 100
              ), 100) * 0.35
            + CASE
                WHEN (mwa.disputes_won + mwa.disputes_lost) > 0
                THEN (mwa.disputes_won * 100.0) / (mwa.disputes_won + mwa.disputes_lost) * 0.25
                ELSE 50 * 0.25
              END
        )                                                             AS composite_health_score,
        -- Flag accounts requiring manual review
        CASE
            WHEN mwa.latest_risk_score >= 85 AND mwa.chargeback_amount > 100000 THEN TRUE
            WHEN mwa.has_aml_flag AND mwa.chargeback_count > 0 THEN TRUE
            WHEN (mwa.disputes_won + mwa.disputes_lost) > 50
                 AND (mwa.disputes_lost * 1.0 / NULLIF(mwa.disputes_won + mwa.disputes_lost, 0)) > 0.8
            THEN TRUE
            ELSE FALSE
        END                                                           AS requires_manual_review
    FROM merchant_with_accounts mwa
)

-- ── Final: Filter and rank merchants for operational review ───────────
SELECT
    rc.merchant_id,
    rc.acquirer_id,
    rc.account_status,
    rc.risk_rating,
    rc.total_txns,
    rc.chargeback_count,
    rc.chargeback_amount,
    rc.total_volume,
    rc.chargeback_ratio_pct,
    rc.dispute_win_rate_pct,
    rc.latest_risk_score,
    rc.composite_health_score,
    rc.risk_tier,
    rc.requires_manual_review,
    rc.active_fee_schedule_id,
    rc.account_balance,
    rc.reserve_balance,
    -- Compute reserve coverage ratio
    CASE
        WHEN rc.chargeback_amount > 0
        THEN ROUND((rc.reserve_balance / rc.chargeback_amount) * 100, 2)
        ELSE NULL
    END                                                               AS reserve_coverage_pct,
    -- Rank within each risk tier by composite health score (ascending = worse)
    RANK() OVER (
        PARTITION BY rc.risk_tier
        ORDER BY rc.composite_health_score ASC
    )                                                                 AS risk_tier_rank,
    -- Dense rank across all merchants by total chargeback amount
    DENSE_RANK() OVER (
        ORDER BY rc.chargeback_amount DESC
    )                                                                 AS chargeback_amount_rank,
    CURRENT_TIMESTAMP                                                 AS analyzed_at
FROM risk_categorized rc
WHERE rc.risk_tier NOT IN ('NO_DISPUTES', 'LOW')
   OR rc.requires_manual_review = TRUE
ORDER BY
    rc.risk_tier ASC,
    rc.composite_health_score ASC
