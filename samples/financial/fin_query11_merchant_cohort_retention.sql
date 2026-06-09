-- ============================================================================
-- GPS Financial SQL #11: Merchant Cohort Retention Analysis
-- ============================================================================
-- Inspired by TheLook Ecommerce cohort analysis (github.com/awan92/TheLook-Ecommerce-Analysis)
-- and the classic SaaS cohort retention pattern used across the industry.
--
-- Real-world patterns incorporated:
--   * Monthly cohorts based on first settlement date (cohort_items CTE)
--   * month_number tracking (0 = cohort month, 1 = month after, ...)
--   * Cohort size + retention count + retention percentage
--   * Segmentation by merchant category (MCC) and acquirer
--   * DATE_DIFF for month offset calculation
--   * DATE_TRUNC for month normalization
-- ============================================================================

WITH
-- ── Step 1: Find each merchant's cohort month (first settlement) ──────────
merchant_cohorts AS (
    SELECT
        t.merchant_id,
        t.acquirer_id,
        t.mcc                                                     AS merchant_category,
        MIN(DATE_FORMAT(t.txn_date, '%Y-%m-01'))                  AS cohort_month
    FROM gps_transactions t
    WHERE t.txn_type = 'PURCHASE'
      AND t.txn_status IN ('SETTLED', 'AUTHORIZED')
      AND t.merchant_id IS NOT NULL
      AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 18 MONTH)
    GROUP BY t.merchant_id, t.acquirer_id, t.mcc
),

-- ── Step 2: Get all merchant activity months ────────────────────────────
merchant_activity AS (
    SELECT
        t.merchant_id,
        DATE_FORMAT(t.txn_date, '%Y-%m-01')                        AS activity_month,
        COUNT(DISTINCT t.txn_id)                                   AS txn_count,
        SUM(t.settlement_amount)                                   AS settlement_volume,
        COUNT(DISTINCT t.cardholder_account_id)                    AS unique_customers
    FROM gps_transactions t
    WHERE t.txn_type = 'PURCHASE'
      AND t.txn_status IN ('SETTLED', 'AUTHORIZED')
      AND t.merchant_id IS NOT NULL
      AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 18 MONTH)
    GROUP BY t.merchant_id, DATE_FORMAT(t.txn_date, '%Y-%m-01')
),

-- ── Step 3: Join activity to cohort, compute month_number ──────────────
cohort_activity AS (
    SELECT
        mc.merchant_id,
        mc.acquirer_id,
        mc.merchant_category,
        mc.cohort_month,
        ma.activity_month,
        ma.txn_count,
        ma.settlement_volume,
        ma.unique_customers,
        -- Month offset: 0 = cohort month, 1 = first month after, etc.
        PERIOD_DIFF(
            EXTRACT(YEAR_MONTH FROM ma.activity_month),
            EXTRACT(YEAR_MONTH FROM mc.cohort_month)
        )                                                           AS month_number
    FROM merchant_cohorts mc
    INNER JOIN merchant_activity ma
        ON mc.merchant_id = ma.merchant_id
       AND ma.activity_month >= mc.cohort_month
),

-- ── Step 4: Compute cohort size (merchants active in cohort month) ─────
cohort_size AS (
    SELECT
        cohort_month,
        acquirer_id,
        merchant_category,
        COUNT(DISTINCT merchant_id)                                 AS total_merchants,
        SUM(txn_count)                                              AS cohort_txn_count,
        SUM(settlement_volume)                                      AS cohort_volume
    FROM cohort_activity
    WHERE month_number = 0
    GROUP BY cohort_month, acquirer_id, merchant_category
),

-- ── Step 5: Retention table (merchants still active at each month_number) ──
retention_data AS (
    SELECT
        ca.cohort_month,
        ca.acquirer_id,
        ca.merchant_category,
        ca.month_number,
        COUNT(DISTINCT ca.merchant_id)                              AS active_merchants,
        SUM(ca.txn_count)                                           AS retained_txn_count,
        SUM(ca.settlement_volume)                                   AS retained_volume,
        AVG(ca.unique_customers)                                    AS avg_customers_per_merchant
    FROM cohort_activity ca
    GROUP BY ca.cohort_month, ca.acquirer_id, ca.merchant_category, ca.month_number
)

-- ── Final: Retention rate + volume retention ───────────────────────────
SELECT
    rd.cohort_month,
    rd.acquirer_id,
    rd.merchant_category,
    rd.month_number,
    cs.total_merchants                                             AS cohort_size,
    rd.active_merchants,
    ROUND(
        (rd.active_merchants * 100.0) / NULLIF(cs.total_merchants, 0),
        2
    )                                                               AS retention_rate_pct,
    cs.cohort_volume                                                AS cohort_total_volume,
    rd.retained_volume,
    ROUND(
        (rd.retained_volume * 100.0) / NULLIF(cs.cohort_volume, 0),
        2
    )                                                               AS volume_retention_pct,
    -- Volume per active merchant (health indicator)
    ROUND(
        rd.retained_volume / NULLIF(rd.active_merchants, 0),
        2
    )                                                               AS volume_per_merchant,
    rd.avg_customers_per_merchant,
    -- Growth/decline vs previous month
    ROUND(
        (rd.retained_volume - LAG(rd.retained_volume) OVER (
            PARTITION BY rd.cohort_month, rd.acquirer_id, rd.merchant_category
            ORDER BY rd.month_number
        )) / NULLIF(LAG(rd.retained_volume) OVER (
            PARTITION BY rd.cohort_month, rd.acquirer_id, rd.merchant_category
            ORDER BY rd.month_number
        ), 0) * 100,
        2
    )                                                               AS volume_change_pct,
    -- Cohort quality label
    CASE
        WHEN rd.month_number = 0 THEN 'BASELINE'
        WHEN rd.active_merchants * 100.0 / NULLIF(cs.total_merchants, 0) >= 80
            THEN 'EXCELLENT'
        WHEN rd.active_merchants * 100.0 / NULLIF(cs.total_merchants, 0) >= 60
            THEN 'GOOD'
        WHEN rd.active_merchants * 100.0 / NULLIF(cs.total_merchants, 0) >= 40
            THEN 'CONCERNING'
        ELSE 'CRITICAL'
    END                                                             AS retention_quality
FROM retention_data rd
INNER JOIN cohort_size cs
    ON rd.cohort_month = cs.cohort_month
   AND rd.acquirer_id = cs.acquirer_id
   AND rd.merchant_category = cs.merchant_category
WHERE rd.month_number BETWEEN 0 AND 12
ORDER BY
    rd.cohort_month DESC,
    rd.acquirer_id,
    rd.merchant_category,
    rd.month_number
