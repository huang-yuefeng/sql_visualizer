-- Step 2: Enrich with TRANSFORM, COMPUTED (CASE), WINDOW functions
INSERT INTO enriched_transactions (
    txn_id, customer_id, net_amount, amount_tier, customer_segment,
    running_total, txn_rank, prev_amount, enriched_date
)
SELECT
    rt.txn_id,
    rt.customer_id,
    COALESCE(rt.amount - rt.fee, rt.amount) AS net_amount,
    CASE
        WHEN rt.amount > 1000 THEN 'HIGH'
        WHEN rt.amount > 500 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS amount_tier,
    cm.segment AS customer_segment,
    SUM(rt.amount) OVER (PARTITION BY rt.customer_id ORDER BY rt.txn_date) AS running_total,
    ROW_NUMBER() OVER (PARTITION BY rt.customer_id ORDER BY rt.txn_date) AS txn_rank,
    LAG(rt.amount) OVER (PARTITION BY rt.customer_id ORDER BY rt.txn_date) AS prev_amount,
    CAST(rt.txn_date AS DATE) AS enriched_date
FROM raw_transactions rt
LEFT JOIN customer_master cm ON rt.customer_id = cm.id;
