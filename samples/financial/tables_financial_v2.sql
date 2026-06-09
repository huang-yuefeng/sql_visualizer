-- ============================================================================
-- GPS (Global Payments System) Financial Domain — Enhanced Schema v2
-- ============================================================================
-- Based on real-world patterns from open-source payment ledgers (pg-ledger,
-- iPay) and fraud detection systems. Adds double-entry bookkeeping, audit
-- trail with versioning, fee schedules with tiered JSON, and proper
-- DECIMAL precision for financial amounts.
-- ============================================================================

-- ── Core: Accounts with balance constraints ────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_accounts (
    account_id          VARCHAR(26)     NOT NULL PRIMARY KEY,   -- ULID format
    entity_type         VARCHAR(20)     NOT NULL,               -- MERCHANT, CUSTOMER, ISSUER, ACQUIRER, NETWORK
    entity_id           VARCHAR(50)     NOT NULL,
    account_name        VARCHAR(100)    NOT NULL,
    currency_code       CHAR(3)         NOT NULL DEFAULT 'USD',
    balance             DECIMAL(18,4)   NOT NULL DEFAULT 0.0000,
    available_balance   DECIMAL(18,4)   NOT NULL DEFAULT 0.0000,
    reserve_balance     DECIMAL(18,4)   NOT NULL DEFAULT 0.0000,
    allow_negative      BOOLEAN         NOT NULL DEFAULT FALSE,
    allow_positive      BOOLEAN         NOT NULL DEFAULT TRUE,
    version             BIGINT          NOT NULL DEFAULT 0,     -- optimistic locking
    risk_rating         VARCHAR(20)     DEFAULT NULL,
    kyc_status          VARCHAR(30)     DEFAULT 'PENDING',
    compliance_flags    JSON            DEFAULT NULL,
    account_status      VARCHAR(20)     NOT NULL DEFAULT 'ACTIVE',
    opened_at           TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at           TIMESTAMP       DEFAULT NULL,
    UNIQUE INDEX idx_account_entity (entity_type, entity_id),
    INDEX idx_account_status (account_status),
    INDEX idx_account_currency (currency_code),
    INDEX idx_account_risk (risk_rating)
) ENGINE=InnoDB;

-- ── Core: Transactions with multi-party settlement fields ──────────────────
CREATE TABLE IF NOT EXISTS gps_transactions (
    txn_id              VARCHAR(26)     NOT NULL PRIMARY KEY,
    txn_type            VARCHAR(20)     NOT NULL,               -- PURCHASE, REFUND, CHARGEBACK, REVERSAL, AUTHORIZATION
    txn_status          VARCHAR(20)     NOT NULL DEFAULT 'PENDING',
    amount              DECIMAL(18,4)   NOT NULL,
    currency_code       CHAR(3)         NOT NULL,
    settlement_currency CHAR(3)         NOT NULL DEFAULT 'USD',
    settlement_amount   DECIMAL(18,4)   DEFAULT NULL,
    fx_rate             DECIMAL(12,8)   DEFAULT NULL,

    -- Multi-party references
    cardholder_account_id VARCHAR(26)   DEFAULT NULL,
    merchant_id         VARCHAR(26)     DEFAULT NULL,
    acquirer_id         VARCHAR(26)     DEFAULT NULL,
    issuer_id           VARCHAR(26)     DEFAULT NULL,
    card_network        VARCHAR(20)     DEFAULT NULL,
    settlement_batch_id VARCHAR(26)     DEFAULT NULL,

    -- Fee breakdown
    merchant_discount   DECIMAL(18,4)   DEFAULT 0.0000,
    interchange_fee     DECIMAL(18,4)   DEFAULT 0.0000,
    network_fee         DECIMAL(18,4)   DEFAULT 0.0000,
    processing_fee      DECIMAL(18,4)   DEFAULT 0.0000,

    -- Risk and fraud
    risk_score          DECIMAL(5,2)    DEFAULT NULL,
    fraud_check_result  VARCHAR(30)     DEFAULT NULL,
    device_id           VARCHAR(100)    DEFAULT NULL,
    ip_address          VARCHAR(45)     DEFAULT NULL,
    geo_location        POINT           DEFAULT NULL,

    -- Metadata
    card_present        BOOLEAN         DEFAULT TRUE,
    mcc                 VARCHAR(4)      DEFAULT NULL,           -- Merchant Category Code
    auth_code           VARCHAR(20)     DEFAULT NULL,
    txn_date            TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_txn_merchant (merchant_id),
    INDEX idx_txn_account (cardholder_account_id),
    INDEX idx_txn_batch (settlement_batch_id),
    INDEX idx_txn_date (txn_date),
    INDEX idx_txn_type_status (txn_type, txn_status),
    INDEX idx_txn_network (card_network),
    INDEX idx_txn_risk (risk_score)
) ENGINE=InnoDB;

