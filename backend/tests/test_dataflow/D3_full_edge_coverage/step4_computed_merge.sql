-- Step 4: COMPUTED fields + MERGE with SUBSET bridging
MERGE INTO customer_summary cs
USING (
    SELECT
        da.customer_id,
        da.daily_total,
        da.txn_count,
        da.avg_amount,
        da.category,
        CASE
            WHEN da.daily_total > 1000 THEN 'PLATINUM'
            WHEN da.daily_total > 500 THEN 'GOLD'
            ELSE 'STANDARD'
        END AS tier_level,
        cm.segment AS base_segment
    FROM daily_aggregates da
    JOIN customer_master cm ON da.customer_id = cm.id
) src
ON cs.customer_id = src.customer_id
WHEN MATCHED THEN
    UPDATE SET
        cs.daily_total = src.daily_total,
        cs.txn_count = src.txn_count,
        cs.avg_amount = src.avg_amount,
        cs.tier_level = src.tier_level,
        cs.updated_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN
    INSERT (customer_id, daily_total, txn_count, avg_amount, tier_level, created_at)
    VALUES (src.customer_id, src.daily_total, src.txn_count, src.avg_amount, src.tier_level, CURRENT_TIMESTAMP);
