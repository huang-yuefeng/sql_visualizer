-- ============================================================================
-- GPS Financial SQL #12: Revenue Waterfall / MRR Analysis
-- ============================================================================
-- Inspired by SaaS MRR analysis (github.com/marusa07201/saas-revenue-retention-analysis)
-- — the industry-standard pattern for tracking recurring revenue changes.
-- Adapted for GPS merchant processing volumes.
--
-- Real-world patterns incorporated:
--   * Monthly Recurring Volume (MRV) as GPS analog to MRR
--   * New merchant volume, churned merchant volume
--   * Expansion (volume growth) and contraction (volume decline)
--   * Net retention rate (excludes new, includes expansion/contraction)
--   * Reactivation (back-from-churn) volume
--   * LAG/LEAD for month-over-month merchant state transitions
--   * DATE_TRUNC + INTERVAL arithmetic for calendar month navigation
-- ============================================================================

WITH
-- ── Step 1: Aggregate monthly processing volume per merchant ────────────
monthly_merchant_volume AS (
    SELECT
        t.merchant_id,
        t.acquirer_id,
        t.card_network,
        DATE_FORMAT(t.txn_date, '%Y-%m-01')                         AS volume_month,
        COUNT(DISTINCT t.txn_id)                                    AS txn_count,
        SUM(t.settlement_amount)                                    AS processing_volume,
        SUM(t.merchant_discount)                                    AS discount_total,
        SUM(t.interchange_fee)                                      AS interchange_total,
        SUM(t.network_fee)                                          AS network_fee_total,
        SUM(t.processing_fee)                                       AS processing_fee_total,
        -- Net revenue to GPS (all fees)
        SUM(COALESCE(t.merchant_discount, 0)
          + COALESCE(t.interchange_fee, 0)
          + COALESCE(t.network_fee, 0)
          + COALESCE(t.processing_fee, 0))                          AS net_revenue,
        COUNT(DISTINCT t.cardholder_account_id)                     AS unique_customers
    FROM gps_transactions t
    WHERE t.txn_type = 'PURCHASE'
      AND t.txn_status IN ('SETTLED')
      AND t.merchant_id IS NOT NULL
      AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 24 MONTH)
    GROUP BY t.merchant_id, t.acquirer_id, t.card_network, DATE_FORMAT(t.txn_date, '%Y-%m-01')
),

-- ── Step 2: Add previous/next month references per merchant ─────────────
merchant_month_states AS (
    SELECT
        mmv.*,
        -- Previous paid month (for churn/new detection)
        LAG(mmv.volume_month) OVER (
            PARTITION BY mmv.merchant_id, mmv.card_network
            ORDER BY mmv.volume_month
        )                                                           AS previous_volume_month,
        -- Next paid month (for churn detection)
        LEAD(mmv.volume_month) OVER (
            PARTITION BY mmv.merchant_id, mmv.card_network
            ORDER BY mmv.volume_month
        )                                                           AS next_volume_month,
        -- Previous month's volume (for expansion/contraction)
        LAG(mmv.processing_volume) OVER (
            PARTITION BY mmv.merchant_id, mmv.card_network
            ORDER BY mmv.volume_month
        )                                                           AS previous_volume,
        LAG(mmv.net_revenue) OVER (
            PARTITION BY mmv.merchant_id, mmv.card_network
            ORDER BY mmv.volume_month
        )                                                           AS previous_revenue,
        -- Calendar navigation helpers
        DATE_ADD(mmv.volume_month, INTERVAL 1 MONTH)                AS next_calendar_month,
        DATE_ADD(mmv.volume_month, INTERVAL -1 MONTH)               AS previous_calendar_month
    FROM monthly_merchant_volume mmv
),

