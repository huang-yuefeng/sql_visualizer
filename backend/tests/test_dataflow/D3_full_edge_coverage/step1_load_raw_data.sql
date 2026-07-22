-- Step 1: Load raw transaction data with all edge type scenarios
INSERT INTO raw_transactions (txn_id, customer_id, amount, fee, txn_date, status, region)
SELECT
    t.id AS txn_id,
    t.cust_id AS customer_id,
    t.amount,
    t.fee_amount,
    t.transaction_date AS txn_date,
    t.status_code AS status,
    r.region_name AS region
FROM source_transactions t
JOIN source_regions r ON t.region_id = r.id
WHERE t.transaction_date >= '2024-01-01'
  AND t.status_code IN ('COMPLETED', 'PENDING');
