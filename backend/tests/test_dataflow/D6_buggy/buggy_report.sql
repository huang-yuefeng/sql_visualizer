-- BUG: references t.fee instead of t.amount
SELECT
    t.id,
    t.fee AS amount,    -- wrong source column!
    t.status
FROM transactions t
WHERE t.status = 'COMPLETED';