-- ── Settlement Batches ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_settlement_batches (
    batch_id            VARCHAR(26)     NOT NULL PRIMARY KEY,
    batch_status        VARCHAR(20)     NOT NULL DEFAULT 'OPEN',
    settlement_date     DATE            NOT NULL,
    currency_code       CHAR(3)         NOT NULL,
    total_amount        DECIMAL(18,4)   NOT NULL DEFAULT 0.0000,
    total_transactions  INT             NOT NULL DEFAULT 0,
    net_settlement      DECIMAL(18,4)   NOT NULL DEFAULT 0.0000,
    counterparty_a      VARCHAR(26)     DEFAULT NULL,
    counterparty_b      VARCHAR(26)     DEFAULT NULL,
    clearinghouse_ref   VARCHAR(100)    DEFAULT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at           TIMESTAMP       DEFAULT NULL,
    INDEX idx_batch_status (batch_status),
    INDEX idx_batch_date (settlement_date),
    INDEX idx_batch_counterparty (counterparty_a, counterparty_b)
) ENGINE=InnoDB;

-- ── Double-Entry Ledger Entries (pg-ledger inspired) ───────────────────────
CREATE TABLE IF NOT EXISTS gps_entries (
    entry_id            VARCHAR(26)     NOT NULL PRIMARY KEY,
    account_id          VARCHAR(26)     NOT NULL,
    txn_id              VARCHAR(26)     NOT NULL,
    amount              DECIMAL(18,4)   NOT NULL,               -- positive = credit, negative = debit
    balance_before      DECIMAL(18,4)   NOT NULL,
    balance_after       DECIMAL(18,4)   NOT NULL,
    account_version     BIGINT          NOT NULL,
    entry_type          VARCHAR(20)     NOT NULL,               -- DEBIT, CREDIT
    description         VARCHAR(255)    DEFAULT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES gps_accounts (account_id),
    FOREIGN KEY (txn_id) REFERENCES gps_transactions (txn_id),
    INDEX idx_entry_account (account_id),
    INDEX idx_entry_txn (txn_id),
    INDEX idx_entry_date (created_at)
) ENGINE=InnoDB;

-- ── Fee Schedules with JSON tier definition ─────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_fee_schedules (
    fee_id              VARCHAR(26)     NOT NULL PRIMARY KEY,
    fee_type            VARCHAR(20)     NOT NULL,               -- PERCENTAGE, FLAT, TIERED, HYBRID
    applicable_entity_type VARCHAR(20)  NOT NULL,
    applicable_entity_id   VARCHAR(50)  NOT NULL,
    card_network        VARCHAR(20)     DEFAULT NULL,
    fee_structure       JSON            NOT NULL,               -- tier thresholds, rates, flat amounts
    effective_from      DATE            NOT NULL,
    effective_to        DATE            DEFAULT NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fee_entity (applicable_entity_type, applicable_entity_id),
    INDEX idx_fee_network (card_network),
    INDEX idx_fee_effective (effective_from, effective_to)
) ENGINE=InnoDB;

