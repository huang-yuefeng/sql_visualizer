-- 04_union_subquery.sql: UNION ALL with outer subquery wrapping
-- Tests: UNION, SUBQUERY, SET_OP, TABLE_FLOW edges
SELECT
    order_id,
    customer_id,
    amount,
    order_date,
    'H1_2024' AS half_year_label
FROM orders_2024_h1
WHERE order_status = 'COMPLETED'

UNION ALL

SELECT
    order_id,
    customer_id,
    amount,
    order_date,
    'H2_2024' AS half_year_label
FROM orders_2024_h2
WHERE order_status = 'COMPLETED';
