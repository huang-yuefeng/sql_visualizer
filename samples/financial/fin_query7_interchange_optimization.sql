-- ============================================================================
-- GPS Financial SQL #7: Interchange Fee Optimization & Network Analysis
-- ============================================================================
-- Multi-currency interchange fee optimization using recursive-pattern CTEs,
-- complex window frames (ROWS BETWEEN), self-joins, JSON path extraction,
-- and rolling-window aggregations.
--
-- Business scenario:
--   Optimize interchange fee routing across card networks (Visa, Mastercard,
--   Amex, Discover) by analyzing per-merchant per-network fee structures,
--   comparing effective rates, and identifying cost-saving rerouting
--   opportunities. Includes FX impact on cross-border transactions.
-- ============================================================================

WITH
-- ── Step 1: Get latest FX rates for all currency pairs ────────────────────
latest_fx_rates AS (
    SELECT
        er.from_currency,
        er.to_currency,
        er.bid_rate,
        er.ask_rate,
        er.mid_rate,
        er.spread,
        er.provider_name,
        er.rate_date,
        ROW_NUMBER() OVER (
            PARTITION BY er.from_currency, er.to_currency
            ORDER BY er.rate_date DESC, er.updated_at DESC
        )                                                             AS rate_recency
    FROM gps_exchange_rates er
    WHERE er.rate_type = 'SPOT'
      AND er.rate_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
      AND er.is_active = 1
),

-- ── Step 2: Aggregate transaction volume by merchant, currency, network ──
merchant_network_volume AS (
    SELECT
        t.merchant_id,
        t.currency_code                                             AS txn_currency,
        t.card_network,
        t.txn_type,
        COUNT(t.txn_id)                                             AS txn_count,
        SUM(t.amount)                                               AS total_amount,
        AVG(t.amount)                                               AS avg_txn_amount,
        MIN(t.txn_date)                                             AS first_txn_date,
        MAX(t.txn_date)                                             AS last_txn_date,
        -- Cross-border indicator: settlement currency ≠ transaction currency
        MAX(CASE WHEN t.settlement_currency != t.currency_code
                 THEN 1 ELSE 0 END)                                 AS has_cross_border
    FROM gps_transactions t
    WHERE t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 3 MONTH)
      AND t.txn_status IN ('SETTLED', 'AUTHORIZED')
      AND t.merchant_id IS NOT NULL
      AND t.card_network IS NOT NULL
    GROUP BY t.merchant_id, t.currency_code, t.card_network, t.txn_type
),

-- ── Step 3: Self-join to compare volume across networks for same merchant ──
network_comparison AS (
    SELECT
        a.merchant_id,
        a.txn_currency,
        a.card_network                                             AS primary_network,
        b.card_network                                             AS alternative_network,
        a.txn_count                                                AS primary_txn_count,
        a.total_amount                                             AS primary_total_amount,
        a.avg_txn_amount                                           AS primary_avg_amount,
        b.txn_count                                                AS alt_txn_count,
        b.total_amount                                             AS alt_total_amount,
        b.avg_txn_amount                                           AS alt_avg_amount,
        CASE
            WHEN b.total_amount IS NOT NULL AND b.total_amount > 0
            THEN ROUND(((b.total_amount - a.total_amount) / b.total_amount) * 100, 2)
            ELSE NULL
        END                                                        AS volume_diff_pct,
        a.has_cross_border
    FROM merchant_network_volume a
    LEFT JOIN merchant_network_volume b
        ON a.merchant_id = b.merchant_id
       AND a.txn_currency = b.txn_currency
       AND a.card_network != b.card_network
       AND a.txn_type = b.txn_type
    WHERE a.card_network IN ('VISA', 'MASTERCARD', 'AMEX', 'DISCOVER')
),

-- ── Step 4: Attach fee schedules and compute effective rates ────────────
fee_analysis AS (
    SELECT
        nc.*,
        -- Parse fee schedule JSON for tiered pricing
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.percentage_rate') AS DECIMAL(10,6)),
            0.0
        )                                                           AS base_percentage_rate,
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.flat_fee') AS DECIMAL(15,4)),
            0.0
        )                                                           AS flat_fee_per_txn,
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.tiers[0].threshold') AS DECIMAL(15,2)),
            0.0
        )                                                           AS first_tier_threshold,
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.tiers[0].rate') AS DECIMAL(10,6)),
            0.0
        )                                                           AS first_tier_rate,
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.tiers[1].threshold') AS DECIMAL(15,2)),
            999999999.99
        )                                                           AS second_tier_threshold,
        COALESCE(
            CAST(JSON_EXTRACT(fs.fee_structure, '$.tiers[1].rate') AS DECIMAL(10,6)),
            0.0
        )                                                           AS second_tier_rate,
        fs.fee_type,
        -- Compute effective fee for primary network volume
        CASE
            WHEN fs.fee_type = 'PERCENTAGE' THEN
                nc.primary_total_amount * COALESCE(
                    CAST(JSON_EXTRACT(fs.fee_structure, '$.percentage_rate') AS DECIMAL(10,6)), 0
                )
            WHEN fs.fee_type = 'FLAT' THEN
                nc.primary_txn_count * COALESCE(
                    CAST(JSON_EXTRACT(fs.fee_structure, '$.flat_fee') AS DECIMAL(15,4)), 0
                )
            WHEN fs.fee_type = 'TIERED' THEN
                -- Tiered: first N txns at rate1, remainder at rate2
                LEAST(nc.primary_total_amount, first_tier_threshold) * first_tier_rate
                + GREATEST(nc.primary_total_amount - first_tier_threshold, 0) * second_tier_rate
            WHEN fs.fee_type = 'HYBRID' THEN
                (nc.primary_total_amount * base_percentage_rate)
                + (nc.primary_txn_count * flat_fee_per_txn)
            ELSE 0
        END                                                         AS primary_effective_fee,
        nc.primary_total_amount                                     AS gross_amount,
        fx.mid_rate                                                 AS fx_rate,
        -- FX-adjusted amounts in settlement currency (USD)
        CASE
            WHEN nc.txn_currency != 'USD' AND fx.mid_rate IS NOT NULL
            THEN nc.primary_total_amount * fx.mid_rate
            ELSE nc.primary_total_amount
        END                                                         AS usd_equivalent_amount
    FROM network_comparison nc
    INNER JOIN gps_fee_schedules fs
        ON fs.applicable_entity_type = 'MERCHANT'
       AND fs.applicable_entity_id = nc.merchant_id
       AND fs.card_network = nc.primary_network
       AND fs.effective_from <= CURRENT_DATE
       AND (fs.effective_to IS NULL OR fs.effective_to >= CURRENT_DATE)
    LEFT JOIN latest_fx_rates fx
        ON fx.from_currency = nc.txn_currency
       AND fx.to_currency = 'USD'
       AND fx.rate_recency = 1
),

