SELECT
    o.id,
    o.amount,
    o.status,
    CASE WHEN o.amount > 50 THEN 'high' ELSE 'low' END AS amount_tier
FROM orders o
WHERE o.status = 'PENDING';
