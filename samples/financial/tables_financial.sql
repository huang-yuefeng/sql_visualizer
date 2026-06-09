-- =========================================================================
-- GPS (Global Payments System) Financial Domain - Core Tables
-- Simulating a large-scale settlement / reconciliation database
-- =========================================================================

-- 1. CORE TRANSACTION TABLE (~50 columns)
CREATE TABLE gps_transactions (
    txn_id              VARCHAR(36)     PRIMARY KEY,
    txn_type            VARCHAR(20)     NOT NULL,   -- PAYMENT/REFUND/CHARGEBACK/REVERSAL
    txn_status          VARCHAR(20)     NOT NULL,   -- PENDING/AUTHORIZED/SETTLED/DECLINED/CANCELLED
    txn_sub_status      VARCHAR(30),                -- AWAITING_FUNDS/FRAUD_HOLD/MANUAL_REVIEW
    source_account_id   VARCHAR(36)     NOT NULL,
    dest_account_id     VARCHAR(36)     NOT NULL,
    amount              DECIMAL(18,4)   NOT NULL,
    currency_code       CHAR(3)         NOT NULL,   -- ISO 4217
    settlement_currency CHAR(3),
    exchange_rate       DECIMAL(14,8),
    settlement_amount   DECIMAL(18,4),
    fee_amount          DECIMAL(14,4),
    fee_currency        CHAR(3),
    tax_amount          DECIMAL(14,4),
    net_amount          DECIMAL(18,4),
    merchant_id         VARCHAR(36),
    merchant_category   VARCHAR(10),                -- MCC code
    acquirer_id         VARCHAR(36),
    issuer_id           VARCHAR(36),
    processor_id        VARCHAR(36),
    network_id          VARCHAR(36),
    gateway_id          VARCHAR(36),
    terminal_id         VARCHAR(50),
    auth_code           VARCHAR(20),
    auth_timestamp      TIMESTAMP(3),
    capture_timestamp   TIMESTAMP(3),
    settlement_timestamp TIMESTAMP(3),
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    batch_id            VARCHAR(36),
    settlement_batch_id VARCHAR(36),
    reconciliation_id   VARCHAR(36),
    settlement_date     DATE,
    posting_date        DATE,
    value_date          DATE,
    txn_description     VARCHAR(255),
    memo                TEXT,
    ip_address          VARCHAR(45),
    device_fingerprint  VARCHAR(128),
    geo_country         CHAR(2),
    geo_city            VARCHAR(100),
    risk_score          DECIMAL(5,2),
    risk_level          VARCHAR(20),                -- LOW/MEDIUM/HIGH/CRITICAL
    fraud_check_status  VARCHAR(20),
    chargeback_reason   VARCHAR(50),
    reversal_reason     VARCHAR(50),
    parent_txn_id       VARCHAR(36),
    correlation_id      VARCHAR(36),
    idempotency_key     VARCHAR(128),
    trace_id            VARCHAR(64),
    version             INT             DEFAULT 1,
    partition_key       INT             NOT NULL    -- data partitioning
) PARTITION BY HASH(partition_key);

-- 2. ACCOUNTS TABLE (~35 columns)
CREATE TABLE gps_accounts (
    account_id          VARCHAR(36)     PRIMARY KEY,
    account_number      VARCHAR(30)     UNIQUE NOT NULL,
    account_type        VARCHAR(20)     NOT NULL,   -- CHECKING/SAVINGS/MERCHANT/WALLET/ESCROW
    account_status      VARCHAR(20)     NOT NULL,   -- ACTIVE/SUSPENDED/CLOSED/FROZEN
    customer_id         VARCHAR(36)     NOT NULL,
    customer_type       VARCHAR(20),                -- INDIVIDUAL/BUSINESS/GOVERNMENT
    currency_code       CHAR(3)         NOT NULL,
    balance             DECIMAL(18,4)   DEFAULT 0,
    available_balance   DECIMAL(18,4)   DEFAULT 0,
    blocked_amount      DECIMAL(18,4)   DEFAULT 0,
    pending_credits     DECIMAL(18,4)   DEFAULT 0,
    pending_debits      DECIMAL(18,4)   DEFAULT 0,
    overdraft_limit     DECIMAL(18,4)   DEFAULT 0,
    reserve_amount      DECIMAL(18,4)   DEFAULT 0,
    daily_txn_limit     DECIMAL(18,4),
    monthly_txn_limit   DECIMAL(18,4),
    single_txn_limit    DECIMAL(18,4),
    daily_txn_count     INT             DEFAULT 0,
    monthly_txn_count   INT             DEFAULT 0,
    total_txn_count     BIGINT          DEFAULT 0,
    kyc_status          VARCHAR(20),                -- NOT_STARTED/IN_PROGRESS/VERIFIED/FAILED
    kyc_level           INT             DEFAULT 0,
    risk_rating         VARCHAR(10),                -- A/B/C/D/E
    compliance_flag     BOOLEAN         DEFAULT FALSE,
    opened_date         DATE            NOT NULL,
    closed_date         DATE,
    last_activity_date  DATE,
    last_txn_id         VARCHAR(36),
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    timezone            VARCHAR(50),
    region_code         VARCHAR(10),
    branch_code         VARCHAR(20),
    country_code        CHAR(2),
    metadata_json       JSON
);

