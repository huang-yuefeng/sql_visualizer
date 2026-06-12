-- Step 3: Join orders with customer data into analytics table
INSERT INTO analytics_orders (order_id, customer_name, amount, segment, region, order_date)
SELECT so.order_id, sc.name, so.amount, sc.segment, sc.region, so.order_date
FROM stg_orders so
JOIN stg_customers sc ON so.customer_id = sc.customer_id
WHERE so.status = 'completed';
