-- Bare `id` and `name` with BOTH visible tables owning them (customers and
-- orders both have id/name per ddl_tables.sql) — genuinely ambiguous:
-- S3 (≥2 tables) and S4b (≥2 owners) must decline, never guess.
SELECT id, name FROM customers JOIN orders ON customers.cust_key = orders.order_key;