-- 3. SETTLEMENT BATCHES (~25 columns)
CREATE TABLE gps_settlement_batches (
    batch_id                VARCHAR(36)     PRIMARY KEY,
    batch_status            VARCHAR(20)     NOT NULL,   -- OPEN/CLOSED/SUBMITTED/PROCESSING/SETTLED/FAILED
    settlement_date         DATE            NOT NULL,
    settlement_cycle        VARCHAR(10),                -- DAILY/T+1/T+2/WEEKLY
    currency_code           CHAR(3)         NOT NULL,
    total_transactions      INT             DEFAULT 0,
    total_amount            DECIMAL(18,4)   DEFAULT 0,
    total_fees              DECIMAL(14,4)   DEFAULT 0,
    total_chargebacks       DECIMAL(14,4)   DEFAULT 0,
    net_settlement_amount   DECIMAL(18,4)   DEFAULT 0,
    settlement_method       VARCHAR(30),                -- ACH/WIRE/RTGS/FEDWIRE/SWIFT
    settlement_account_id   VARCHAR(36),
    clearinghouse_id        VARCHAR(36),
    bank_reference          VARCHAR(50),
    processor_batch_ref     VARCHAR(50),
    network_batch_ref       VARCHAR(50),
    cutover_time            TIMESTAMP(3),
    submission_time         TIMESTAMP(3),
    acknowledgment_time     TIMESTAMP(3),
    settlement_time         TIMESTAMP(3),
    completion_time         TIMESTAMP(3),
    created_at              TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    created_by              VARCHAR(50),
    retry_count             INT             DEFAULT 0,
    error_code              VARCHAR(20),
    error_message           TEXT,
    notes                   TEXT
);

-- 4. RECONCILIATION LOG (~30 columns)
CREATE TABLE gps_reconciliation (
    recon_id            VARCHAR(36)     PRIMARY KEY,
    recon_type          VARCHAR(30)     NOT NULL,   -- INTERNAL/EXTERNAL/GL/BANK
    recon_status        VARCHAR(20)     NOT NULL,   -- IN_PROGRESS/MATCHED/MISMATCH/UNRESOLVED
    recon_date          DATE            NOT NULL,
    source_system       VARCHAR(50)     NOT NULL,
    target_system       VARCHAR(50)     NOT NULL,
    source_total_count  INT,
    target_total_count  INT,
    source_total_amount DECIMAL(18,4),
    target_total_amount DECIMAL(18,4),
    matched_count       INT             DEFAULT 0,
    matched_amount      DECIMAL(18,4)   DEFAULT 0,
    unmatched_count     INT             DEFAULT 0,
    unmatched_amount    DECIMAL(18,4)   DEFAULT 0,
    discrepancy_count   INT             DEFAULT 0,
    discrepancy_amount  DECIMAL(18,4)   DEFAULT 0,
    currency_code       CHAR(3),
    batch_id            VARCHAR(36),
    recon_period_start  TIMESTAMP(3),
    recon_period_end    TIMESTAMP(3),
    match_threshold     DECIMAL(5,2)    DEFAULT 0.01,
    match_ruleset_id    VARCHAR(36),
    matched_by          VARCHAR(50),
    approved_by         VARCHAR(50),
    approval_status     VARCHAR(20),
    resolution_notes    TEXT,
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    completed_at        TIMESTAMP(3),
    has_exceptions      BOOLEAN         DEFAULT FALSE,
    exception_count     INT             DEFAULT 0,
    sla_breach          BOOLEAN         DEFAULT FALSE
);

-- 5. EXCHANGE RATES (~20 columns)
CREATE TABLE gps_exchange_rates (
    rate_id             VARCHAR(36)     PRIMARY KEY,
    base_currency       CHAR(3)         NOT NULL,
    target_currency     CHAR(3)         NOT NULL,
    rate                DECIMAL(14,8)   NOT NULL,
    rate_type           VARCHAR(20),                -- SPOT/FORWARD/CORPORATE/CENTRAL_BANK
    bid_rate            DECIMAL(14,8),
    ask_rate            DECIMAL(14,8),
    mid_rate            DECIMAL(14,8),
    spread_bps          DECIMAL(8,2),
    source_provider     VARCHAR(50),                -- REUTERS/BLOOMBERG/OANDA/INTERNAL
    effective_date      DATE            NOT NULL,
    effective_time      TIME,
    expiry_date         DATE,
    is_active           BOOLEAN         DEFAULT TRUE,
    valid_from          TIMESTAMP(3),
    valid_to            TIMESTAMP(3),
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    created_by          VARCHAR(50),
    approved_by         VARCHAR(50),
    version             INT             DEFAULT 1,
    notes               VARCHAR(255)
);

