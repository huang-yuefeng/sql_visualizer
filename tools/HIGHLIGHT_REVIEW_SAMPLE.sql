-- ============================================================
-- HIGHLIGHT SOLUTIONS REVIEW SAMPLE (2026-08-07)
-- definition lines in THIS file:
--   CTE src_x def L13        CTE mid def L18
--   ods_a read L15           ods_b read L25
--   implicit alias a (mid)  def L22   (FROM src_x a)
--   derived alias  b        def L26   () b)
--   implicit alias a (main) def L33   (FROM mid a)
--   qualified reads: a.id L20, b.val L21, a.id L27 (ON), a.dt L28,
--                    a.id L31, a.amt L32
-- ============================================================
INSERT OVERWRITE TABLE tgt_loan PARTITION(dt='$(load_date)')
WITH src_x AS (
    SELECT id, amt
    FROM ods_a
    WHERE dt = '$(load_date)'
)
,mid AS (
    SELECT
        a.id
        ,b.val
    FROM src_x a
    LEFT JOIN (
        SELECT id, val
        FROM ods_b
    ) b
    ON a.id = b.id
    WHERE a.dt = '$(load_date)'
)
SELECT
    a.id
    ,a.amt
FROM mid a
;
