-- ============================================================================
-- GPS Financial SQL #3: Account Balance Snapshot with LAG/LEAD
-- Daily balance snapshots with period-over-period comparison
-- ============================================================================
WITH daily_balances AS (
    SELECT
        a.account_id,
        a.account_number,
        a.account_type,
        a.customer_id,
        a.currency_code,
        a.balance,
        a.available_balance,
        a.blocked_amount,
        a.pending_credits,
        a.pending_debits,
        a.overdraft_limit,
        a.reserve_amount,
        a.risk_rating,
        a.kyc_status,
        a.region_code,
        a.country_code,
        DATE(a.last_activity_date) AS activity_date,
        a.total_txn_count,
        a.daily_txn_count,
        a.monthly_txn_count,
        a.daily_txn_limit,
        a.monthly_txn_limit
    FROM gps_accounts a
    WHERE a.account_status = 'ACTIVE'
      AND a.last_activity_date >= DATE_SUB(CURRENT_DATE, INTERVAL 90 DAY)
),
account_stats AS (
    SELECT
        db.account_id,
        db.account_number,
        db.account_type,
        db.customer_id,
        db.currency_code,
        db.balance,
        db.available_balance,
        db.blocked_amount,
        db.pending_credits,
        db.pending_debits,
        db.risk_rating,
        db.region_code,
        SUM(t.amount)                            AS total_inflow,
        SUM(CASE WHEN t.amount < 0 THEN t.amount ELSE 0 END) AS total_outflow,
        COUNT(t.txn_id)                          AS txn_count,
        MAX(t.created_at)                        AS last_txn_time,
        MIN(t.created_at)                        AS first_txn_time,
        COUNT(DISTINCT t.merchant_id)            AS unique_merchants,
        SUM(CASE WHEN t.txn_type = 'CHARGEBACK' THEN t.amount ELSE 0 END) AS total_chargebacks,
        SUM(CASE WHEN t.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END) AS high_risk_txns
    FROM daily_balances db
    LEFT JOIN gps_transactions t
        ON db.account_id = t.source_account_id
       AND t.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
       AND t.txn_status IN ('AUTHORIZED', 'SETTLED')
    GROUP BY db.account_id, db.account_number, db.account_type,
             db.customer_id, db.currency_code, db.balance,
             db.available_balance, db.blocked_amount,
             db.pending_credits, db.pending_debits,
             db.risk_rating, db.region_code
)
SELECT
    s.account_id,
    s.account_number,
    s.account_type,
    s.customer_id,
    s.currency_code,
    s.balance,
    s.available_balance,
    (s.balance - s.available_balance)           AS effective_blocked,
    s.blocked_amount,
    s.pending_credits,
    s.pending_debits,
    s.overdraft_limit,
    s.reserve_amount,
    s.risk_rating,
    s.region_code,

    COALESCE(s.total_inflow, 0)                  AS inflow_30d,
    ABS(COALESCE(s.total_outflow, 0))            AS outflow_30d,
    (COALESCE(s.total_inflow, 0) + COALESCE(s.total_outflow, 0)) AS net_flow_30d,
    s.txn_count                                  AS txn_count_30d,
    s.unique_merchants,
    s.high_risk_txns,

    CASE
        WHEN ABS(COALESCE(s.total_outflow, 0)) > 0
        THEN ROUND(COALESCE(s.total_inflow, 0) / ABS(COALESCE(s.total_outflow, 0)), 4)
        ELSE NULL
    END AS cashflow_ratio,

    CASE
        WHEN s.balance < 0 AND s.overdraft_limit > 0
            AND ABS(s.balance) > s.overdraft_limit
        THEN 'OVERDRAFT_EXCEEDED'
        WHEN s.balance < 0 THEN 'OVERDRAFT'
        WHEN s.balance < 1000 THEN 'LOW_BALANCE'
        WHEN s.balance >= 1000 AND s.available_balance < 500 THEN 'LOW_LIQUIDITY'
        ELSE 'HEALTHY'
    END AS balance_health,

    CASE
        WHEN s.high_risk_txns > 5 THEN 'HIGH_RISK_ACCOUNT'
        WHEN s.total_chargebacks > 1000 THEN 'CHARGEBACK_SURVEILLANCE'
        WHEN s.balance > 100000 AND s.risk_rating IN ('D', 'E') THEN 'REVIEW_NEEDED'
        ELSE 'NORMAL'
    END AS account_alert,

    LAG(s.balance) OVER (
        PARTITION BY s.account_id ORDER BY s.currency_code
    ) AS prev_day_balance,

    LEAD(s.balance) OVER (
        PARTITION BY s.account_id ORDER BY s.currency_code
    ) AS next_day_balance,

    AVG(s.balance) OVER (
        PARTITION BY s.region_code, s.account_type
        ORDER BY s.currency_code
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS avg_7day_balance_region,

    SUM(s.total_inflow) OVER (
        PARTITION BY s.customer_id
        ORDER BY s.currency_code
    ) AS customer_cumulative_inflow,

    RANK() OVER (
        PARTITION BY s.region_code, s.account_type
        ORDER BY s.balance DESC
    ) AS balance_rank_in_region,

    NTILE(10) OVER (
        PARTITION BY s.account_type
        ORDER BY s.balance ASC
    ) AS balance_decile,

    s.last_txn_time,
    s.first_txn_time,

    DATEDIFF(
        COALESCE(s.last_txn_time, CURRENT_TIMESTAMP),
        COALESCE(s.first_txn_time, CURRENT_TIMESTAMP)
    ) AS account_age_days

FROM daily_balances db
INNER JOIN account_stats s ON db.account_id = s.account_id

WHERE db.balance IS NOT NULL
  AND (
      s.txn_count_30d > 0
      OR s.balance != 0
      OR s.high_risk_txns > 0
      OR s.risk_rating IN ('D', 'E')
  )

ORDER BY s.region_code, balance_decile, s.balance DESC;
