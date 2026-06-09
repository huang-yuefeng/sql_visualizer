-- Nested subqueries and complex logical expressions
SELECT
    p.product_name,
    p.category,
    p.price,
    p.stock,
    p.rating
FROM products p
WHERE p.category IN (
    SELECT DISTINCT p2.category
    FROM products p2
    WHERE p2.rating > 4.5
      AND p2.is_active = TRUE
      AND p2.stock > 0
)
  AND p.price > (
      SELECT AVG(p3.price)
      FROM products p3
      WHERE p3.category = p.category
  )
  AND (
      p.rating >= 4.0
      OR p.stock < 10
  )
  AND p.is_active = TRUE;

-- INSERT with SELECT and conditions
INSERT INTO logs (table_name, operation, record_id, old_value, new_value, changed_by)
SELECT 'products', 'UPDATE', p.product_id,
       CONCAT('price=', p.price, ',stock=', p.stock),
       CONCAT('price=', p.price * 1.1, ',stock=', p.stock - 5),
       1
FROM products p
WHERE p.category = 'electronics'
  AND p.is_active = TRUE
  AND p.stock >= 5;
