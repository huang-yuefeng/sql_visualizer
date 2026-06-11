-- Daily transaction volume by network and currency
SELECT
    t.card_network,
    t.currency_code,
    DATE(t.txn_date) AS txn_date,
    COUNT(t.txn_id) AS txn_count,
    SUM(t.amount) AS total_amount,
    AVG(t.amount) AS avg_amount,
    SUM(COALESCE(t.merchant_discount, 0)
      + COALESCE(t.interchange_fee, 0)
      + COALESCE(t.network_fee, 0)
      + COALESCE(t.processing_fee, 0)) AS total_fees
FROM gps_transactions t
WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  AND t.txn_status = 'SETTLED'
  AND t.card_network IS NOT NULL
GROUP BY t.card_network, t.currency_code, DATE(t.txn_date)
ORDER BY txn_date DESC, total_amount DESC
