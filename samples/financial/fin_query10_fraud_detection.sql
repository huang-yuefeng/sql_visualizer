-- ============================================================================
-- GPS Financial SQL #10: Real-Time Fraud Detection & Chargeback Analytics
-- ============================================================================
-- Inspired by Borghi97/fraud-detection-sql (github.com/Borghi97/fraud-detection-sql)
-- — a production fraud detection pipeline with FastAPI + SQL analytics used
-- as reference for financial fraud systems.
--
-- Real-world patterns incorporated:
--   * PERCENTILE_CONT() for statistical thresholding (quartile-based risk bands)
--   * LEAD() window for rapid-transaction detection (gap ≤ 5 minutes)
--   * Multi-factor fraud scoring (velocity, device, geo, amount)
--   * Chargeback rate computation with view-style aggregation
--   * Risk classification tiers based on statistical percentiles
--   * Time-window gap detection for card-testing / enumeration attacks
-- ============================================================================

WITH
-- ── Step 1: Compute statistical thresholds from historical data ──────────
transaction_stats AS (
    SELECT
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY t.amount)
            OVER ()                                               AS q1_amount,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY t.amount)
            OVER ()                                               AS median_amount,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY t.amount)
            OVER ()                                               AS q3_amount,
        PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY t.amount)
            OVER ()                                               AS p90_amount,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY t.amount)
            OVER ()                                               AS p99_amount,
        AVG(t.amount) OVER ()                                     AS avg_amount,
        STDDEV(t.amount) OVER ()                                  AS stddev_amount,
        t.txn_id,
        t.amount,
        t.txn_date                                                AS transaction_ts,
        t.cardholder_account_id                                   AS user_id,
        t.device_id,
        t.geo_location,
        t.card_network,
        t.merchant_id,
        t.txn_type,
        t.risk_score,
        -- Normalize: is this a chargeback?
        CASE WHEN t.txn_type = 'CHARGEBACK' THEN 1 ELSE 0 END    AS has_cbk
    FROM gps_transactions t
    WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 90 DAY)
),

-- ── Step 2: Classify transactions by amount risk tier ───────────────────
classified_transactions AS (
    SELECT
        ts.*,
        CASE
            WHEN ts.amount >= ts.p99_amount THEN 'CRITICAL'
            WHEN ts.amount >= ts.p90_amount THEN 'HIGH'
            WHEN ts.amount >= ts.q3_amount   THEN 'MEDIUM_HIGH'
            WHEN ts.amount >= ts.median_amount THEN 'MEDIUM'
            WHEN ts.amount >= ts.q1_amount   THEN 'MEDIUM_LOW'
            ELSE 'LOW'
        END                                                       AS amount_class,
        -- Z-score: how many standard deviations from mean
        CASE
            WHEN ts.stddev_amount > 0
            THEN ROUND((ts.amount - ts.avg_amount) / ts.stddev_amount, 2)
            ELSE 0
        END                                                       AS amount_zscore
    FROM transaction_stats ts
),

