-- MaxCompute/ODPS: INSERT OVERWRITE with PARTITION
set odps.sql.decimal.odps2=true;
INSERT OVERWRITE TABLE dwd_fact_orders PARTITION (dt)
SELECT
    o.order_id,
    o.customer_id,
    DECODE(o.status, 'PAID', 1, 'PENDING', 0, -1) AS status_code,
    NVL(o.discount, 0) AS discount,
    TO_DATE(o.order_time) AS order_date,
    DATEADD(o.ship_date, 3, 'day') AS expected_delivery,
    DATETRUNC(o.order_time, 'DD') AS order_day,
    o.dt
FROM ods_orders o
WHERE o.dt = '${load_date}'
  AND o.is_deleted = 0;
