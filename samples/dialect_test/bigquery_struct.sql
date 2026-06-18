-- BigQuery: STRUCT, ARRAY, backtick references
SELECT
    o.order_id,
    o.customer.name AS customer_name,
    o.customer.address.city AS city,
    ARRAY_LENGTH(o.items) AS item_count,
    o.items[SAFE_OFFSET(0)].product_name AS first_product
FROM `project-id`.dataset.orders o
WHERE o.order_date >= '2024-01-01'
  AND EXISTS (SELECT 1 FROM UNNEST(o.items) AS item WHERE item.price > 100);
