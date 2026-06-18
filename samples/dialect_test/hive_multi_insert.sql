-- Apache Hive: multi-table insert from single source
FROM page_view_stg pvs
INSERT OVERWRITE TABLE page_view PARTITION(dt='2008-06-08', country)
    SELECT pvs.viewTime, pvs.userid, pvs.page_url, pvs.referrer_url, null, null, pvs.ip, pvs.cnt
INSERT OVERWRITE TABLE page_view_summary PARTITION(dt='2008-06-08')
    SELECT pvs.userid, COUNT(*) AS page_views, pvs.country
    GROUP BY pvs.userid, pvs.country;
