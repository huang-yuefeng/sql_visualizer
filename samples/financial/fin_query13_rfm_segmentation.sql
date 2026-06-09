-- ============================================================================
-- GPS Financial SQL #13: RFM Segmentation for Merchant Portfolio
-- ============================================================================
-- Inspired by RFM analysis patterns (github.com/hamzaugursumer/RFM-Analysis-With-SQL,
-- github.com/ChristopherShelton/sql-ecommerce-analysis) — the industry-standard
-- Recency-Frequency-Monetary customer segmentation framework.
-- Adapted for GPS merchants (payer = merchant, value = settlement volume).
--
-- Real-world patterns incorporated:
--   * NTILE(5) for R, F, M quintile scoring
--   * DATEDIFF for recency calculation
--   * Combined RFM score (concatenated quintiles)
--   * Segmentation labels: Champions, Loyal, At Risk, Hibernating, Lost
--   * Per-segment aggregate statistics
--   * Rank/percentile within segment
-- ============================================================================

WITH
-- ── Step 1: Compute raw RFM metrics per merchant ────────────────────────
merchant_rfm_raw AS (
    SELECT
        t.merchant_id,
        t.acquirer_id,
        t.card_network,
        -- Recency: days since last transaction
        DATEDIFF(CURRENT_DATE, MAX(t.txn_date))                    AS recency_days,
        -- Frequency: number of transactions in analysis period
        COUNT(DISTINCT t.txn_id)                                    AS frequency,
        -- Monetary: total settlement volume
        SUM(t.settlement_amount)                                    AS monetary_volume,
        -- Additional metrics for richer segmentation
        AVG(t.settlement_amount)                                    AS avg_txn_amount,
        COUNT(DISTINCT DATE_FORMAT(t.txn_date, '%Y-%m-01'))         AS active_months,
        COUNT(DISTINCT t.cardholder_account_id)                     AS unique_customers,
        SUM(COALESCE(t.merchant_discount, 0)
          + COALESCE(t.interchange_fee, 0)
          + COALESCE(t.network_fee, 0)
          + COALESCE(t.processing_fee, 0))                          AS total_fees_paid,
        MAX(t.txn_date)                                             AS last_txn_date,
        MIN(t.txn_date)                                             AS first_txn_date,
        -- Chargeback indicator
        SUM(CASE WHEN t.txn_type = 'CHARGEBACK' THEN 1 ELSE 0 END) AS chargeback_count
    FROM gps_transactions t
    WHERE t.txn_type IN ('PURCHASE', 'REFUND', 'CHARGEBACK')
      AND t.txn_status IN ('SETTLED', 'AUTHORIZED')
      AND t.merchant_id IS NOT NULL
      AND t.txn_date >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
    GROUP BY t.merchant_id, t.acquirer_id, t.card_network
),

-- ── Step 2: Compute RFM scores (1-5 quintiles, 5 = best) ─────────────
rfm_scored AS (
    SELECT
        r.*,
        -- Recency score: lower recency = better (5 = most recent)
        NTILE(5) OVER (ORDER BY r.recency_days ASC)                 AS r_score,
        -- Frequency score: higher frequency = better (5 = most frequent)
        NTILE(5) OVER (ORDER BY r.frequency DESC)                   AS f_score,
        -- Monetary score: higher volume = better (5 = highest value)
        NTILE(5) OVER (ORDER BY r.monetary_volume DESC)             AS m_score
    FROM merchant_rfm_raw r
    WHERE r.frequency > 0  -- Exclude merchants with zero transactions
),

