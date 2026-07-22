-- 05_transform_case.sql: Transform functions and CASE classification
-- Tests: TRANSFORM, CASE, COMPUTED, TABLE_FLOW edges
SELECT
    c.customer_id,
    UPPER(c.customer_name) AS name_upper,
    COALESCE(c.email_address, 'no-email@unknown.com') AS contact_email,
    CAST(c.account_balance AS DECIMAL(12,2)) AS balance_precise,
    ROUND(c.credit_score, -1) AS credit_score_decile,
    CASE
        WHEN c.account_balance > 50000 AND c.credit_score >= 750 THEN 'PREMIUM'
        WHEN c.account_balance > 10000 THEN 'STANDARD'
        WHEN c.account_balance > 0 THEN 'BASIC'
        ELSE 'DORMANT'
    END AS customer_tier
FROM dim_customers c
WHERE c.is_active = 1;
