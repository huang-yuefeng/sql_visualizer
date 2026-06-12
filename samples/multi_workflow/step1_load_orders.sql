-- Step 1: Load raw orders from source into staging
INSERT INTO stg_orders (order_id, customer_id, amount, order_date, status)
SELECT o.order_id, o.customer_id, o.amount, o.order_date, o.status
FROM raw_orders o
WHERE o.order_date >= '2024-01-01'
  AND o.status IN ('completed', 'pending');
