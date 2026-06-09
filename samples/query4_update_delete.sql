-- UPDATE and DELETE with logical conditions
UPDATE orders o
SET o.order_status = 'cancelled',
    o.shipped_date = NULL
WHERE o.order_status = 'pending'
  AND o.order_date < DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  AND NOT EXISTS (
      SELECT 1 FROM payments p
      WHERE p.order_id = o.order_id
        AND p.status = 'completed'
  );

DELETE FROM logs l
WHERE l.table_name = 'orders'
  AND l.operation = 'DELETE'
  AND l.changed_at < DATE_SUB(CURRENT_DATE, INTERVAL 90 DAY)
  AND l.changed_by IN (
      SELECT u.user_id FROM users u
      WHERE u.status = 'disabled'
  );
