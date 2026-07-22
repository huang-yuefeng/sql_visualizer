-- Step 3: Aggregate with AGGREGATE, INDIRECT (HAVING), SET_OP (UNION)
WITH daily_stats AS (
    SELECT
        customer_id,
        DATE(enriched_date) AS stat_date,
        SUM(net_amount) AS daily_total,
        COUNT(*) AS txn_count,
        AVG(net_amount) AS avg_amount
    FROM enriched_transactions
    GROUP BY customer_id, DATE(enriched_date)
    HAVING SUM(net_amount) > 100
),
high_value_daily AS (
    SELECT
        customer_id,
        stat_date,
        daily_total,
        txn_count,
        avg_amount,
        'HIGH_VALUE' AS category
    FROM daily_stats
    WHERE daily_total > 500
)
SELECT * FROM high_value_daily
UNION ALL
SELECT
    customer_id,
    stat_date,
    daily_total,
    txn_count,
    avg_amount,
    'REGULAR' AS category
FROM daily_stats
WHERE daily_total <= 500;