-- ── Step 3: Classify each merchant-month and compute waterfall metrics ──
waterfall_metrics AS (
    SELECT
        mms.volume_month,
        mms.acquirer_id,
        mms.card_network,
        -- Customer counts
        COUNT(DISTINCT mms.merchant_id)                             AS active_merchants,
        -- MRV (Monthly Recurring Volume)
        SUM(mms.processing_volume)                                  AS mrv,
        SUM(mms.net_revenue)                                        AS mrr,
        -- New merchants (first month ever)
        SUM(CASE
            WHEN mms.previous_volume_month IS NULL
            THEN 1 ELSE 0
        END)                                                        AS new_merchants,
        SUM(CASE
            WHEN mms.previous_volume_month IS NULL
            THEN mms.net_revenue ELSE 0
        END)                                                        AS new_mrr,
        -- Churned merchants (no activity next month)
        SUM(CASE
            WHEN mms.next_volume_month IS NULL
               OR mms.next_volume_month != mms.next_calendar_month
            THEN 1 ELSE 0
        END)                                                        AS churned_merchants,
        SUM(CASE
            WHEN mms.next_volume_month IS NULL
               OR mms.next_volume_month != mms.next_calendar_month
            THEN mms.net_revenue ELSE 0
        END)                                                        AS churned_mrr,
        -- Expansion (same merchant, higher volume than last month)
        SUM(CASE
            WHEN mms.previous_volume_month = mms.previous_calendar_month
             AND mms.net_revenue > mms.previous_revenue
            THEN mms.net_revenue - mms.previous_revenue
            ELSE 0
        END)                                                        AS expansion_mrr,
        -- Contraction (same merchant, lower volume than last month)
        SUM(CASE
            WHEN mms.previous_volume_month = mms.previous_calendar_month
             AND mms.net_revenue < mms.previous_revenue
            THEN mms.net_revenue - mms.previous_revenue
            ELSE 0
        END)                                                        AS contraction_mrr,
        -- Reactivation (merchant was inactive, now back)
        SUM(CASE
            WHEN mms.previous_volume_month IS NOT NULL
             AND mms.previous_volume_month != mms.previous_calendar_month
            THEN mms.net_revenue ELSE 0
        END)                                                        AS reactivation_mrr,
        -- Resurrected merchants count
        SUM(CASE
            WHEN mms.previous_volume_month IS NOT NULL
             AND mms.previous_volume_month != mms.previous_calendar_month
            THEN 1 ELSE 0
        END)                                                        AS reactivated_merchants
    FROM merchant_month_states mms
    GROUP BY mms.volume_month, mms.acquirer_id, mms.card_network
)

-- ── Final: Revenue waterfall with net retention rate ──────────────────
SELECT
    wm.volume_month,
    wm.acquirer_id,
    wm.card_network,
    wm.active_merchants,
    wm.new_merchants,
    wm.churned_merchants,
    wm.reactivated_merchants,
    -- MRR components
    ROUND(wm.mrr, 2)                                                AS mrr,
    ROUND(wm.new_mrr, 2)                                            AS new_mrr,
    ROUND(wm.expansion_mrr, 2)                                      AS expansion_mrr,
    ROUND(wm.contraction_mrr, 2)                                    AS contraction_mrr,
    ROUND(wm.churned_mrr, 2)                                        AS churned_mrr,
    ROUND(wm.reactivation_mrr, 2)                                   AS reactivation_mrr,
    -- Net New MRR = New + Expansion + Contraction + Reactivation + Churned
    ROUND(
        wm.new_mrr + wm.expansion_mrr + wm.contraction_mrr
        + wm.reactivation_mrr + wm.churned_mrr,
        2
    )                                                               AS net_new_mrr,
    -- MRR Growth Rate
    ROUND(
        (wm.new_mrr + wm.expansion_mrr + wm.contraction_mrr
         + wm.reactivation_mrr + wm.churned_mrr)
        * 100.0 / NULLIF(
            wm.mrr
            - wm.new_mrr
            - wm.reactivation_mrr,
            0
        ),
        2
    )                                                               AS mrr_growth_rate_pct,
    -- Net Revenue Retention (excludes new, includes expansion + contraction + churn)
    ROUND(
        (wm.mrr - wm.new_mrr + wm.expansion_mrr + wm.contraction_mrr
         + wm.churned_mrr)
        * 100.0 / NULLIF(wm.mrr - wm.new_mrr, 0),
        2
    )                                                               AS net_revenue_retention_pct,
    -- Gross Revenue Retention (excludes new + expansion, includes contraction + churn)
    ROUND(
        (wm.mrr - wm.new_mrr - wm.expansion_mrr + wm.contraction_mrr
         + wm.churned_mrr)
        * 100.0 / NULLIF(wm.mrr - wm.new_mrr, 0),
        2
    )                                                               AS gross_revenue_retention_pct,
    -- Churn rate
    ROUND(
        wm.churned_merchants * 100.0 / NULLIF(wm.active_merchants, 0),
        2
    )                                                               AS logo_churn_rate_pct,
    ROUND(
        ABS(wm.churned_mrr) * 100.0 / NULLIF(wm.mrr, 0),
        2
    )                                                               AS revenue_churn_rate_pct,
    -- MoM growth
    ROUND(
        (wm.mrr - LAG(wm.mrr) OVER (
            PARTITION BY wm.acquirer_id, wm.card_network
            ORDER BY wm.volume_month
        )) * 100.0 / NULLIF(LAG(wm.mrr) OVER (
            PARTITION BY wm.acquirer_id, wm.card_network
            ORDER BY wm.volume_month
        ), 0),
        2
    )                                                               AS mom_growth_pct,
    -- YoY growth
    ROUND(
        (wm.mrr - LAG(wm.mrr, 12) OVER (
            PARTITION BY wm.acquirer_id, wm.card_network
            ORDER BY wm.volume_month
        )) * 100.0 / NULLIF(LAG(wm.mrr, 12) OVER (
            PARTITION BY wm.acquirer_id, wm.card_network
            ORDER BY wm.volume_month
        ), 0),
        2
    )                                                               AS yoy_growth_pct
FROM waterfall_metrics wm
ORDER BY
    wm.volume_month DESC,
    wm.acquirer_id,
    wm.card_network
