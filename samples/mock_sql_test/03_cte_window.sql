-- 03_cte_window.sql: CTE with ROW_NUMBER window and CASE expression
-- Tests: CTE, WINDOW, COMPUTED, TABLE_FLOW edges
WITH ranked_orders AS (
    SELECT
        customer_id,
        order_id,
        amount,
        order_date,
        ROW_NUMBER() OVER (
            PARTITION BY customer_id
            ORDER BY order_date DESC
        ) AS recency_rank
    FROM raw_orders
    WHERE order_status = 'COMPLETED'
)
SELECT
    customer_id,
    order_id,
    amount,
    recency_rank,
    CASE
        WHEN recency_rank = 1 THEN 'NEWEST'
        WHEN recency_rank <= 3 THEN 'RECENT'
        ELSE 'OLDER'
    END AS order_recency_label
FROM ranked_orders
WHERE recency_rank <= 10;
