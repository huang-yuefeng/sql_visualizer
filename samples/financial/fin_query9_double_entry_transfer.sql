-- ============================================================================
-- GPS Financial SQL #9: Double-Entry Transfer with Balance Validation
-- ============================================================================
-- Inspired by pg-ledger (github.com/arkamfahry/pg-ledger) — a production
-- PostgreSQL double-entry accounting system used as reference by financial
-- applications. Adapted for MySQL/GPS domain.
--
-- Patterns from real-world code:
--   * Balance snapshot capture (before/after per account)
--   * Optimistic locking via version column
--   * Debit/credit entries inserted atomically
--   * Balance constraint validation (no negative balance for certain accounts)
--   * Multi-currency settlement with FX conversion
--   * RETURNING-style output via final SELECT
-- ============================================================================

WITH
-- ── Step 1: Collect unsettled transactions needing transfer ───────────────
pending_settlements AS (
    SELECT
        t.txn_id,
        t.cardholder_account_id,
        t.merchant_id,
        t.amount                                                  AS txn_amount,
        t.currency_code                                           AS txn_currency,
        t.settlement_currency,
        t.settlement_amount,
        t.merchant_discount,
        t.interchange_fee,
        t.network_fee,
        t.processing_fee,
        t.txn_date,
        t.card_network
    FROM gps_transactions t
    WHERE t.txn_status = 'AUTHORIZED'
      AND t.txn_type = 'PURCHASE'
      AND t.settlement_amount IS NOT NULL
      AND t.cardholder_account_id IS NOT NULL
      AND t.merchant_id IS NOT NULL
      AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY)
),

-- ── Step 2: Look up current account state for both parties ──────────────
account_snapshots AS (
    SELECT
        ps.*,
        -- Cardholder account state
        ch.account_id                                             AS cardholder_acc_id,
        ch.balance                                                AS cardholder_balance,
        ch.available_balance                                      AS cardholder_available,
        ch.version                                                AS cardholder_version,
        ch.allow_negative                                         AS cardholder_allow_neg,
        -- Merchant account state
        m.account_id                                              AS merchant_acc_id,
        m.balance                                                 AS merchant_balance,
        m.available_balance                                       AS merchant_available,
        m.version                                                 AS merchant_version,
        -- Latest FX rate for the settlement currency pair
        (SELECT er.mid_rate
         FROM gps_exchange_rates er
         WHERE er.from_currency = ps.txn_currency
           AND er.to_currency = ps.settlement_currency
           AND er.rate_type = 'SPOT'
           AND er.is_active = 1
         ORDER BY er.rate_date DESC
         LIMIT 1
        )                                                         AS applied_fx_rate
    FROM pending_settlements ps
    INNER JOIN gps_accounts ch
        ON ch.entity_type = 'CUSTOMER'
       AND ch.entity_id = ps.cardholder_account_id
       AND ch.account_status = 'ACTIVE'
    INNER JOIN gps_accounts m
        ON m.entity_type = 'MERCHANT'
       AND m.entity_id = ps.merchant_id
       AND m.account_status IN ('ACTIVE', 'RESTRICTED')
),

-- ── Step 3: Compute the net amounts for each party ──────────────────────
transfer_calculations AS (
    SELECT
        asnap.*,
        -- Cardholder debit amount (in settlement currency)
        ROUND(asnap.settlement_amount, 4)                         AS debit_amount,
        -- Merchant credit: settlement_amount minus all fees
        ROUND(
            asnap.settlement_amount
            - COALESCE(asnap.merchant_discount, 0)
            - COALESCE(asnap.interchange_fee, 0)
            - COALESCE(asnap.network_fee, 0)
            - COALESCE(asnap.processing_fee, 0),
            4
        )                                                         AS credit_amount,
        -- Cardholder new balance
        asnap.cardholder_balance - asnap.settlement_amount        AS cardholder_new_balance,
        -- Cardholder new available balance
        asnap.cardholder_available - asnap.settlement_amount      AS cardholder_new_available,
        -- Merchant new balance
        asnap.merchant_balance
        + asnap.settlement_amount
        - COALESCE(asnap.merchant_discount, 0)
        - COALESCE(asnap.interchange_fee, 0)
        - COALESCE(asnap.network_fee, 0)
        - COALESCE(asnap.processing_fee, 0)                       AS merchant_new_balance,
        -- Validation: cardholder must have sufficient available balance
        CASE
            WHEN asnap.cardholder_allow_neg = FALSE
                 AND (asnap.cardholder_available - asnap.settlement_amount) < 0
            THEN 'INSUFFICIENT_FUNDS'
            WHEN asnap.cardholder_acc_id = asnap.merchant_acc_id
            THEN 'SAME_ACCOUNT'
            WHEN asnap.settlement_amount <= 0
            THEN 'INVALID_AMOUNT'
            ELSE 'VALID'
        END                                                       AS validation_result
    FROM account_snapshots asnap
),

