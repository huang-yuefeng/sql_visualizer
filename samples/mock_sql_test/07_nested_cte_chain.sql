-- 07_nested_cte_chain.sql: Chained CTEs with window functions
-- Tests: CTE chain, AGGREGATE, WINDOW, TABLE_FLOW across dependencies
WITH daily_stats AS (
    SELECT
        DATE(order_date) AS order_day,
        customer_id,
        COUNT(*) AS daily_orders,
        SUM(amount) AS daily_total
    FROM raw_orders
    WHERE order_status = 'COMPLETED'
    GROUP BY DATE(order_date), customer_id
),
weekly_rollup AS (
    SELECT
        customer_id,
        order_day,
        daily_orders,
        daily_total,
        SUM(daily_total) OVER (
            PARTITION BY customer_id
            ORDER BY order_day
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS rolling_7day_total,
        LAG(daily_total, 1) OVER (
            PARTITION BY customer_id
            ORDER BY order_day
        ) AS prev_day_total
    FROM daily_stats
),
final_summary AS (
    SELECT
        customer_id,
        MIN(order_day) AS first_order_date,
        MAX(order_day) AS last_order_date,
        SUM(daily_orders) AS total_orders,
        AVG(daily_total) AS avg_daily_spend,
        MAX(rolling_7day_total) AS peak_weekly_spend
    FROM weekly_rollup
    GROUP BY customer_id
)
SELECT
    fs.customer_id,
    dc.customer_name,
    fs.first_order_date,
    fs.last_order_date,
    fs.total_orders,
    fs.avg_daily_spend,
    fs.peak_weekly_spend,
    CURRENT_DATE - fs.last_order_date AS days_since_last_order
FROM final_summary fs
LEFT JOIN dim_customers dc ON fs.customer_id = dc.customer_id
WHERE fs.total_orders >= 3
ORDER BY fs.avg_daily_spend DESC;
