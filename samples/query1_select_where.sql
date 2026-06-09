-- Simple SELECT with WHERE conditions and logical operators
SELECT u.user_id, u.username, u.email, u.age, u.score
FROM users u
WHERE u.age >= 18
  AND u.status = 'active'
  AND (u.score > 100.00 OR u.score IS NULL)
  AND u.last_login IS NOT NULL
  AND u.created_at >= '2024-01-01';
