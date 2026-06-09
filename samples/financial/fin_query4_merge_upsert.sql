-- ============================================================================
-- GPS Financial SQL #4: MERGE/UPSERT - Account Balance Updates from Settlement
-- Update account balances from settled transactions
-- ============================================================================
MERGE INTO gps_accounts AS target
USING (
    SELECT
        t.source_account_id AS account_id,
        t.txn_type,
        t.amount,
        t.fee_amount,
        t.net_amount,
        t.settlement_batch_id,
        t.settlement_date,
        t.txn_id,
        t.currency_code,
        COUNT(*) OVER (PARTITION BY t.source_account_id) AS daily_txn_count_batch,
        SUM(t.amount) OVER (PARTITION BY t.source_account_id) AS daily_amount_batch
    FROM gps_transactions t
    WHERE t.txn_status = 'SETTLED'
      AND t.settlement_date = CURRENT_DATE
      AND t.txn_type IN ('PAYMENT', 'REFUND')
      AND t.source_account_id IS NOT NULL
) AS source
ON target.account_id = source.account_id
   AND target.account_status = 'ACTIVE'

WHEN MATCHED AND source.txn_type = 'PAYMENT' THEN
    UPDATE SET
        target.balance             = target.balance - source.amount - COALESCE(source.fee_amount, 0),
        target.available_balance   = target.available_balance - source.amount - COALESCE(source.fee_amount, 0),
        target.daily_txn_count     = target.daily_txn_count + 1,
        target.monthly_txn_count   = target.monthly_txn_count + 1,
        target.total_txn_count     = target.total_txn_count + 1,
        target.last_txn_id         = source.txn_id,
        target.last_activity_date  = source.settlement_date,
        target.updated_at          = CURRENT_TIMESTAMP

WHEN MATCHED AND source.txn_type = 'REFUND' THEN
    UPDATE SET
        target.balance             = target.balance + source.amount,
        target.available_balance   = target.available_balance + source.amount,
        target.pending_credits     = target.pending_credits + source.amount,
        target.daily_txn_count     = target.daily_txn_count + 1,
        target.monthly_txn_count   = target.monthly_txn_count + 1,
        target.total_txn_count     = target.total_txn_count + 1,
        target.last_txn_id         = source.txn_id,
        target.last_activity_date  = source.settlement_date,
        target.updated_at          = CURRENT_TIMESTAMP

WHEN NOT MATCHED THEN
    INSERT (
        account_id, account_number, account_type, account_status,
        customer_id, currency_code, balance, available_balance,
        last_txn_id, last_activity_date, created_at, updated_at
    )
    VALUES (
        source.account_id,
        CONCAT('TMP-', source.account_id),
        'EXTERNAL',
        'ACTIVE',
        'UNKNOWN',
        COALESCE(source.currency_code, 'USD'),
        source.net_amount,
        source.net_amount,
        source.txn_id,
        source.settlement_date,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    );

-- ============================================================================
-- GPS Financial SQL #4b: Audit trail recording after merge
-- ============================================================================
INSERT INTO gps_audit_trail (
    entity_type, entity_id, action, field_name,
    old_value, new_value, changed_by, changed_by_role,
    change_timestamp, correlation_id, change_reason
)
SELECT
    'ACCOUNT',
    t.source_account_id,
    'BALANCE_UPDATE',
    'balance',
    CAST((a.balance + COALESCE(t.amount, 0)) AS CHAR),
    CAST(a.balance AS CHAR),
    'SETTLEMENT_ENGINE',
    'SYSTEM',
    CURRENT_TIMESTAMP,
    t.settlement_batch_id,
    CONCAT('Settlement batch: ', t.settlement_batch_id)
FROM gps_transactions t
INNER JOIN gps_accounts a
    ON t.source_account_id = a.account_id
   AND t.txn_status = 'SETTLED'
   AND t.settlement_date = CURRENT_DATE
WHERE t.txn_type = 'PAYMENT'
  AND t.amount > 0
  AND a.account_status = 'ACTIVE';