-- ── Step 3: Detect rapid consecutive transactions (card testing) ───────
rapid_transactions AS (
    SELECT
        ct.*,
        -- Next transaction timestamp for same user
        LEAD(ct.transaction_ts, 1) OVER (
            PARTITION BY ct.user_id
            ORDER BY ct.transaction_ts
        )                                                         AS next_ts_user,
        -- Next transaction timestamp for same device
        LEAD(ct.transaction_ts, 1) OVER (
            PARTITION BY ct.device_id
            ORDER BY ct.transaction_ts
        )                                                         AS next_ts_device,
        -- Previous transaction amount for velocity check
        LAG(ct.amount, 1) OVER (
            PARTITION BY ct.user_id
            ORDER BY ct.transaction_ts
        )                                                         AS prev_amount_user,
        -- Transaction count per user in last 24 hours (rolling window)
        COUNT(ct.txn_id) OVER (
            PARTITION BY ct.user_id
            ORDER BY ct.transaction_ts
            RANGE BETWEEN INTERVAL '24' HOUR PRECEDING AND CURRENT ROW
        )                                                         AS user_24h_txn_count,
        -- Transaction count per device in last 1 hour
        COUNT(ct.txn_id) OVER (
            PARTITION BY ct.device_id
            ORDER BY ct.transaction_ts
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                                         AS device_1h_txn_count
    FROM classified_transactions ct
),

-- ── Step 4: Compute multi-factor fraud scores ───────────────────────────
fraud_scored AS (
    SELECT
        rt.*,
        -- Time gap to next user transaction (minutes)
        CASE
            WHEN rt.next_ts_user IS NOT NULL
            THEN TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_user)
            ELSE NULL
        END                                                       AS gap_minutes_user,
        -- Time gap to next device transaction (minutes)
        CASE
            WHEN rt.next_ts_device IS NOT NULL
            THEN TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_device)
            ELSE NULL
        END                                                       AS gap_minutes_device,
        -- Flag: rapid user transaction (≤ 5 min)
        CASE
            WHEN rt.next_ts_user IS NOT NULL
                 AND TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_user) <= 5
            THEN 1 ELSE 0
        END                                                       AS rapid_user_flag,
        -- Flag: rapid device transaction (≤ 5 min)
        CASE
            WHEN rt.next_ts_device IS NOT NULL
                 AND TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_device) <= 5
            THEN 1 ELSE 0
        END                                                       AS rapid_device_flag,
        -- Velocity: amount jump vs previous transaction
        CASE
            WHEN rt.prev_amount_user IS NOT NULL AND rt.prev_amount_user > 0
            THEN ROUND((rt.amount - rt.prev_amount_user) / rt.prev_amount_user * 100, 2)
            ELSE NULL
        END                                                       AS amount_velocity_pct,
        -- Composite fraud indicator (weighted sum)
        (
            COALESCE(rt.risk_score, 0) * 0.35
            + CASE WHEN rt.amount_zscore > 2.0 THEN 25 ELSE 0 END
            + CASE WHEN rt.user_24h_txn_count > 20 THEN 20 ELSE 0 END
            + CASE WHEN rt.device_1h_txn_count > 10 THEN 15 ELSE 0 END
            + CASE
                WHEN rt.next_ts_user IS NOT NULL
                     AND TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_user) <= 5
                THEN 20 ELSE 0
              END
            + CASE
                WHEN rt.next_ts_device IS NOT NULL
                     AND TIMESTAMPDIFF(MINUTE, rt.transaction_ts, rt.next_ts_device) <= 5
                THEN 10 ELSE 0
              END
            + CASE WHEN rt.has_cbk = 1 THEN 30 ELSE 0 END
        )                                                         AS composite_fraud_score,
        -- Decision: recommend approve/deny/review
        CASE
            WHEN rt.amount_class = 'CRITICAL' AND rt.has_cbk = 1
                THEN 'DENY'
            WHEN rt.amount_class IN ('HIGH', 'CRITICAL')
                 AND (rt.rapid_user_flag = 1 OR rt.rapid_device_flag = 1)
                THEN 'DENY'
            WHEN rt.risk_score >= 80 AND rt.amount_zscore > 1.5
                THEN 'REVIEW'
            WHEN rt.user_24h_txn_count > 15 OR rt.device_1h_txn_count > 8
                THEN 'REVIEW'
            WHEN rt.has_cbk = 1
                THEN 'REVIEW'
            ELSE 'APPROVE'
        END                                                       AS fraud_decision
    FROM rapid_transactions rt
)

-- ── Step 5: Aggregate fraud summary by amount class ────────────────────
SELECT
    fs.amount_class,
    COUNT(fs.txn_id)                                              AS total_transactions,
    SUM(fs.has_cbk)                                               AS total_chargebacks,
    SUM(fs.rapid_user_flag)                                       AS total_rapid_user,
    SUM(fs.rapid_device_flag)                                     AS total_rapid_device,
    ROUND(AVG(fs.amount), 2)                                      AS avg_amount,
    ROUND(AVG(fs.amount_zscore), 2)                               AS avg_zscore,
    ROUND(AVG(fs.amount_velocity_pct), 2)                         AS avg_velocity_pct,
    -- Chargeback rate as percentage
    ROUND(
        SUM(fs.has_cbk) * 100.0 / NULLIF(COUNT(fs.txn_id), 0),
        2
    )                                                             AS cbk_rate_pct,
    -- Rapid transaction rate
    ROUND(
        (SUM(fs.rapid_user_flag) + SUM(fs.rapid_device_flag))
        * 100.0 / NULLIF(COUNT(fs.txn_id), 0),
        2
    )                                                             AS rapid_rate_pct,
    -- Fraud decision breakdown
    SUM(CASE WHEN fs.fraud_decision = 'DENY'   THEN 1 ELSE 0 END) AS deny_count,
    SUM(CASE WHEN fs.fraud_decision = 'REVIEW' THEN 1 ELSE 0 END) AS review_count,
    SUM(CASE WHEN fs.fraud_decision = 'APPROVE'THEN 1 ELSE 0 END) AS approve_count,
    ROUND(AVG(fs.composite_fraud_score), 1)                       AS avg_fraud_score,
    -- Median gap between transactions
    ROUND(AVG(fs.gap_minutes_user), 1)                            AS avg_user_gap_min,
    ROUND(AVG(fs.gap_minutes_device), 1)                          AS avg_device_gap_min
FROM fraud_scored fs
GROUP BY fs.amount_class
ORDER BY
    CASE fs.amount_class
        WHEN 'CRITICAL'   THEN 1
        WHEN 'HIGH'       THEN 2
        WHEN 'MEDIUM_HIGH'THEN 3
        WHEN 'MEDIUM'     THEN 4
        WHEN 'MEDIUM_LOW' THEN 5
        WHEN 'LOW'        THEN 6
    END
