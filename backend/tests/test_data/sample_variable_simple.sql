-- sample_variable_simple.sql
-- Basic SELECT with aliases, WHERE, JOIN — tests basic variable extraction

SELECT
    sb.settlement_batch_id,
    sb.settlement_date,
    sb.batch_status,
    sb.total_amount AS batch_total_amount,
    sb.currency_code,
    sb.total_transactions,
    'SETTLEMENT' AS record_type
FROM gps_settlement_batches sb
WHERE sb.settlement_date >= '2024-01-01'
  AND sb.batch_status IN ('CLOSED', 'RECONCILED')
