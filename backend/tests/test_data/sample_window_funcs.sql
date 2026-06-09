-- sample_window_funcs.sql
-- Window functions: ROW_NUMBER, SUM OVER, LAG, LEAD, RANK

SELECT
    t.settlement_batch_id,
    t.amount,
    t.txn_date,
    ROW_NUMBER() OVER (
        PARTITION BY t.settlement_batch_id
        ORDER BY t.txn_date DESC
    ) AS txn_row_num,
    SUM(t.amount) OVER (
        PARTITION BY t.settlement_batch_id
        ORDER BY t.txn_date
    ) AS cumulative_amount,
    LAG(t.amount, 1, 0) OVER (
        PARTITION BY t.settlement_batch_id
        ORDER BY t.txn_date
    ) AS prev_amount,
    LEAD(t.amount, 1, 0) OVER (
        PARTITION BY t.settlement_batch_id
        ORDER BY t.txn_date
    ) AS next_amount,
    RANK() OVER (
        ORDER BY t.amount DESC
    ) AS amount_rank
FROM gps_transactions t
WHERE t.txn_date >= '2024-01-01'
