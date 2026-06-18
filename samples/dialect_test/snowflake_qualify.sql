-- Snowflake: QUALIFY, COPY INTO
SELECT
    customer_id,
    order_date,
    order_amount,
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) AS rn
FROM orders
WHERE order_date >= '2024-01-01'
QUALIFY rn = 1;
