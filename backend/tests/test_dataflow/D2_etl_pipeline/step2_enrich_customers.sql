SELECT
    so.order_id,
    so.customer_id,
    so.amount,
    c.customer_name,
    c.segment
FROM staging_orders so
JOIN customers c ON so.customer_id = c.customer_id
WHERE so.order_date >= '2024-01-01';
