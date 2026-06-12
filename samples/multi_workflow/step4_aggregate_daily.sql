-- Step 4: Aggregate orders by day and region
INSERT INTO daily_summary (report_date, region, total_orders, total_amount)
SELECT DATE(ao.order_date) AS dt, ao.region, COUNT(*) AS cnt, SUM(ao.amount) AS total
FROM analytics_orders ao
GROUP BY DATE(ao.order_date), ao.region;
