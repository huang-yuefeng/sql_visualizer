SELECT
    cm.customer_id,
    cm.total_spend,
    cm.rank,
    cm.tier,
    AVG(cm.total_spend) OVER () AS avg_spend
FROM (
    SELECT
        customer_id,
        SUM(amount) AS total_spend,
        COUNT(*) AS transaction_count,
        ROW_NUMBER() OVER (ORDER BY SUM(amount) DESC) AS rank,
        CASE WHEN SUM(amount) > 300 THEN 'VIP' ELSE 'REGULAR' END AS tier
    FROM staging_orders
    GROUP BY customer_id
) cm
WHERE cm.tier = 'VIP';
