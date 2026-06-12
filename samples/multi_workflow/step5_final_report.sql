-- Step 5: Final report from daily summary
SELECT ds.report_date, ds.region, ds.total_orders, ds.total_amount,
       ROUND(ds.total_amount / NULLIF(ds.total_orders, 0), 2) AS avg_order_value
FROM daily_summary ds
WHERE ds.report_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
ORDER BY ds.report_date DESC, ds.total_amount DESC;
