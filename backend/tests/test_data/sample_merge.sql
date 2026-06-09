-- sample_merge.sql
-- MERGE INTO statement with WHEN MATCHED and WHEN NOT MATCHED

MERGE INTO gps_accounts AS target
USING (
    SELECT
        t.account_id,
        SUM(t.amount) AS total_amount,
        COUNT(t.txn_id) AS txn_count,
        MAX(t.txn_date) AS last_txn_date
    FROM gps_transactions t
    WHERE t.txn_status = 'SETTLED'
    GROUP BY t.account_id
) AS source
ON target.account_id = source.account_id
WHEN MATCHED THEN UPDATE SET
    target.balance = target.balance + source.total_amount,
    target.total_transactions = target.total_transactions + source.txn_count,
    target.last_activity_date = source.last_txn_date,
    target.updated_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (
    account_id, balance, total_transactions, last_activity_date, created_at, updated_at
) VALUES (
    source.account_id, source.total_amount, source.txn_count,
    source.last_txn_date, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
)
