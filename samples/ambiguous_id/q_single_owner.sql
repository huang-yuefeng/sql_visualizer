-- Bare `name` where only ONE visible table owns it (products owns name,
-- inventory does not) — S4b must resolve it to products.
SELECT name FROM products JOIN inventory ON products.prod_key = inventory.inv_key;
