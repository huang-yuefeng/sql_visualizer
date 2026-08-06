--** 功能描述：[贷款借据信息附属表]数据处理
--** 目标表：[BDM_ACC_LOAN_INFO_SUP]
--** 源表名：ODS [ods_hub_lsacmsp] [ods_hub_ssclmtp] [ods_hie_ipblmsp] [ods_hie_ipdcmsp] [ods_hie_ippdcpp] [ods_hie_ipacmsp] BDM [bdm_acc_loan_info] [bdm_gdc_label_fin] [bdm_evt_loan_trans] GDC [ods_cdp_gdc_acct_migrate_to_diff_branches]
--** 创建时间：2025-11-11
--** 文件名：BDM_ACC_LOAN_INFO_SUP_M
SET odps.sql.decimal.odps2 = true;

--20260206 HBCNRDQE-5243 HBCNRDQE-5244 启用备用字段reserved_field8存放rollover业务标识
WITH rollover_loan_info AS (
    -- 对当月到期日期发生改变但未发生还款交易的rollover业务打标
    -- 查询当月到期日期发生过改变的贷款借据编码，月末的最新贷款到期日期
    SELECT
        lending_ref
        ,loan_maturity_dt
    FROM
        bdm_acc_loan_info
    WHERE
        data_dt = '$(load_date)'
        AND lending_ref IN (
            -- 查询当月到期日期发生过改变的贷款借据编码
            SELECT
                lending_ref
            FROM (
                -- 查询一整月贷款余额不为0，pogmab等于"HSBC"，poapty等于'REV','RLN','OL8'中的一个，数据的贷款借据编码、最新到期日期
                SELECT
                    DISTINCT lending_ref
                    ,loan_maturity_dt
                FROM
                    bdm_acc_loan_info p1
                    LEFT JOIN (
                        SELECT podcg, poctcd, pogmab, poacb, poacs, poacx, podtao, poapty, poofla, pofddt, pocnlm, poclin
                        FROM
                            ods_hub_lsacmsp
                        WHERE
                            p_dt = '$(load_date)'
                            AND podcg = 'HSBC'
                            AND podtao <> pofddt
                            AND NVL(poofla,0) <> 0
                            AND NVL(poapty,'') <> '01'
                    ) p2
                    ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref
                WHERE
                    SUBSTR(p1.data_dt,1,7) = SUBSTR('$(load_date)',1,7)
                    AND p1.charge_department = 'OPS_CDT'
                    AND p1.loan_bal > 0
                    AND p2.pogmab = 'HSBC'
                    AND p2.poapty IN ('REV','RLN','OL8')
                    AND p1.lending_ref NOT IN (
                        SELECT
                            DISTINCT lending_ref
                        FROM
                            bdm_evt_loan_trans a
                        WHERE
                            SUBSTR(a.trans_dt, 1, 7) = SUBSTR('$(load_date)', 1, 7)
                            AND SUBSTR(a.data_dt, 1, 7) = SUBSTR('$(load_date)', 1, 7)
                            AND a.charge_department = 'OPS_CDT'
                            AND a.Reserved_Field10 = 'Rollover2'
                    )
                GROUP BY lending_ref
                HAVING COUNT(1) > 1
            )
        )
)
,loan_final AS (
    SELECT
        NULL AS internal_key -- 账户主键暂不需要，有需要的自己加工
        ,p1.lending_ref -- 借据编号
        ,p1.contract_no -- 合同号
        ,p1.acct_no -- 信贷分户账账号
        ,p2.poapty AS product_code -- 源系统产品类别
        ,NULL AS interest_type -- 源系统利率类型 暂不需要，有需要的自己加工
        ,CASE WHEN branch.target_branch_internal_code IS NOT NULL THEN branch.target_branch_internal_code ELSE p1.branch_code END AS branch_code_sk -- 内部核算机构号
        ,p3.zfds20 AS desc_length20 -- zfds20
        ,p5.igctcd||p5.igdcgl||LPAD(p5.igdcb,3,'0')||LPAD(p5.igdcs,6,'0')||'N'||p4.iicnl1||p4.iicl11 AS limit_contract_no -- limit合同号
        ,CASE WHEN accu.vlookup_key_value IS NOT NULL THEN 'Y' ELSE 'N' END AS abnormal_issue_flag -- 异常发放标识-统计累放用，通过GDC补录
        ,p1.tag_primary_accountable_party -- 业务职能部门
        ,p1.tag_responsible_party -- 报送部门
        ,p1.sys_src_code -- 源系统代码
        ,p1.charge_department
        ,p1.issue_dt -- 贷款发放日期
        ,p1.loan_ori_maturity_dt -- 贷款到期日期
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8 -- rollover业务标识（修改到期日期）
    FROM
        bdm_acc_loan_info p1
        LEFT JOIN (
            SELECT
                DISTINCT vlookup_key_value
            FROM
                bdm_gdc_label_fin
            WHERE
                bdm_table = 'BDM_ACC_LOAN_INFO_SUP'
                AND field = 'abnormal_issue_flag' -- 只取此类标签
                AND data_dt = (SELECT MAX(t.data_dt) FROM bdm_gdc_label_fin t WHERE t.data_dt <= '$(load_date)' AND t.bdm_table = 'BDM_ACC_LOAN_INFO_SUP' AND t.field = 'abnormal_issue_flag')
        ) accu
        ON p1.lending_ref = accu.vlookup_key_value
        LEFT JOIN (
            SELECT
                account_no
                ,target_branch_internal_code
            FROM
                ods_cdp_gdc_acct_migrate_to_diff_branches
            WHERE
                p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('$(load_date)',1,7))
        ) branch
        ON branch.account_no = p1.acct_no
        LEFT JOIN (
            SELECT podcg, poctcd, pogmab, poacb, poacs, poacx, podtao, poapty, poofla, pofddt, pocnlm, poclin
            FROM
                ods_hub_lsacmsp
            WHERE
                p_dt = '$(load_date)'
                AND podcg = 'HSBC'
                AND podtao <> pofddt
                AND NVL(poofla,0) <> 0
                AND NVL(poapty,'') <> '01'
        ) p2
        ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref
        LEFT JOIN ods_hub_ssclmtp p3
        ON
            p3.zfctcd = p2.poctcd
            AND p3.zfdcg = p2.podcg
            AND p3.zfdcb = p2.podcb
            AND p3.zfdcs = p2.podcs
            AND p3.zflmty = p2.pocnlm
            AND p3.zfline = p2.poclin
            AND p3.zflgi = 'N'
            AND p3.p_dt = '$(load_date)'
        LEFT JOIN (
            SELECT
                a.*
            FROM
                ods_hie_ipblmsp a
                LEFT JOIN ods_hie_ipdcmsp b
                ON
                    a.iidcptl||a.iibrabl||a.iidcno = b.ihdcptl||b.ihbrab||b.ihdcno
                    AND b.p_dt = '$(load_date)'
                LEFT JOIN ods_hie_ippdcpp c
                ON
                    b.ihctcd||b.ihgmab = c.ibctcd||c.ibgmab
                    AND b.ihdcpt = c.ibapty
                    AND c.p_dt = '$(load_date)'
            WHERE
                a.p_dt = '$(load_date)'
                AND a.iiinsd <> 0
                AND a.iiblao <> 0
                AND a.iippao <> 0
                AND c.ibsbdc <> 0
                AND c.ibdbs = 'Y'
        ) p4
        ON RPAD(p4.iiapty,3,'')||p4.iiblno = p1.lending_ref
        LEFT JOIN ods_hie_ipacmsp p5
        ON
            p5.iiapty = p4.iiapty
            AND p5.p_dt = p4.p_dt
        LEFT JOIN rollover_loan_info p6
        ON p6.lending_ref = p1.lending_ref
    WHERE
        p1.data_dt = '$(load_date)'
)
INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)
SELECT
    p1.internal_key -- 账户主键
    ,p1.lending_ref -- 借据编号
    ,p1.contract_no -- 合同号
    ,p1.acct_no -- 信贷分户账账号
    ,p1.product_code -- 源系统产品类别
    ,p1.interest_type -- 源系统利率类型
    ,p1.branch_code_sk -- 内部核算机构号
    ,p1.desc_length20 -- zfds20
    ,p1.limit_contract_no -- limit合同号
    ,p1.abnormal_issue_flag -- 异常发放标识
    ,p1.tag_primary_accountable_party -- 业务职能部门
    ,p1.tag_responsible_party -- 报送部门
    ,p1.sys_src_code -- 源系统代码
    ,getdate() AS rec_creat_dt_tm -- 数据更新时间
    ,NULL AS reserved_field1
    ,NULL AS reserved_field2
    ,NULL AS reserved_field3
    ,NULL AS reserved_field4
    ,NULL AS reserved_field5
    ,CASE WHEN p1.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ' THEN CASE WHEN NVL(p2.reserved_field6,'') <> '' AND p2.reserved_field6 <> p1.issue_dt THEN p2.reserved_field6 ELSE p1.issue_dt END END AS reserved_field6 -- 贷款发放日期
    ,CASE WHEN p1.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ' THEN CASE WHEN NVL(p3.loan_ori_maturity_dt,'') <> '' AND p3.loan_ori_maturity_dt <> p2.reserved_field7 THEN p3.loan_ori_maturity_dt WHEN NVL(p2.reserved_field7,'') <> '' AND p2.reserved_field7 <> p1.loan_ori_maturity_dt THEN p2.reserved_field7 ELSE p1.loan_ori_maturity_dt END END AS reserved_field7 -- 贷款到期日期
    ,p1.reserved_field8 AS reserved_field8 -- rollover业务标识（修改到期日期）
    ,NULL AS reserved_field9
    ,NULL AS reserved_field10
    ,NULL AS reserved_field11
    ,NULL AS reserved_field12
    ,NULL AS reserved_field13
    ,NULL AS reserved_field14
    ,NULL AS reserved_field15
    ,NULL AS reserved_field16
    ,NULL AS reserved_field17
    ,NULL AS reserved_field18
    ,NULL AS reserved_field19
    ,NULL AS reserved_field20
    ,p1.charge_department
FROM
    loan_final p1
    LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表
    ON
        p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等
        AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD') -- 取前一天的数据
        AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'
    LEFT JOIN bdm_sys_acc_loan_info p3 -- 贷款借据静态表
    ON
        p3.lending_ref = p1.lending_ref -- p1表和p3表贷款借据编码相等
WHERE
    1 = 1;

-- 操作日志记录
INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)
SELECT
    '$(load_date)' AS data_dt
    ,'BDM' AS object_domain
    ,'' AS sub_src_system
    ,'BDM_ACC_LOAN_INFO_SUP' AS table_name
    ,'BDM_ACC_LOAN_INFO_SUP' AS job_name
    ,COUNT(1) AS total_rows
    ,getdate() AS load_time
    ,'Y' AS STATUS
    ,NULL AS remarks
FROM
    bdm_acc_loan_info_sup
WHERE
    data_dt = '$(load_date)';
