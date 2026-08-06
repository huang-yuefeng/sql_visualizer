-- 1b fixture corpus (never-guess validation): TWO visible tables (customers,
-- orders) both own the generic columns `id` AND `name`; a third table
-- (products) owns only ONE of them (`name`); inventory owns neither.
-- S4b must leave `id`/`name` in the customers⋈orders scope unresolved
-- (ambiguous, ≥2 owners) and resolve `name` in the products⋈inventory
-- scope (unique visible owner: products).
CREATE TABLE customers (id INT, name VARCHAR(50), cust_key INT);
CREATE TABLE orders (id INT, name VARCHAR(50), order_key INT);
CREATE TABLE products (name VARCHAR(100), price DECIMAL(10,2), prod_key INT);
CREATE TABLE inventory (qty INT, location VARCHAR(30), inv_key INT);
