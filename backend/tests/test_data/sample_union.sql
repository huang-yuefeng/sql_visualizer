-- sample_union.sql
-- UNION ALL with CTEs — tests union branch variable tracking

WITH merchant_activity AS (
    SELECT
        t.merchant_id,
        'MERCHANT' AS entity_type,
        SUM(t.amount) AS total_amount,
        COUNT(t.txn_id) AS txn_count
    FROM gps_transactions t
    WHERE t.merchant_id IS NOT NULL
    GROUP BY t.merchant_id
),
issuer_activity AS (
    SELECT
        t.issuer_id,
        'ISSUER' AS entity_type,
        SUM(t.amount) AS total_amount,
        COUNT(t.txn_id) AS txn_count
    FROM gps_transactions t
    WHERE t.issuer_id IS NOT NULL
    GROUP BY t.issuer_id
),
combined_activity AS (
    SELECT merchant_id AS entity_id, entity_type, total_amount, txn_count
    FROM merchant_activity
    UNION ALL
    SELECT issuer_id AS entity_id, entity_type, total_amount, txn_count
    FROM issuer_activity
)
SELECT
    entity_id,
    entity_type,
    total_amount,
    txn_count,
    CASE
        WHEN total_amount > 1000000 THEN 'HIGH'
        WHEN total_amount > 100000 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS activity_level
FROM combined_activity
ORDER BY total_amount DESC
