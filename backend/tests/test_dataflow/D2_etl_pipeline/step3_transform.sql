WITH order_summary AS (
    SELECT
        customer_id,
        SUM(amount) AS total_amount,
        COUNT(*) AS order_count
    FROM staging_orders
    GROUP BY customer_id
)
SELECT
    os.customer_id,
    os.total_amount,
    os.order_count,
    COALESCE(os.total_amount, 0) AS final_amount
FROM order_summary os
WHERE os.total_amount > 100;
