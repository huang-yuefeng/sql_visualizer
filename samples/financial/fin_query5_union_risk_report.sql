-- ============================================================================
-- GPS Financial SQL #5: Multi-Source UNION ALL Aggregation for Risk Reporting
-- Combine transaction, account, and settlement data for regulatory reporting
-- ============================================================================
WITH merchant_activity AS (
    SELECT
        t.merchant_id                         AS entity_id,
        'MERCHANT'                            AS entity_type,
        t.currency_code,
        COUNT(*)                              AS txn_count,
        SUM(t.amount)                         AS total_amount,
        SUM(t.fee_amount)                     AS total_fees,
        SUM(t.net_amount)                     AS net_amount,
        SUM(CASE WHEN t.txn_type = 'CHARGEBACK' THEN t.amount ELSE 0 END) AS chargeback_amount,
        COUNT(DISTINCT t.source_account_id)   AS unique_customers,
        COUNT(DISTINCT DATE(t.created_at))    AS active_days,
        AVG(t.risk_score)                     AS avg_risk_score,
        MAX(t.risk_score)                     AS max_risk_score,
        SUM(CASE WHEN t.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END) AS flagged_txns
    FROM gps_transactions t
    WHERE t.merchant_id IS NOT NULL
      AND t.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
      AND t.txn_status IN ('AUTHORIZED', 'SETTLED')
    GROUP BY t.merchant_id, t.currency_code
),
issuer_activity AS (
    SELECT
        t.issuer_id                           AS entity_id,
        'ISSUER'                              AS entity_type,
        t.currency_code,
        COUNT(*)                              AS txn_count,
        SUM(t.amount)                         AS total_amount,
        SUM(t.fee_amount)                     AS total_fees,
        SUM(t.net_amount)                     AS net_amount,
        0                                     AS chargeback_amount,
        COUNT(DISTINCT t.dest_account_id)     AS unique_customers,
        COUNT(DISTINCT DATE(t.created_at))    AS active_days,
        AVG(t.risk_score)                     AS avg_risk_score,
        MAX(t.risk_score)                     AS max_risk_score,
        SUM(CASE WHEN t.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END) AS flagged_txns
    FROM gps_transactions t
    WHERE t.issuer_id IS NOT NULL
      AND t.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
      AND t.txn_status IN ('AUTHORIZED', 'SETTLED')
    GROUP BY t.issuer_id, t.currency_code
),
acquirer_activity AS (
    SELECT
        t.acquirer_id                         AS entity_id,
        'ACQUIRER'                            AS entity_type,
        t.currency_code,
        COUNT(*)                              AS txn_count,
        SUM(t.amount)                         AS total_amount,
        SUM(t.fee_amount)                     AS total_fees,
        SUM(t.net_amount)                     AS net_amount,
        SUM(CASE WHEN t.txn_type = 'CHARGEBACK' THEN t.amount ELSE 0 END) AS chargeback_amount,
        COUNT(DISTINCT t.source_account_id)   AS unique_customers,
        COUNT(DISTINCT DATE(t.created_at))    AS active_days,
        AVG(t.risk_score)                     AS avg_risk_score,
        MAX(t.risk_score)                     AS max_risk_score,
        SUM(CASE WHEN t.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END) AS flagged_txns
    FROM gps_transactions t
    WHERE t.acquirer_id IS NOT NULL
      AND t.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
      AND t.txn_status IN ('AUTHORIZED', 'SETTLED')
    GROUP BY t.acquirer_id, t.currency_code
),
combined_activity AS (
    SELECT * FROM merchant_activity
    UNION ALL
    SELECT * FROM issuer_activity
    UNION ALL
    SELECT * FROM acquirer_activity
)
SELECT
    ca.entity_id,
    ca.entity_type,
    ca.currency_code,
    ca.txn_count,
    ca.total_amount,
    ca.total_fees,
    ca.net_amount,
    ca.chargeback_amount,
    ca.unique_customers,
    ca.active_days,
    ca.avg_risk_score,
    ca.max_risk_score,
    ca.flagged_txns,

    CASE
        WHEN ca.total_amount > 0
        THEN ROUND(ca.chargeback_amount / ca.total_amount * 100, 2)
        ELSE 0
    END AS chargeback_rate_pct,

    CASE
        WHEN ca.txn_count > 0
        THEN ROUND(ca.flagged_txns * 100.0 / ca.txn_count, 2)
        ELSE 0
    END AS flagged_rate_pct,

    CASE
        WHEN ca.active_days > 0
        THEN ROUND(ca.txn_count * 1.0 / ca.active_days, 1)
        ELSE 0
    END AS avg_daily_txns,

    CASE
        WHEN ca.chargeback_rate_pct > 1.0 OR ca.flagged_rate_pct > 5.0
        THEN 'ENHANCED_DUE_DILIGENCE'
        WHEN ca.avg_risk_score > 70 OR ca.txn_count > 10000
        THEN 'MONITORING'
        ELSE 'STANDARD'
    END AS risk_category,

    SUM(ca.total_amount) OVER (
        PARTITION BY ca.entity_type
        ORDER BY ca.total_amount DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_entity_type_amount,

    PERCENT_RANK() OVER (
        PARTITION BY ca.entity_type
        ORDER BY ca.total_amount
    ) AS amount_percentile,

    RANK() OVER (
        PARTITION BY ca.entity_type
        ORDER BY ca.flagged_txns DESC
    ) AS flagged_rank

FROM combined_activity ca

WHERE ca.txn_count >= 5
  AND ca.total_amount > 0

ORDER BY ca.entity_type, flagged_rank ASC, ca.total_amount DESC;