-- ── Step 4: Filter valid transfers and compute fee breakdown ────────────
valid_transfers AS (
    SELECT
        tc.*,
        -- Total fees collected across all parties
        COALESCE(tc.merchant_discount, 0)
        + COALESCE(tc.interchange_fee, 0)
        + COALESCE(tc.network_fee, 0)
        + COALESCE(tc.processing_fee, 0)                          AS total_fees,
        -- Effective fee rate as percentage
        ROUND(
            (COALESCE(tc.merchant_discount, 0)
             + COALESCE(tc.interchange_fee, 0)
             + COALESCE(tc.network_fee, 0)
             + COALESCE(tc.processing_fee, 0))
            * 100.0 / NULLIF(tc.settlement_amount, 0),
            4
        )                                                         AS effective_fee_rate_pct,
        -- FX impact
        CASE
            WHEN tc.txn_currency != tc.settlement_currency
                 AND tc.applied_fx_rate IS NOT NULL
            THEN ROUND(
                tc.txn_amount * tc.applied_fx_rate - tc.settlement_amount, 4
            )
            ELSE 0
        END                                                       AS fx_adjustment,
        -- Cardholder new version (simulate optimistic locking)
        tc.cardholder_version + 1                                  AS cardholder_new_version,
        tc.merchant_version + 1                                    AS merchant_new_version,
        CURRENT_TIMESTAMP                                         AS transfer_timestamp
    FROM transfer_calculations tc
    WHERE tc.validation_result = 'VALID'
)

-- ── Output: Transfer journal with balance snapshots ────────────────────
SELECT
    vt.txn_id,
    vt.cardholder_acc_id                                          AS debit_account_id,
    vt.merchant_acc_id                                            AS credit_account_id,
    vt.debit_amount,
    vt.credit_amount,
    vt.txn_currency,
    vt.settlement_currency,
    vt.applied_fx_rate,
    vt.fx_adjustment,
    vt.cardholder_balance                                         AS debit_balance_before,
    vt.cardholder_new_balance                                     AS debit_balance_after,
    vt.merchant_balance                                           AS credit_balance_before,
    vt.merchant_new_balance                                       AS credit_balance_after,
    vt.total_fees,
    vt.effective_fee_rate_pct,
    vt.merchant_discount,
    vt.interchange_fee,
    vt.network_fee,
    vt.processing_fee,
    vt.card_network,
    vt.cardholder_version                                         AS debit_version_expected,
    vt.cardholder_new_version                                     AS debit_version_new,
    vt.merchant_version                                           AS credit_version_expected,
    vt.merchant_new_version                                       AS credit_version_new,
    vt.validation_result,
    vt.transfer_timestamp,
    -- Flag for accounts exceeding risk thresholds
    CASE
        WHEN vt.cardholder_new_balance < -1000 THEN 'CARDHOLDER_OVERDRAWN'
        WHEN vt.total_fees > vt.settlement_amount * 0.1 THEN 'HIGH_FEE_ALERT'
        ELSE 'OK'
    END                                                           AS alert_flag
FROM valid_transfers vt
ORDER BY vt.transfer_timestamp DESC
