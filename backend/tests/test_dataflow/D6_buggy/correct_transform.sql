WITH batch_summary AS (
    SELECT
        status,
        SUM(amount) AS total_amount,
        COUNT(*) AS txn_count
    FROM transactions
    GROUP BY status
)
SELECT * FROM batch_summary;
