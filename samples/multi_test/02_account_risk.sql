-- Account risk assessment with balance monitoring
SELECT
    a.account_id,
    a.entity_type,
    a.currency_code,
    a.balance,
    a.available_balance,
    a.risk_rating,
    a.account_status,
    COUNT(t.txn_id) AS recent_txn_count,
    SUM(t.amount) AS recent_volume,
    MAX(t.txn_date) AS last_txn_date,
    CASE
        WHEN a.risk_rating = 'HIGH' AND SUM(t.amount) > 100000 THEN 'CRITICAL'
        WHEN a.risk_rating = 'HIGH' THEN 'REVIEW'
        WHEN a.balance < 0 THEN 'OVERDRAWN'
        ELSE 'NORMAL'
    END AS risk_status
FROM gps_accounts a
LEFT JOIN gps_transactions t
    ON a.entity_id = t.merchant_id
   AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
WHERE a.account_status = 'ACTIVE'
GROUP BY a.account_id, a.entity_type, a.currency_code,
         a.balance, a.available_balance, a.risk_rating, a.account_status
ORDER BY recent_volume DESC
