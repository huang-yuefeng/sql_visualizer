-- 06_merge_update.sql: MERGE with UPDATE/INSERT branches
-- Tests: DML, MERGE target, TABLE_FLOW edges
MERGE INTO customer_summary AS target
USING (
    SELECT
        t.customer_id,
        SUM(t.amount) AS total_spent,
        COUNT(*) AS transaction_count,
        MAX(t.order_date) AS last_order_date
    FROM stg_orders t
    WHERE t.order_status = 'COMPLETED'
    GROUP BY t.customer_id
) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED THEN
    UPDATE SET
        total_spent = target.total_spent + source.total_spent,
        transaction_count = target.transaction_count + source.transaction_count,
        last_order_date = GREATEST(target.last_order_date, source.last_order_date)
WHEN NOT MATCHED THEN
    INSERT (customer_id, total_spent, transaction_count, last_order_date)
    VALUES (source.customer_id, source.total_spent, source.transaction_count, source.last_order_date);
