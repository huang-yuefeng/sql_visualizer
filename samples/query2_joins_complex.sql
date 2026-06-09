-- SELECT with JOINs, complex WHERE, aggregation, HAVING
SELECT
    u.user_id,
    u.username,
    COUNT(o.order_id) AS total_orders,
    SUM(o.amount) AS total_spent,
    AVG(o.amount) AS avg_order_amount,
    MAX(o.order_date) AS last_order_date
FROM users u
LEFT JOIN orders o ON u.user_id = o.user_id
INNER JOIN payments p ON o.order_id = p.order_id
WHERE u.status IN ('active', 'vip')
  AND u.age BETWEEN 25 AND 45
  AND o.order_date >= DATE_SUB(CURRENT_DATE, INTERVAL 1 YEAR)
  AND p.status = 'completed'
  AND p.payment_method IN ('credit_card', 'paypal')
GROUP BY u.user_id, u.username
HAVING total_orders >= 3
   AND total_spent > 500.00
ORDER BY total_spent DESC;