-- ── Exchange Rates ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_exchange_rates (
    rate_id             VARCHAR(26)     NOT NULL PRIMARY KEY,
    from_currency       CHAR(3)         NOT NULL,
    to_currency         CHAR(3)         NOT NULL,
    rate_type           VARCHAR(10)     NOT NULL DEFAULT 'SPOT',
    bid_rate            DECIMAL(12,8)   NOT NULL,
    ask_rate            DECIMAL(12,8)   NOT NULL,
    mid_rate            DECIMAL(12,8)   NOT NULL,
    spread              DECIMAL(12,8)   NOT NULL,
    provider_name       VARCHAR(50)     DEFAULT NULL,
    rate_date           DATE            NOT NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fx_pair (from_currency, to_currency),
    INDEX idx_fx_date (rate_date)
) ENGINE=InnoDB;

-- ── Reconciliation Log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_reconciliation (
    recon_id            VARCHAR(26)     NOT NULL PRIMARY KEY,
    entity_type         VARCHAR(30)     NOT NULL,
    entity_id           VARCHAR(100)    NOT NULL,
    recon_type          VARCHAR(30)     NOT NULL,               -- INTERNAL, EXTERNAL, GL, BANK
    recon_status        VARCHAR(20)     NOT NULL DEFAULT 'PENDING',
    resolution          VARCHAR(30)     DEFAULT NULL,           -- MERCHANT_FAVOR, CUSTOMER_FAVOR, SPLIT
    internal_amount     DECIMAL(18,4)   NOT NULL,
    external_amount     DECIMAL(18,4)   NOT NULL,
    variance            DECIMAL(18,4)   NOT NULL,
    variance_pct        DECIMAL(8,4)    DEFAULT NULL,
    recon_date          DATE            NOT NULL,
    matched_by          VARCHAR(50)     DEFAULT NULL,
    notes               TEXT            DEFAULT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recon_entity (entity_type, entity_id),
    INDEX idx_recon_status (recon_status),
    INDEX idx_recon_date (recon_date)
) ENGINE=InnoDB;

-- ── Risk Scores (ML + Rule-based) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_risk_scores (
    score_id            VARCHAR(26)     NOT NULL PRIMARY KEY,
    entity_type         VARCHAR(30)     NOT NULL,
    entity_id           VARCHAR(100)    NOT NULL,
    composite_score     DECIMAL(5,2)    NOT NULL,
    ml_score            DECIMAL(5,2)    DEFAULT NULL,
    rule_score          DECIMAL(5,2)    DEFAULT NULL,
    velocity_score      DECIMAL(5,2)    DEFAULT NULL,
    device_score        DECIMAL(5,2)    DEFAULT NULL,
    geo_score           DECIMAL(5,2)    DEFAULT NULL,
    behavioral_score    DECIMAL(5,2)    DEFAULT NULL,
    model_version       VARCHAR(20)     DEFAULT NULL,
    scored_at           TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_risk_entity (entity_type, entity_id),
    INDEX idx_risk_scored (scored_at DESC),
    INDEX idx_risk_composite (composite_score)
) ENGINE=InnoDB;

-- ── Audit Trail (change tracking) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_audit_trail (
    audit_id            VARCHAR(26)     NOT NULL PRIMARY KEY,
    entity_type         VARCHAR(30)     NOT NULL,
    entity_id           VARCHAR(100)    NOT NULL,
    action              VARCHAR(30)     NOT NULL,               -- CREATE, UPDATE, DELETE, FLAG
    field_name          VARCHAR(50)     NOT NULL,
    old_value           TEXT            DEFAULT NULL,
    new_value           TEXT            DEFAULT NULL,
    changed_by          VARCHAR(100)    NOT NULL,
    changed_by_role     VARCHAR(30)     DEFAULT NULL,
    change_timestamp    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    correlation_id      VARCHAR(26)     DEFAULT NULL,
    change_reason       VARCHAR(255)    DEFAULT NULL,
    approved_by         VARCHAR(100)    DEFAULT NULL,
    INDEX idx_audit_entity (entity_type, entity_id),
    INDEX idx_audit_timestamp (change_timestamp),
    INDEX idx_audit_correlation (correlation_id)
) ENGINE=InnoDB;
