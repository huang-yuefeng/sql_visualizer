-- Step 2: Enrich customer data from CRM
INSERT INTO stg_customers (customer_id, name, segment, region)
SELECT c.customer_id, c.full_name, c.segment, c.region
FROM crm_customers c
WHERE c.is_active = 1
  AND c.region IN ('NA', 'EMEA', 'APAC');
