-- 01_dml_table_flow.sql: INSERT-SELECT with WHERE filter
-- Tests: DML, TABLE_FLOW, FILTER, REF edges
INSERT INTO stg_orders (order_id, customer_id, amount, order_date, order_status)
SELECT
    o.order_id,
    o.customer_id,
    o.amount,
    o.order_date,
    o.order_status
FROM raw_orders o
WHERE o.order_date >= DATE '2024-01-01'
  AND o.order_status IN ('COMPLETED', 'PENDING');
