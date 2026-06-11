-- Settlement batch reconciliation
SELECT
    sb.batch_id,
    sb.settlement_date,
    sb.currency_code,
    sb.batch_status,
    sb.total_amount AS batch_total,
    COUNT(t.txn_id) AS actual_txn_count,
    SUM(t.amount) AS actual_amount,
    ABS(sb.total_amount - SUM(t.amount)) AS variance,
    CASE
        WHEN ABS(sb.total_amount - SUM(t.amount)) > sb.total_amount * 0.01
        THEN 'BREACH' ELSE 'OK'
    END AS recon_result
FROM gps_settlement_batches sb
LEFT JOIN gps_transactions t
    ON sb.batch_id = t.settlement_batch_id
   AND t.txn_status = 'SETTLED'
WHERE sb.settlement_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
GROUP BY sb.batch_id, sb.settlement_date, sb.currency_code,
         sb.batch_status, sb.total_amount
ORDER BY variance DESC
