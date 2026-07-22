WITH customer_metrics AS (
    SELECT
        customer_id,
        SUM(amount) AS total_spend,
        COUNT(*) AS transaction_count,
        ROW_NUMBER() OVER (ORDER BY SUM(amount) DESC) AS rank
    FROM staging_orders
    GROUP BY customer_id
)
SELECT
    cm.customer_id,
    cm.total_spend,
    cm.rank,
    CASE WHEN cm.total_spend > 300 THEN 'VIP' ELSE 'REGULAR' END AS tier
FROM customer_metrics cm;
