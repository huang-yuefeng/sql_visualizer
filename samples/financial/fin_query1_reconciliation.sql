-- ============================================================================
-- GPS Financial SQL #1: Settlement Batch Reconciliation with CTE + Window Functions
-- Reconcile settlement batches against individual transactions
-- ============================================================================
WITH batch_summary AS (
    SELECT
        sb.batch_id,
        sb.settlement_date,
        sb.currency_code,
        sb.settlement_method,
        sb.clearinghouse_id,
        sb.total_transactions  AS batch_txn_count,
        sb.total_amount        AS batch_total_amount,
        sb.total_fees          AS batch_fees,
        sb.net_settlement_amount,
        sb.batch_status,
        sb.completion_time
    FROM gps_settlement_batches sb
    WHERE sb.settlement_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
      AND sb.batch_status IN ('SETTLED', 'PROCESSING')
),
txn_aggregated AS (
    SELECT
        t.settlement_batch_id,
        COUNT(*)                            AS actual_txn_count,
        SUM(t.amount)                       AS actual_amount,
        SUM(t.fee_amount)                   AS actual_fees,
        SUM(COALESCE(t.tax_amount, 0))      AS actual_tax,
        SUM(t.net_amount)                   AS actual_net,
        COUNT(CASE WHEN t.txn_status = 'DECLINED'    THEN 1 END) AS declined_count,
        COUNT(CASE WHEN t.txn_status = 'CHARGEBACK'  THEN 1 END) AS chargeback_count,
        COUNT(CASE WHEN t.risk_level = 'HIGH'        THEN 1 END) AS high_risk_count
    FROM gps_transactions t
    WHERE t.settlement_batch_id IS NOT NULL
      AND t.settlement_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
      AND t.txn_type IN ('PAYMENT', 'REFUND')
    GROUP BY t.settlement_batch_id
),
recon_data AS (
    SELECT
        r.batch_id,
        r.recon_status,
        r.matched_count,
        r.unmatched_count,
        r.discrepancy_amount,
        r.resolution_notes,
        ROW_NUMBER() OVER (
            PARTITION BY r.batch_id
            ORDER BY r.recon_date DESC, r.created_at DESC
        ) AS latest_recon_rn
    FROM gps_reconciliation r
    WHERE r.recon_type = 'INTERNAL'
      AND r.recon_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
)
SELECT
    bs.batch_id,
    bs.settlement_date,
    bs.currency_code,
    bs.settlement_method,
    bs.clearinghouse_id,
    bs.batch_txn_count,
    bs.batch_total_amount,
    bs.batch_fees,
    bs.net_settlement_amount,
    bs.batch_status,
    COALESCE(ta.actual_txn_count, 0)       AS actual_txn_count,
    COALESCE(ta.actual_amount, 0)          AS actual_amount,
    COALESCE(ta.actual_fees, 0)            AS actual_fees,
    COALESCE(ta.actual_tax, 0)             AS actual_tax,
    COALESCE(ta.actual_net, 0)             AS actual_net,
    ta.declined_count,
    ta.chargeback_count,
    ta.high_risk_count,
    (bs.batch_txn_count - COALESCE(ta.actual_txn_count, 0))   AS txn_count_var,
    (bs.batch_total_amount - COALESCE(ta.actual_amount, 0))   AS amount_var,
    ABS(bs.batch_total_amount - COALESCE(ta.actual_amount, 0)) AS amount_var_abs,
    CASE
        WHEN ABS(bs.batch_total_amount - COALESCE(ta.actual_amount, 0))
             > 0.01 * bs.batch_total_amount
        THEN 'THRESHOLD_BREACH'
        ELSE 'WITHIN_TOLERANCE'
    END AS variance_status,
    rd.recon_status,
    rd.matched_count,
    rd.unmatched_count,
    rd.discrepancy_amount,
    SUM(COALESCE(ta.actual_amount, 0)) OVER (
        PARTITION BY bs.settlement_date, bs.currency_code
        ORDER BY bs.batch_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_daily_amount,
    ROW_NUMBER() OVER (
        PARTITION BY bs.settlement_date
        ORDER BY ABS(bs.batch_total_amount - COALESCE(ta.actual_amount, 0)) DESC
    ) AS variance_rank,
    LAG(bs.batch_total_amount) OVER (
        PARTITION BY bs.currency_code
        ORDER BY bs.settlement_date, bs.batch_id
    ) AS prev_batch_amount
FROM batch_summary bs
LEFT JOIN txn_aggregated ta ON bs.batch_id = ta.settlement_batch_id
LEFT JOIN recon_data rd ON bs.batch_id = rd.batch_id AND rd.latest_recon_rn = 1
WHERE bs.batch_txn_count > 0
  AND (rd.recon_status IS NULL OR rd.recon_status != 'RESOLVED')
ORDER BY bs.settlement_date DESC, variance_rank ASC;
