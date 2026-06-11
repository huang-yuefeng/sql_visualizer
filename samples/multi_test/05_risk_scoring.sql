-- Risk score monitoring across entities
SELECT
    rs.entity_type,
    rs.entity_id,
    rs.composite_score,
    rs.ml_score,
    rs.rule_score,
    rs.velocity_score,
    rs.scored_at,
    t.merchant_id,
    COUNT(t.txn_id) AS txn_count_7d,
    SUM(t.amount) AS volume_7d,
    a.risk_rating,
    a.account_status,
    CASE
        WHEN rs.composite_score >= 80 AND a.risk_rating = 'HIGH' THEN 'ESCALATE'
        WHEN rs.composite_score >= 80 THEN 'MONITOR'
        WHEN rs.composite_score >= 50 THEN 'REVIEW'
        ELSE 'OK'
    END AS risk_action
FROM gps_risk_scores rs
INNER JOIN gps_accounts a
    ON rs.entity_type = a.entity_type AND rs.entity_id = a.entity_id
LEFT JOIN gps_transactions t
    ON a.entity_id = t.merchant_id
   AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
WHERE rs.scored_at >= DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY)
GROUP BY rs.entity_type, rs.entity_id, rs.composite_score,
         rs.ml_score, rs.rule_score, rs.velocity_score,
         rs.scored_at, t.merchant_id, a.risk_rating, a.account_status
ORDER BY rs.composite_score DESC
