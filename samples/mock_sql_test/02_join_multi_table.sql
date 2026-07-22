-- 02_join_multi_table.sql: Multi-table JOIN with aggregation
-- Tests: JOIN, AGGREGATE, TABLE_FLOW, FILTER edges
SELECT
    c.customer_region,
    SUM(o.amount) AS total_revenue,
    COUNT(DISTINCT o.order_id) AS order_count,
    AVG(o.amount) AS avg_order_value
FROM stg_orders o
INNER JOIN dim_customers c ON o.customer_id = c.customer_id
LEFT JOIN dim_regions r ON c.customer_region = r.region_code
WHERE o.order_date >= DATE '2024-01-01'
GROUP BY c.customer_region
HAVING SUM(o.amount) > 10000;
