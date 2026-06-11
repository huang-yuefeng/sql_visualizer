-- Fee schedule analysis across networks
SELECT
    fs.card_network,
    fs.fee_type,
    t.merchant_id,
    COUNT(t.txn_id) AS txn_count,
    SUM(t.amount) AS total_volume,
    SUM(COALESCE(t.merchant_discount, 0)) AS total_discount,
    SUM(COALESCE(t.interchange_fee, 0)) AS total_interchange,
    SUM(COALESCE(t.network_fee, 0)) AS total_network_fee,
    ROUND(SUM(COALESCE(t.merchant_discount, 0) + COALESCE(t.interchange_fee, 0)
        + COALESCE(t.network_fee, 0)) / NULLIF(SUM(t.amount), 0) * 100, 2) AS effective_rate_pct
FROM gps_fee_schedules fs
INNER JOIN gps_transactions t
    ON fs.card_network = t.card_network
   AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
   AND t.txn_status = 'SETTLED'
WHERE fs.is_active = 1
GROUP BY fs.card_network, fs.fee_type, t.merchant_id
ORDER BY effective_rate_pct DESC