-- ── Step 3: Build combined RFM score and segment labels ───────────────
rfm_segmented AS (
    SELECT
        rs.*,
        -- Combined RFM score (e.g., "555" = best, "111" = worst)
        CONCAT(rs.r_score, rs.f_score, rs.m_score)                  AS rfm_score,
        -- Simple RFM total
        (rs.r_score + rs.f_score + rs.m_score)                      AS rfm_total,
        -- Weighted RFM (customizable weights)
        ROUND(
            rs.r_score * 0.30 + rs.f_score * 0.30 + rs.m_score * 0.40,
            1
        )                                                           AS rfm_weighted,
        -- Segment classification based on combined score
        CASE
            -- Champions: high R, high F, high M (total >= 13)
            WHEN (rs.r_score + rs.f_score + rs.m_score) >= 13
                THEN 'CHAMPIONS'
            -- Loyal: good R, good F, decent M
            WHEN rs.r_score >= 4 AND rs.f_score >= 4
                THEN 'LOYAL'
            -- Potential Loyalists: recent but lower frequency
            WHEN rs.r_score >= 4 AND rs.f_score >= 3
                THEN 'POTENTIAL_LOYALIST'
            -- At Risk: good history but going cold (high F+M, low R)
            WHEN rs.f_score >= 4 AND rs.m_score >= 4 AND rs.r_score <= 2
                THEN 'AT_RISK'
            -- Cannot Lose: high value but declining
            WHEN rs.m_score >= 5 AND rs.r_score <= 3
                THEN 'CANNOT_LOSE'
            -- Hibernating: low recency, low frequency, low monetary
            WHEN rs.r_score <= 2 AND rs.f_score <= 2
                THEN 'HIBERNATING'
            -- Lost: lowest scores
            WHEN (rs.r_score + rs.f_score + rs.m_score) <= 4
                THEN 'LOST'
            -- New: recently acquired (first txn < 90 days)
            WHEN DATEDIFF(CURRENT_DATE, rs.first_txn_date) <= 90
                THEN 'NEW'
            -- About to Sleep: medium recency, low frequency
            WHEN rs.r_score <= 3 AND rs.f_score <= 2 AND rs.m_score <= 3
                THEN 'ABOUT_TO_SLEEP'
            -- Need Attention: medium across the board
            ELSE 'NEED_ATTENTION'
        END                                                         AS rfm_segment,
        -- Churn risk indicator
        CASE
            WHEN rs.recency_days > 180 THEN 'HIGH'
            WHEN rs.recency_days > 90  THEN 'MEDIUM'
            WHEN rs.recency_days > 60  THEN 'LOW'
            ELSE 'SAFE'
        END                                                         AS churn_risk,
        -- Revenue concentration flag
        CASE
            WHEN rs.m_score = 5 THEN 'TOP_20PCT'
            WHEN rs.m_score >= 4 THEN 'TOP_40PCT'
            ELSE 'BOTTOM_60PCT'
        END                                                         AS revenue_tier
    FROM rfm_scored rs
)

-- ── Final: Segment-level summary statistics + individual merchant view ─
SELECT
    rs.merchant_id,
    rs.acquirer_id,
    rs.card_network,
    rs.rfm_segment,
    rs.rfm_score,
    rs.rfm_total,
    rs.rfm_weighted,
    rs.r_score,
    rs.f_score,
    rs.m_score,
    rs.churn_risk,
    rs.revenue_tier,
    rs.recency_days,
    rs.frequency,
    rs.monetary_volume,
    rs.avg_txn_amount,
    rs.active_months,
    rs.unique_customers,
    rs.total_fees_paid,
    ROUND(rs.total_fees_paid / NULLIF(rs.monetary_volume, 0) * 100, 2) AS fee_rate_pct,
    rs.chargeback_count,
    rs.last_txn_date,
    rs.first_txn_date,
    -- Segment rank within RFM segment by monetary value
    RANK() OVER (
        PARTITION BY rs.rfm_segment
        ORDER BY rs.monetary_volume DESC
    )                                                               AS segment_rank,
    -- Percentile within segment
    ROUND(
        PERCENT_RANK() OVER (
            PARTITION BY rs.rfm_segment
            ORDER BY rs.monetary_volume
        ) * 100,
        1
    )                                                               AS segment_percentile,
    -- Running total of volume within segment
    SUM(rs.monetary_volume) OVER (
        PARTITION BY rs.rfm_segment
        ORDER BY rs.monetary_volume DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                               AS segment_cumulative_volume,
    CURRENT_TIMESTAMP                                               AS scored_at
FROM rfm_segmented rs
ORDER BY
    rs.rfm_total DESC,
    rs.monetary_volume DESC