-- ── Step 5: Rolling window analysis of merchant fee trends ─────────────
fee_trends AS (
    SELECT
        fa.merchant_id,
        fa.primary_network,
        fa.txn_currency,
        fa.usd_equivalent_amount,
        fa.primary_effective_fee,
        fa.gross_amount,
        fa.fee_type,
        -- Rolling 7-day average of effective fee rate (simulated via ROWS window)
        AVG(
            CASE WHEN fa.gross_amount > 0
                 THEN (fa.primary_effective_fee / fa.gross_amount) * 100
                 ELSE 0
            END
        ) OVER (
            PARTITION BY fa.merchant_id, fa.primary_network
            ORDER BY fa.first_txn_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        )                                                           AS rolling_7d_avg_fee_rate_pct,
        -- Cumulative fee total per merchant-network
        SUM(fa.primary_effective_fee) OVER (
            PARTITION BY fa.merchant_id, fa.primary_network
            ORDER BY fa.first_txn_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                           AS cumulative_fee_total,
        -- Fee-to-volume ratio Z-score style comparison vs peer merchants
        (fa.primary_effective_fee / NULLIF(fa.gross_amount, 0)) * 100
        - AVG(
            (fa.primary_effective_fee / NULLIF(fa.gross_amount, 0)) * 100
        ) OVER (
            PARTITION BY fa.primary_network, fa.txn_currency
        )                                                           AS fee_rate_deviation_from_mean,
        -- Window: previous period comparison
        LAG(fa.primary_effective_fee, 1, 0) OVER (
            PARTITION BY fa.merchant_id, fa.primary_network
            ORDER BY fa.first_txn_date
        )                                                           AS prev_period_fee,
        LEAD(fa.primary_effective_fee, 1, 0) OVER (
            PARTITION BY fa.merchant_id, fa.primary_network
            ORDER BY fa.first_txn_date
        )                                                           AS next_period_fee
    FROM fee_analysis fa
)

-- ── Final: Identify routing optimization opportunities ────────────────
SELECT
    ft.merchant_id,
    ft.primary_network,
    ft.txn_currency,
    ft.usd_equivalent_amount,
    ft.primary_effective_fee,
    ft.gross_amount,
    ft.fee_type,
    ROUND(ft.rolling_7d_avg_fee_rate_pct, 4)                       AS avg_fee_rate_7d_pct,
    ROUND(ft.fee_rate_deviation_from_mean, 4)                       AS fee_rate_vs_peers_pct,
    ROUND(ft.cumulative_fee_total, 2)                               AS ytd_cumulative_fee,
    -- Identify if this merchant is paying above network average
    CASE
        WHEN ft.fee_rate_deviation_from_mean > 0.5 THEN 'ABOVE_AVERAGE'
        WHEN ft.fee_rate_deviation_from_mean < -0.5 THEN 'BELOW_AVERAGE'
        ELSE 'AT_AVERAGE'
    END                                                             AS fee_positioning,
    -- Recommend network switching if alternative is cheaper
    CASE
        WHEN ft.fee_rate_deviation_from_mean > 1.0
             AND ft.usd_equivalent_amount > 50000
        THEN 'RECOMMEND_REROUTE'
        WHEN ft.fee_rate_deviation_from_mean > 0.5
        THEN 'MONITOR'
        ELSE 'OPTIMAL'
    END                                                             AS routing_recommendation,
    -- Savings estimate if rerouted to lowest-cost network
    ROUND(
        GREATEST(ft.fee_rate_deviation_from_mean, 0) / 100.0 * ft.gross_amount,
        2
    )                                                               AS estimated_savings,
    ft.prev_period_fee,
    ft.next_period_fee,
    ROUND(
        ((ft.primary_effective_fee - ft.prev_period_fee)
         / NULLIF(ft.prev_period_fee, 0)) * 100,
        2
    )                                                               AS fee_change_pct,
    CURRENT_TIMESTAMP                                               AS analyzed_at
FROM fee_trends ft
WHERE ft.usd_equivalent_amount > 1000  -- Filter noise
ORDER BY
    ft.fee_rate_deviation_from_mean DESC,
    ft.usd_equivalent_amount DESC
