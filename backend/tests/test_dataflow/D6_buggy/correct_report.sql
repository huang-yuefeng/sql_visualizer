SELECT
    bs.status,
    bs.total_amount,
    bs.txn_count
FROM batch_summary bs
WHERE bs.total_amount > 0;