-- 6. FEE SCHEDULES (~25 columns)
CREATE TABLE gps_fee_schedules (
    fee_schedule_id     VARCHAR(36)     PRIMARY KEY,
    fee_name            VARCHAR(100)    NOT NULL,
    fee_type            VARCHAR(30)     NOT NULL,   -- PERCENTAGE/FLAT/TIERED/HYBRID
    applies_to          VARCHAR(30)     NOT NULL,   -- MERCHANT/CUSTOMER/PARTNER/INTERNAL
    txn_type            VARCHAR(20),                -- PAYMENT/REFUND/CHARGEBACK
    currency_code       CHAR(3),
    min_amount          DECIMAL(14,4)   DEFAULT 0,
    max_amount          DECIMAL(14,4),
    rate_percentage     DECIMAL(8,4),               -- e.g. 2.5000 = 2.5%
    rate_fixed          DECIMAL(14,4),
    rate_min            DECIMAL(14,4),
    rate_max            DECIMAL(14,4),
    tier_definition     JSON,                       -- [{"from":0,"to":1000,"rate":2.5},{"from":1000,"to":10000,"rate":1.5}]
    discount_rate       DECIMAL(8,4),
    markup_rate         DECIMAL(8,4),
    settlement_currency CHAR(3),
    interchange_rate    DECIMAL(8,4),
    scheme_fee          DECIMAL(14,4),
    processing_fee      DECIMAL(14,4),
    effective_from      DATE            NOT NULL,
    effective_to        DATE,
    is_active           BOOLEAN         DEFAULT TRUE,
    merchant_category   VARCHAR(10),
    region_code         VARCHAR(10),
    account_type        VARCHAR(20),
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    priority            INT             DEFAULT 0,
    notes               TEXT
);

-- 7. RISK SCORES (~20 columns)
CREATE TABLE gps_risk_scores (
    score_id            VARCHAR(36)     PRIMARY KEY,
    entity_id           VARCHAR(36)     NOT NULL,
    entity_type         VARCHAR(20)     NOT NULL,   -- TRANSACTION/ACCOUNT/MERCHANT/IP
    score_value         DECIMAL(5,2)    NOT NULL,
    score_level         VARCHAR(10)     NOT NULL,   -- LOW/MED/HIGH/CRIT
    model_version       VARCHAR(20),
    model_name          VARCHAR(50),
    features_json       JSON,                       -- feature vector used for scoring
    rules_triggered     JSON,                       -- which rules fired
    ml_score            DECIMAL(5,2),
    rule_score          DECIMAL(5,2),
    velocity_score      DECIMAL(5,2),
    device_score        DECIMAL(5,2),
    geo_score           DECIMAL(5,2),
    behavioral_score    DECIMAL(5,2),
    calculated_at       TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    expires_at          TIMESTAMP(3),
    is_overridden       BOOLEAN         DEFAULT FALSE,
    overridden_by       VARCHAR(50),
    override_reason     TEXT,
    created_at          TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3)
);

-- 8. AUDIT TRAIL (~20 columns)
CREATE TABLE gps_audit_trail (
    audit_id            BIGINT          PRIMARY KEY AUTO_INCREMENT,
    entity_type         VARCHAR(50)     NOT NULL,
    entity_id           VARCHAR(36)     NOT NULL,
    action              VARCHAR(30)     NOT NULL,   -- CREATE/UPDATE/DELETE/APPROVE/REJECT
    field_name          VARCHAR(100),
    old_value           TEXT,
    new_value           TEXT,
    changed_by          VARCHAR(50),
    changed_by_role     VARCHAR(50),
    change_timestamp    TIMESTAMP(3)    DEFAULT CURRENT_TIMESTAMP(3),
    source_ip           VARCHAR(45),
    session_id          VARCHAR(128),
    correlation_id      VARCHAR(36),
    change_reason       TEXT,
    approval_status     VARCHAR(20),
    approved_by         VARCHAR(50),
    approved_at         TIMESTAMP(3),
    is_reversible       BOOLEAN         DEFAULT TRUE,
    client_version      VARCHAR(50),
    api_endpoint        VARCHAR(255)
) PARTITION BY HASH(audit_id);
