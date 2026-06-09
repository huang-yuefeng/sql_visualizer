-- SELECT with subqueries, CASE expressions, and EXISTS
SELECT
    u.user_id,
    u.username,
    CASE
        WHEN u.score >= 90 THEN 'A'
        WHEN u.score >= 80 THEN 'B'
        WHEN u.score >= 70 THEN 'C'
        WHEN u.score IS NOT NULL THEN 'D'
        ELSE 'F'
    END AS grade,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM orders o
            WHERE o.user_id = u.user_id
              AND o.amount > 1000
        ) THEN 'High Value'
        ELSE 'Regular'
    END AS customer_tier,
    (
        SELECT COUNT(*) FROM orders o
        WHERE o.user_id = u.user_id
          AND o.order_status = 'shipped'
    ) AS shipped_orders
FROM users u
WHERE u.age > 18
  AND (
    u.username LIKE 'j%'
    OR u.email NOT LIKE '%test.com'
  );
