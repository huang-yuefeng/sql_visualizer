-- sample_cte_chain.sql
-- Two CTEs where the second references the first — tests cross-CTE lineage

WITH batch_summary AS (
    SELECT
        sb.settlement_batch_id,
        sb.settlement_date,
        sb.total_amount AS batch_total_amount,
        COUNT(t.txn_id) AS actual_txn_count
    FROM gps_settlement_batches sb
    LEFT JOIN gps_transactions t
        ON sb.settlement_batch_id = t.settlement_batch_id
    GROUP BY sb.settlement_batch_id, sb.settlement_date, sb.total_amount
),
recon_data AS (
    SELECT
        bs.settlement_batch_id,
        bs.settlement_date,
        bs.batch_total_amount,
        bs.actual_txn_count,
        COALESCE(ta.actual_amount, 0) AS actual_amount,
        ABS(bs.batch_total_amount - COALESCE(ta.actual_amount, 0)) AS variance
    FROM batch_summary bs
    CROSS JOIN (
        SELECT SUM(t.amount) AS actual_amount
        FROM gps_transactions t
    ) ta
)
SELECT
    settlement_batch_id,
    settlement_date,
    batch_total_amount,
    actual_txn_count,
    actual_amount,
    variance,
    CASE
        WHEN variance > 0.01 * batch_total_amount THEN 'THRESHOLD_BREACH'
        ELSE 'WITHIN_TOLERANCE'
    END AS variance_status
FROM recon_data
ORDER BY settlement_date DESC
