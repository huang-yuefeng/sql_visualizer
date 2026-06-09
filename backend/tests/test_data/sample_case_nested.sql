-- sample_case_nested.sql
-- Nested CASE expressions with computed columns

SELECT
    a.account_id,
    a.balance,
    a.risk_score,
    CASE
        WHEN a.risk_score >= 80 THEN 'LOW_RISK'
        WHEN a.risk_score >= 50 THEN
            CASE
                WHEN a.balance > 500000 THEN 'MEDIUM_HIGH_VALUE'
                ELSE 'MEDIUM_STANDARD'
            END
        ELSE 'HIGH_RISK'
    END AS risk_category,
    COALESCE(
        CAST(JSON_EXTRACT(a.compliance_flags, '$.aml_review') AS CHAR),
        'NONE'
    ) AS aml_review_status,
    a.kyc_verified_date IS NOT NULL AND a.balance > 0 AS is_active_account
FROM gps_accounts a
WHERE a.account_status = 'ACTIVE'
