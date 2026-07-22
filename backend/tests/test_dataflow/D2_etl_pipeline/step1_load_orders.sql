CREATE TABLE IF NOT EXISTS staging_orders (
    order_id BIGINT,
    customer_id BIGINT,
    amount DECIMAL(18,2),
    order_date DATE
);
INSERT INTO staging_orders VALUES (1, 100, 150.00, '2024-01-15');
INSERT INTO staging_orders VALUES (2, 101, 200.00, '2024-01-16');
