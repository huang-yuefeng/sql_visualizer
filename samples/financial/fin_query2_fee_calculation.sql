-- ============================================================================
-- GPS Financial SQL #2: Multi-Currency Fee Calculation with Tiered Rates
-- Calculate fees per transaction using exchange rate lookups and tiered pricing
-- ============================================================================
SELECT
    t.txn_id,
    t.txn_type,
    t.amount,
    t.currency_code,
    t.settlement_currency,
    t.merchant_id,
    t.merchant_category,
    t.acquirer_id,
    t.risk_level,
    a.account_type,
    a.customer_type,
    a.kyc_status,

    COALESCE(er.rate, 1.0) AS applied_fx_rate,
    er.rate_type            AS fx_rate_type,
    er.spread_bps           AS fx_spread_bps,
    (t.amount * COALESCE(er.rate, 1.0)) AS settlement_amount_calc,

    fs.fee_schedule_id,
    fs.fee_name,
    fs.fee_type,
    fs.rate_percentage,
    fs.rate_fixed,
    fs.rate_min,
    fs.rate_max,
    fs.interchange_rate,
    fs.scheme_fee,
    fs.processing_fee,

    CASE
        WHEN fs.fee_type = 'PERCENTAGE' THEN
            GREATEST(
                COALESCE(fs.rate_min, 0),
                LEAST(
                    COALESCE(fs.rate_max, 999999),
                    t.amount * fs.rate_percentage / 100.0
                )
            )
        WHEN fs.fee_type = 'FLAT' THEN
            COALESCE(fs.rate_fixed, 0)
        WHEN fs.fee_type = 'TIERED' THEN
            COALESCE(
                JSON_EXTRACT(fs.tier_definition,
                    CONCAT('$[', CAST(FLOOR(t.amount / 1000) AS CHAR), '].rate')),
                fs.rate_fixed
            )
        ELSE 0
    END AS calculated_fee,

    CASE
        WHEN fs.fee_type = 'PERCENTAGE' THEN 'AD_VALOREM'
        WHEN fs.fee_type = 'FLAT'       THEN 'PER_ITEM'
        WHEN fs.fee_type = 'TIERED'     THEN 'TIER_BASED'
        ELSE 'UNKNOWN'
    END AS fee_calc_method,

    COALESCE(fs.interchange_rate, 0)    AS interchange_fee,
    COALESCE(fs.scheme_fee, 0)          AS scheme_fee_amount,
    COALESCE(fs.processing_fee, 0)      AS processing_fee_amount,

    (
        CASE
            WHEN fs.fee_type = 'PERCENTAGE' THEN
                GREATEST(
                    COALESCE(fs.rate_min, 0),
                    LEAST(
                        COALESCE(fs.rate_max, 999999),
                        t.amount * fs.rate_percentage / 100.0
                    )
                )
            WHEN fs.fee_type = 'FLAT' THEN
                COALESCE(fs.rate_fixed, 0)
            WHEN fs.fee_type = 'TIERED' THEN
                COALESCE(
                    JSON_EXTRACT(fs.tier_definition,
                        CONCAT('$[', CAST(FLOOR(t.amount / 1000) AS CHAR), '].rate')),
                    fs.rate_fixed
                )
            ELSE 0
        END
        + COALESCE(fs.interchange_rate, 0)
        + COALESCE(fs.scheme_fee, 0)
        + COALESCE(fs.processing_fee, 0)
    ) AS total_fee,

    rs.score_value   AS txn_risk_score,
    rs.score_level   AS txn_risk_level,
    rs.rules_triggered,
    rs.velocity_score,

    CASE
        WHEN t.risk_level = 'HIGH' AND rs.score_value > 80 THEN 'BLOCK'
        WHEN t.risk_level = 'HIGH' AND rs.score_value > 60 THEN 'MANUAL_REVIEW'
        WHEN t.risk_level = 'MEDIUM' AND rs.velocity_score > 50 THEN 'FLAG'
        ELSE 'CLEAR'
    END AS fee_risk_decision,

    t.created_at,
    t.settlement_date,
    t.settlement_batch_id

FROM gps_transactions t

INNER JOIN gps_accounts a
    ON t.source_account_id = a.account_id
   AND a.account_status = 'ACTIVE'

LEFT JOIN gps_exchange_rates er
    ON t.currency_code = er.base_currency
   AND t.settlement_currency = er.target_currency
   AND er.is_active = TRUE
   AND er.rate_type = 'SPOT'
   AND t.settlement_date = er.effective_date

LEFT JOIN gps_fee_schedules fs
    ON (fs.merchant_category = t.merchant_category OR fs.merchant_category IS NULL)
   AND (fs.txn_type = t.txn_type OR fs.txn_type IS NULL)
   AND (fs.currency_code = t.currency_code OR fs.currency_code IS NULL)
   AND (fs.region_code = a.region_code OR fs.region_code IS NULL)
   AND (fs.account_type = a.account_type OR fs.account_type IS NULL)
   AND fs.is_active = TRUE
   AND t.settlement_date BETWEEN fs.effective_from
                             AND COALESCE(fs.effective_to, '9999-12-31')

LEFT JOIN gps_risk_scores rs
    ON t.txn_id = rs.entity_id
   AND rs.entity_type = 'TRANSACTION'
   AND rs.model_version = (
       SELECT MAX(rs2.model_version)
       FROM gps_risk_scores rs2
       WHERE rs2.entity_id = t.txn_id
         AND rs2.entity_type = 'TRANSACTION'
   )

WHERE t.txn_status IN ('AUTHORIZED', 'SETTLED')
  AND t.txn_type IN ('PAYMENT', 'REFUND')
  AND t.settlement_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  AND t.amount > 0
  AND a.customer_type != 'GOVERNMENT'
  AND (
      t.merchant_id NOT IN (
          SELECT DISTINCT blocked_merchant_id
          FROM gps_risk_scores
          WHERE entity_type = 'MERCHANT'
            AND score_level = 'CRIT'
            AND is_overridden = FALSE
      )
      OR t.merchant_id IS NULL
  )
  AND NOT EXISTS (
      SELECT 1
      FROM gps_transactions parent
      WHERE parent.txn_id = t.parent_txn_id
        AND parent.txn_status = 'REVERSED'
  )
  AND fs.priority = COALESCE(
      (
          SELECT MIN(fs_inner.priority)
          FROM gps_fee_schedules fs_inner
          WHERE (fs_inner.merchant_category = t.merchant_category OR fs_inner.merchant_category IS NULL)
            AND fs_inner.is_active = TRUE
            AND t.settlement_date BETWEEN fs_inner.effective_from
                                      AND COALESCE(fs_inner.effective_to, '9999-12-31')
      ), 0
  )

ORDER BY t.settlement_date DESC, total_fee DESC;
