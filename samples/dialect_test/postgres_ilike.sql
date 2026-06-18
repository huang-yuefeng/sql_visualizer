-- PostgreSQL: ILIKE, :: casting, RETURNING
INSERT INTO audit_log (user_id, action, old_data, new_data)
SELECT u.id, 'UPDATE', row_to_json(old), row_to_json(new)
FROM users u
WHERE u.name ILIKE '%john%'
  AND u.updated_at::date = CURRENT_DATE
RETURNING audit_log.id, audit_log.created_at;
