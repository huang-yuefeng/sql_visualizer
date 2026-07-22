WITH
level1 AS (
    SELECT id, amount FROM transactions WHERE amount > 0
),
level2 AS (
    SELECT l1.id, l1.amount, l1.amount * 1.1 AS taxed_amount FROM level1 l1
),
level3 AS (
    SELECT l2.id, l2.taxed_amount, ROW_NUMBER() OVER (ORDER BY l2.taxed_amount DESC) AS rn FROM level2 l2
),
level4 AS (
    SELECT l3.id, l3.taxed_amount, l3.rn, CASE WHEN l3.taxed_amount > 100 THEN 'HIGH' ELSE 'LOW' END AS bucket FROM level3 l3
),
level5 AS (
    SELECT l4.id, l4.taxed_amount, l4.bucket, AVG(l4.taxed_amount) OVER () AS global_avg FROM level4 l4
)
SELECT * FROM level5 WHERE bucket = 'HIGH';
