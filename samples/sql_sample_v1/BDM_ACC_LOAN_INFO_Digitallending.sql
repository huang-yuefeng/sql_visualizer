--
-- 所属主题：账户主题
-- 功能描述：[贷款借据信息表]数据处理
-- 目标表：[BDM_ACC_LOAN_INFO]【贷款借据信息表】
-- 源表名：
-- ODS:
-- [ods_ccb_cb_loan_acctloan]
-- [ODS_HUB_SSALSFP]
-- [ods_ccb_ap_app_main_info]
-- [ods_ccb_cb_loan_acct]
-- [ods_ccb_ln_app_inf]
-- [ods_ccb_cb_loan_acctloandisb]
-- [ods_ccb_cb_loan_acctloanpmt]
-- [ODS_CUPD_CLD_ACCTMASTER_NEW]
-- [ods_ccb_ln_loan_inf]
-- [ODS_CCB_LN_ORDER_INF]
-- [ods_ccb_cb_loan_acctbal]
-- [ods_ccb_cb_loan_acctloantermhist]
-- [ods_ccb_ln_app_inf_basic]
-- [ods_ccb_ln_account_inf]
-- [BDM_CUS_ICUSTOMER]--20240407
-- [BDM_ACC_DEPOSIT_ACCT]--20240507
--
-- BDM:
-- [bdm_cus_ccustomer]
-- [bdm_cus_jointcustomer]
-- [bdm_fin_lrr_key_base_info]
--
--
-- ** 创建者：minghua.qiu
-- ** 创建时间：20230524
-- 修改日志：
-- 日期 修改人 修改内容
-- yyyymmdd name comment
-- 20231219 mayao 修复重复数据问题：需要加上a.p_dt=$(load_date)
-- a.p_dt=$(load_date)
-- 20231225 mayao 应收利息根据BA给的BRD调整逻辑+调整获取合同号逻辑ods_ccb_cb_loan_acctloan.contractid->ods_ccb_ln_account_inf.contract_info
-- 20240115 mayao tag_primary_accountable_party字段WPB_RBB>>WPB_RBB_Loan
-- tag_responsible_party字段WPB_RBB>>WPB_RBB_Loan
-- 20240116 mayao 新增rec_creat_dt_tm,rec_updt_dt_tm
-- 调整dis_status_alias逻辑
-- 20240228 mayao 修复字段取数逻辑问题：到期日、发放日、贷款入账账号、贷款入账户名、还款账号、还款账号所属行名称 --HBCNRDQE-710
-- 20240323 chenwei 新增科目逻辑
-- 20240407 luowei 还款账号所属行名称、入账账号所属行名称从ODS_CUPD_CLD_ACCTMASTER_NEW表取账户状态修改 HBCNRDQE-896贷款投向行业处理 HBCNRDQE-858
-- 20240507 luowei 新增备用字段，脱敏字段DM_FLAG1、DM_FLAG2
-- 20240516 luowei loan_maturity_dt, ISSUE_DT
-- 20240703 luowei Reserved_Field19增加取值
-- 20240904 luowei 科目逻辑调整HBCNRDQE-1504
-- 20250327 chenbinbin HBCNRDQE-3524：dis_bank_id添加兜底：空值为CNHSBC900Z
-- 20250604 chenbinbin 处理loan_purpose，loan_purpose_onoff_flag
-- 20250725 sunhao 去除loan_purpose字段，调整loan_purpose_indu字段逻辑modify150 HBCNRDQE-4040 HBCNRDQE-4157
-- 20250909 xiongchen 150个人贷款调整原始到期日逻辑
-- 备注：
-- 处理逻辑：
SET odps.sql.decimal.odps2 = true;

WITH
temp_kmbh_gl AS (
SELECT lending_ref
,MXKMBH
FROM (
SELECT p1.acnw AS lending_ref
,SSALSFP.ALCBAL || LPAD(SSALSFP.ALCBP1,5,0) AS MXKMBH
,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN
FROM ODS_CUPD_CLD_ACCTMASTER_NEW p1
LEFT JOIN ODS_HUB_SSALSFP SSALSFP
ON SSALSFP.ALCTCD = SUBSTR(p1.MXKMBH,1,2)
AND SSALSFP.ALGMAB = SUBSTR(p1.MXKMBH,3,4)
AND SSALSFP.ALACB = SUBSTR(p1.MXKMBH,7,3)
AND SSALSFP.ALACS = SUBSTR(p1.MXKMBH,10,6)
AND SSALSFP.ALACX = SUBSTR(p1.MXKMBH,16,3)
AND SSALSFP.ALSSCD = 'GL'
AND SSALSFP.P_DT <= '$(load_date)'
WHERE P1.P_DT = '$(load_date)'
) t
WHERE t.rn = 1
),
temp_kmbh_ie AS (
SELECT lending_ref
,MXKMBH
FROM (
SELECT p1.acnw AS lending_ref
,SSALSFP.ALCBAL || LPAD(SSALSFP.ALCBP1,5,0) AS MXKMBH
,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN
FROM ODS_CUPD_CLD_ACCTMASTER_NEW p1
LEFT JOIN ODS_HUB_SSALSFP SSALSFP
ON SSALSFP.ALCTCD = SUBSTR(p1.MXKMBH,1,2)
AND SSALSFP.ALGMAB = SUBSTR(p1.MXKMBH,3,4)
AND SSALSFP.ALACB = SUBSTR(p1.MXKMBH,7,3)
AND SSALSFP.ALACS = SUBSTR(p1.MXKMBH,10,6)
AND SSALSFP.ALACX = SUBSTR(p1.MXKMBH,16,3)
AND SSALSFP.ALSSCD = 'IE'
AND SSALSFP.P_DT <= '$(load_date)'
WHERE P1.P_DT = '$(load_date)'
) t
WHERE t.rn = 1
)

INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)',CHARGE_DEPARTMENT='WPB_CDT_Digitallending')
SELECT
A.acctnbr AS LENDING_REF --借据编号
,NULL AS PCB_ACCT_NO --申请号
,N.contract_info AS APPLY_NO --额度编号
,A.acctnbr AS LIMIT_NO --合同号
,N.contract_info AS CONTRACT_NO --合同号
--,t_branch.org_no AS ORG_NO --机构号
,'CNHSBC900' AS ORG_NO --机构号
,SUBSTR(B.bank_cust_id,0,9) AS BRANCH_CODE --内部核算机构号
,B.bank_cust_id AS CUST_NO --客户号
,'A17013' AS ITEM_CODE --科目号
,NVL(km_gl.MXKMBH,km_ie.MXKMBH) AS ITEM_CODE --科目号
,P3.cb_pointer AS ITEM_CODE --科目号
,P3.lrr_key AS LRR_KEY_ITEM_CODE --LRR Key科目号
,NULL AS HUB_ITEM_CODE --HUB科目号
,P3.account AS NOMINAL_ACC --COA科目
,P3.product AS FTP_PRODUCT_CODE --FTP产品编码
,'020101' AS BUSINESS_TYPE --信贷业务种类
,A.acctnbr AS ACCT_NO --信贷分户账账号
,NULL AS BILL_NO --票据号码
,'A09' AS FUND_SOURCE --贷款资金来源
,'B02' AS SIGN_CHANNEL --贷款签约渠道
,DECODE(p1.DKFFLX,
'新增','01',
'其他-展期','02',
'借新还旧','03',
'重组贷款','04',
'无还本续贷','05',
'01') AS LOAN_ORIGI_TYPE --贷款发放类型
,DECODE(p1.DKFFLX,
'新增','01',
'其他-展期','02',
'借新还旧','03',
'重组贷款','04',
'无还本续贷','05',
'01') AS SRC_LOAN_ORIGI_TYPE --源系统贷款发放类型
,DECODE(p1.FKFS,
'自主支付','1',
'受托支付','2',
'混合支付','3',
'1') AS PAY_MODE --放款方式
,DECODE(p1.FKFS,
'自主支付','1',
'受托支付','2',
'混合支付','3',
'1') AS SRC_PAY_MODE --源系统放款方式
,p1.CYCD AS CCY_CODE --币种
,D.apply_limit AS LOAN_AMT --放款金额
--,E.disbamt - F.prinamt AS LOAN_BAL --本金余额
,p1.HTJE AS LOAN_AMT --放款金额
,p1.DKYE AS LOAN_BAL --本金余额
,NULL AS RESERVE --减值准备
,DECODE(p1.dkwjfl,
'正常','01',
'关注','02',
'次级','03',
'可疑','04',
'损失','05',
'01') AS LOAN_GRADE --五级分类
,SUBSTR(p1.dtao,1,4)||'-'||SUBSTR(p1.dtao,5,2)||'-'||SUBSTR(p1.dtao,7,2) AS ACCT_OPEN_DT --信贷账户开户日期
,SUBSTR(p1.dtao,1,4)||'-'||SUBSTR(p1.dtao,5,2)||'-'||SUBSTR(p1.dtao,7,2) AS SRC_ACCT_OPEN_DT --源系统开户日期
,SUBSTR(p1.idat,1,4)||'-'||SUBSTR(p1.idat,5,2)||'-'||SUBSTR(p1.idat,7,2) AS ISSUE_DT --贷款发放日期
,SUBSTR(p1.idat,1,4)||'-'||SUBSTR(p1.idat,5,2)||'-'||SUBSTR(p1.idat,7,2) AS SRC_ISSUE_DT --源系统贷款发放日期
--150调整，到期日如果有变化，取原始到期日
,CASE WHEN NVL(p1.dkdqrq,'') <> NVL(p2.dkdqrq,'') THEN SUBSTR(p2.dkdqrq,1,4)||'-'||SUBSTR(p2.dkdqrq,5,2)||'-'||SUBSTR(p2.dkdqrq,7,2)
ELSE SUBSTR(p1.dkdqrq,1,4)||'-'||SUBSTR(p1.dkdqrq,5,2)||'-'||SUBSTR(p1.dkdqrq,7,2) END AS LOAN_ORI_MATURITY_DT --贷款原始到期日期
,SUBSTR(p1.dkdqrq,1,4)||'-'||SUBSTR(p1.dkdqrq,5,2)||'-'||SUBSTR(p1.dkdqrq,7,2) AS LOAN_MATURITY_DT --贷款最新到期日期
,A.payoffdate AS SETTLE_DT --实际终止日期
,SUBSTR(p1.ZJRQ,1,4)||'-'||SUBSTR(p1.ZJRQ,5,2)||'-'||SUBSTR(p1.ZJRQ,7,2) AS SETTLE_DT --实际终止日期
,SUBSTR(p1.ZJRQ,1,4)||'-'||SUBSTR(p1.ZJRQ,5,2)||'-'||SUBSTR(p1.ZJRQ,7,2) AS ACCT_CLOSE_DT --信贷账户销户日期
,'F' AS RATE_FLOAT_TYPE --利率类型
,NULL AS RATE_FLOAT_FREQ --利率浮动频率
,DECODE(p1.llx,
'LPR','TR05',
'TR99') AS BASE_RATE_TYPE --基准利率类型
,NULL AS BASE_RATE --基准利率
,B.app_rate AS ACTUAL_RATE --实际利率
,p1.dkll AS ACTUAL_RATE --实际利率
,C.datemat AS NEXT_RATE_CHANGE_DT --下一贷款利率重新定价日
,DECODE(p1.HKFS,
'按月','03',
'按季','04',
'按半年','05',
'按年','06',
'其他-双周','99',
'03') AS PRI_PAY_METHOD --还本频率
,DECODE(p1.HKFS,
'按月','03',
'按季','04',
'按半年','05',
'按年','06',
'其他-双周','99',
'03') AS SRC_PRI_PAY_METHOD --源系统还本频率
,DECODE(p1.JXFS,
'按月结息','03',
'按季结息','04',
'按半年结息','05',
'按年结息','06',
'其他-双周','99',
'03') AS INT_PAY_METHOD --还息频率
,DECODE(p1.JXFS,
'按月结息','03',
'按季结息','04',
'按半年结息','05',
'按年结息','06',
'其他-双周','99',
'03') AS SRC_INT_PAY_METHOD --源系统还息频率
,p1.CYCD AS INT_CCY_CODE --利息币种
,J.amt AS INTEREST --应收利息
,p1.dkrzzh AS LOAN_IN_ACCT_NO --贷款入账账号
,p1.dkrzhm AS LOAN_IN_ACCT_NAME --贷款入账账户名称
,H.open_acct_bank_no AS LOAN_IN_BANK_NO --贷款入账账号所属行号
,p1.rzzhsshmc AS LOAN_IN_BANK_NAME --贷款入账账号所属行名称
,p1.ZQS AS total_period --总期数
,p1.DQQS AS curr_period --当前期数
,SUBSTR(p1.NDAT,1,4)||'-'||SUBSTR(p1.NDAT,5,2)||'-'||SUBSTR(p1.NDAT,7,2) AS next_pay_date --下期还款日期
,p1.XQYHBJ AS next_pay_nominal --下次应还本金
,p1.XQYHLX AS next_pay_rate --下次应还利息
,p1.LXQKQS AS debt_period --逾期期次
,p1.LJQKQS AS total_debt_period --累计逾期期次
,DECODE(p1.HKFS,
'分期付息一次还本','0102',
'利随本清','03',
'其他-按期计算还本付息','0200',
'0201') AS REPAY_MODE --还款方式
,DECODE(p1.HKFS,
'分期付息一次还本','0102',
'利随本清','03',
'其他-按期计算还本付息','0200',
'0201') AS SRC_REPAY_MODE --源系统还款方式
,p1.hkzh AS REPAY_ACCT_NO --还款账号
,p1.hkzhsshmc AS REPAY_BANK_NO --还款账号所属行号
,p1.hkzhsshmc AS REPAY_BANK_NAME --还款账号所属行名称
,'CHN' AS LOAN_PURPOSE_COUNTRY_CODE --贷款投向国家
,p1.DKTXDQ AS LOAN_PURPOSE_DIST --贷款投向地区
,p4.reserved_field9 AS LOAN_PURPOSE_INDU --贷款投向行业
,NULL AS LOAN_PURPOSE_SNI --贷款投向SNI
,NULL AS LOAN_PURPOSE_CUL --贷款投向CUL
,NULL AS LOAN_PURPOSE_IND_UPDATE_FLAG --贷款投向行业更新标识
,p1.JJDKYT AS PURPOSE --贷款用途
,NULL AS ABROAD_LOAN_PURPOSE --境外贷款用途
,'N' AS SYNDICATED_LOAN_FLAG --银团贷款标志
,NULL AS IS_OUTSHEET --贷款是否出表
,DECODE(p1.dkzt,
'正常','01',
'逾期','02',
'结清','03',
'核销','05',
'01') AS LOAN_STATUS --贷款状态
,DECODE(p1.dkzt,
'正常','01',
'逾期','02',
'结清','03',
'核销','05',
'01') AS SRC_LOAN_STATUS --源系统贷款状态
,DECODE(p1.zhzt,
'正常','01',
'逾期','02',
'结清','03',
'销户','03',
'01') AS LOAN_ACCT_STATUS --信贷账户状态
,DECODE(p1.zhzt,
'正常','01',
'逾期','02',
'结清','03',
'销户','03',
'01') AS SRC_LOAN_ACCT_STATUS --源系统信贷账户状态
,NULL AS collection --催收标志
,NULL AS collection_type --催收方式
,CASE WHEN C.curracctstatcd = 'CLS' THEN '66'
WHEN C.curracctstatcd = 'CO' THEN '05'
WHEN C.curracctstatcd = 'POFF' THEN '01'
END AS SETTLE_MODE --贷款终结方式
,CASE WHEN C.curracctstatcd = 'CLS' THEN '其他终结方式：销户'
END AS SRC_SETTLE_MODE --源系统贷款终结方式
,NULL AS ACCT_STATUS --账户状态
,NULL AS SRC_ACCT_STATUS --源系统账户状态
,'EASTRBBCL' AS CREDITOR_NO --客户经理工号
--,K.duedate AS PRIN_OD_DT --本金逾期日期
,SUBSTR(p1.QBRQ,1,4)||'-'||SUBSTR(p1.QBRQ,5,2)||'-'||SUBSTR(p1.QBRQ,7,2) AS PRIN_OD_DT --本金逾期日期
--,I.prinoutstanding AS PRIN_OD_AMT --欠本金额
,p1.QBJE AS PRIN_OD_AMT --欠本金额
--,L.duedate AS INT_OD_DT --利息逾期日期
,SUBSTR(p1.GXRQ,1,4)||'-'||SUBSTR(p1.GXRQ,5,2)||'-'||SUBSTR(p1.GXRQ,7,2) AS INT_OD_DT --利息逾期日期
--,CASE WHEN DATEDIFF(TO_DATE('$(load_date)'),TO_DATE(L.duedate),'day') <= 90 THEN I.intoutstanding + I.odpintamt
-- END AS INT_OD_AMT --表内欠息余额
--,CASE WHEN DATEDIFF(TO_DATE('$(load_date)'),TO_DATE(L.duedate),'day') > 90 THEN I.intoutstanding + I.odpintamt
-- END AS INTEREST_BALANCE2 --表外欠息余额
,p1.BNQXYE AS INT_OD_AMT --表内欠息余额
,p1.BWQXYE AS INTEREST_BALANCE2 --表外欠息余额
,NULL AS PENALTYINT_AMT --罚息
,NULL AS COMPOUNDINT_AMT --逾期复利
,NULL AS MITIGATE --减免
,NULL AS EXTRA_FEE --其他费用
,NULL AS CURR_NON_TRADING_ADJ_AMT --本月非交易变动
,NULL AS CAPTIAL_RATIO --资本充足率
,NULL AS COOPER_NAME --合作机构名称
,NULL AS INT_SUBSIDY --利息补贴
,NULL AS SRC_INT_SUBSIDY --源系统利息补贴
,NULL AS INDUSTRI_STRUCT_TYPE --产业结构类型
,NULL AS UPGRADE_FLAG --升级标志
,'N' AS IS_INTERNET_LOAN --是否互联网贷款
,DECODE(p1.SFKJDK,
'是','Y',
'N') AS IS_TECHNOLOGY_LOAN --是否科技贷款
,DECODE(p1.SFLSDK,
'是','Y',
'N') AS IS_GREENLOAN --是否绿色贷款
,NULL AS GREENLOAN_TYPE --绿色贷款类型
,NULL AS IS_GREEN_TRANSFINA --是否绿色转型金融
,NULL AS GREEN_TRANSFINA_TYPE --绿色转型金融类型
,NULL AS IS_GREEN_CONSUME --是否绿色消费
,NULL AS GREEN_CONSUME_TYPE --绿色消费类型
,'N' AS IS_VTR_GTR --是否创业担保贷款
,NULL AS FIRST_LOAN_FLG --首贷标志
,NULL AS is_farmers_insur --是否农户保险
,NULL AS othre_py_guarway --其他担保方式
,NULL AS VTR_GTR_TYPE --创业担保类型
,NULL AS SRC_VTR_GTR_TYPE --源系统创业担保类型
,NULL AS ENVSAFE_ENPR_LOAN --环保安全企业贷款
,DECODE(p1.SFSNDK,
'是','Y',
'N') AS IS_AGRIC_LOAN --是否涉农贷款
,CASE WHEN P1.SFPHXSNDK = '是' THEN 'Y'
WHEN P1.SFPHXXWQYDK = '是' THEN 'Y'
ELSE 'N' END AS IS_PRATTWHITNEY_LOAN --是否普惠型贷款
,NULL AS PGUPER_AMT --普惠金额
,NULL AS EXT_DEBT_NO --外部债务编号
,NULL AS LOAN_EX_GU_NO --贷款担保编号
,NULL AS CFEO_GUD_APPROVAL_NO --审批编号
,NULL AS CFEO_GUD_APPROVAL_CCY_CODE --审批币种
,NULL AS CFEO_GUD_APPROVAL_AMT --审批金额
,'3' AS BAD_LOAN_RELEASE_TYPE --不良贷款风险分担方式
,NULL AS SRC_BAD_LOAN_RELEASE_TYPE --源系统不良贷款风险分担方式
,NULL AS IS_COVERED_ASSET --是否有抵押资产
,NULL AS COLL_RES_MATURITY --抵质押物到期日
,NULL AS OVERDUE_TYPE --逾期类型
,NULL AS USEOFUNDS_TYPE --资金用途类型
,NULL AS REMARK --备注
,NULL AS SYS_SRC_CODE --源系统代码
,NULL AS business_line --业务条线
,NULL AS tag_country --国家标签
,NULL AS tag_entity --实体标签
,NULL AS tag_branch --机构标签
,NULL AS tag_gbgf --国别标签
,NULL AS tag_reserve --备用标签
,'WPB_RBB_Loan' AS tag_primary_accountable_party --主责部门
,'WPB_RBB_Loan' AS tag_responsible_party --报送部门
,NULL AS Reserved_Field1
,NULL AS Reserved_Field2
,NULL AS Reserved_Field3
,NULL AS Reserved_Field4
,NULL AS Reserved_Field5
,NULL AS Reserved_Field6
,NULL AS Reserved_Field7
,NULL AS Reserved_Field8
,NULL AS Reserved_Field9
,NULL AS Reserved_Field10
,NULL AS Reserved_Field11
,NULL AS Reserved_Field12
,NULL AS Reserved_Field13
,NULL AS Reserved_Field14
,NULL AS Reserved_Field15
,NULL AS Reserved_Field16
,NULL AS Reserved_Field17
,a.payoffdate AS Reserved_Field18 --150个人贷款发生额使用
,p3.CN_SOURCE_SYSTEM_PDT_CODE AS Reserved_Field19 --1104用
,SUBSTR(A.acctnbr,9) AS Reserved_Field20
,NULL AS dis_user --修改用户
,NULL AS dis_operate_flag --操作标志
,NULL AS dis_data_from --数据来源
,NULL AS dis_edit_lock --编辑锁
,NULL AS dis_verify_status --校验状态
,'$(load_date)' AS dis_data_date
--20250327 chenbinbin HBCNRDQE-3524：dis_bank_id取数口径修改为'CNHSBC900Z'
,NVL(SUBSTR(B.bank_cust_id,0,9),'CNHSBC900Z') AS dis_bank_id
,NULL AS dis_curr_step
,NULL AS dis_step_id
,NULL AS dis_modify_user
,NULL AS dis_status_alias
,getdate() AS rec_creat_dt_tm --20240115新增
,NULL AS rec_updt_dt_tm --20240115新增
,NULL AS RESERVED_1
,B.app_loan_term AS RESERVED_2 --接入terms逻辑
,NULL AS RESERVED_3
,NULL AS RESERVED_4
,NULL AS RESERVED_5
,NULL AS RESERVED_6
,NULL AS RESERVED_7
,NULL AS RESERVED_8
,NULL AS RESERVED_9
,NULL AS RESERVED_10
,NULL AS RESERVED_11
,NULL AS RESERVED_12
,NULL AS RESERVED_13
,NULL AS RESERVED_14
,NULL AS RESERVED_15
,NULL AS PRIMARY_SRC_SYSTEM
,NULL AS DQ_RESULT
,NULL AS COM_RESERVED_1
,NULL AS COM_RESERVED_2
,NULL AS COM_RESERVED_3
,NULL AS COM_RESERVED_4
,NULL AS COM_RESERVED_5
,NULL AS COM_RESERVED_6
,NULL AS DM_FLAG1
,CASE WHEN SUBSTR(p1.dkrzzh,1,6) = 'CNHSBC' AND SUBSTR(p1.dkrzzh,10,1) = '9' THEN 'NI'
WHEN EXISTS (SELECT 1 FROM BDM_ACC_INTERNAL_COUNTERPARTY WHERE data_dt = '$(load_date)' AND acct_no = p1.dkrzzh) THEN 'NI'
WHEN SUBSTR(p1.dkrzzh,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('$(load_date)') a WHERE a.cust_no = dsf_tm.cust_no AND a.CUST_TYPE IN ('I','3')) THEN 'I'
WHEN SUBSTR(p1.dkrzzh,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('$(load_date)') a WHERE a.cust_no = dsf_tm.cust_no AND a.CUST_TYPE = 'C') THEN 'NI'
WHEN EXISTS (
SELECT 1
FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS b
WHERE b.p_dt = (SELECT MAX(p_dt) p_dt FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS) --最新的脱敏白名单数据
AND NVL('1',b.p_dt) = NVL('1',p1.p_dt) --必须加一个恒等式
AND LOWER(p1.dkrzhm) LIKE CONCAT('%',LOWER(b.datamask_keywords),'%')
) THEN 'NI'
WHEN regexp_instr(p1.dkrzhm,'[0-9]+$') > 0 --判断客户名称是否含有数字
OR (regexp_instr(p1.dkrzhm,'[A-Za-z]+$') > 0 AND length(p1.dkrzhm) <> lengthb(p1.dkrzhm))
--判断客户名称是否同时含有中文和英文
THEN 'NI'
WHEN lengthb(p1.dkrzhm) <= 15 THEN 'I' --判断对方户名是否小于等于15位
WHEN lengthb(p1.dkrzhm) > 15 THEN 'NI' --判断对方户名是否大于15位
ELSE NULL
END AS DM_FLAG2
,CASE WHEN p4.reserved_field9 = 'Z' THEN 'F' ELSE 'I' END AS loan_purpose_onoff_flag --境内外标识（'F'境外/'I'境内）
FROM ods_ccb_cb_loan_acctloan A
LEFT JOIN ods_ccb_ap_app_main_info B
ON A.contractid = B.app_no
AND B.P_DT = '$(load_date)'
LEFT JOIN ods_ccb_cb_loan_acct C
ON A.acctnbr = C.acctnbr
AND C.P_DT = '$(load_date)'
LEFT JOIN ods_ccb_ln_app_inf D
ON A.contractid = D.apply_nbr
AND D.P_DT = '$(load_date)'
LEFT JOIN ods_ccb_cb_loan_acctloandisb E
ON A.acctnbr = E.acctloannbr
AND E.P_DT = '$(load_date)'
LEFT JOIN (SELECT F1.acctloannbr,SUM(F1.prinamt) AS prinamt
FROM ods_ccb_cb_loan_acctloanpmt F1
WHERE F1.P_DT = '$(load_date)'
GROUP BY F1.acctloannbr) F
ON A.acctnbr = F.acctloannbr
LEFT JOIN ods_ccb_ln_loan_inf G
ON A.acctnbr = G.iou_id
AND G.P_DT = '$(load_date)'
LEFT JOIN ods_ccb_ln_order_inf H
ON A.contractid = H.order_nbr
AND H.P_DT = '$(load_date)'
-- LEFT JOIN ods_ccb_cb_loan_acctloantermhist I
-- ON A.acctnbr = I.acctnbr
-- AND I.termstatcd = 'OD'
-- AND I.P_DT = '$(load_date)'
LEFT JOIN (select x.acctnbr
,SUM(CASE WHEN balcatcd = 'RCVB' AND baltypcd = 'INT' THEN amt --逾期应收利息
WHEN balcatcd = 'NOTE' AND baltypcd = 'GINT' THEN amt --本金应计利息
WHEN balcatcd = 'ODP' AND baltypcd = 'INT' THEN amt --逾期应收罚息
WHEN balcatcd = 'ODP' AND baltypcd = 'GINT' THEN amt --逾期应计罚息
END) AS amt --利息合计
from
ods_ccb_cb_loan_acctbal x
where x.P_DT = '$(load_date)'
GROUP BY x.acctnbr) J
ON A.acctnbr = J.acctnbr
LEFT JOIN (SELECT K1.acctnbr,MIN(K1.duedate) AS duedate
FROM ods_ccb_cb_loan_acctloantermhist K1
WHERE K1.prinoutstanding <> 0
AND K1.termstatcd = 'OD'
GROUP BY K1.acctnbr) K
ON A.acctnbr = K.acctnbr
LEFT JOIN (SELECT L1.acctnbr,MIN(L1.duedate) AS duedate
FROM ods_ccb_cb_loan_acctloantermhist L1
WHERE L1.prinoutstanding <> 0
AND L1.termstatcd = 'OD'
GROUP BY L1.acctnbr) L
ON A.acctnbr = L.acctnbr
LEFT JOIN ods_ccb_ln_app_inf_basic M
ON A.contractid = M.apply_nbr
AND M.P_DT = '$(load_date)'
LEFT JOIN ods_ccb_ln_account_inf N
ON A.contractid = N.contract_id
AND N.P_DT = '$(load_date)'
LEFT JOIN temp_kmbh_gl km_gl
ON A.acctnbr = km_gl.lending_ref
LEFT JOIN temp_kmbh_ie km_ie
ON A.acctnbr = km_ie.lending_ref
LEFT JOIN ODS_CUPD_CLD_ACCTMASTER_NEW p1
ON A.acctnbr = p1.acnw
AND p1.P_DT = '$(load_date)'
--150添加维护原始到期日
LEFT JOIN ODS_CUPD_CLD_ACCTMASTER_NEW p2 ON p1.acnw = p2.acnw AND p2.P_DT = date_add('$(load_date)', INTERVAL -1 DAY)
--2024-04-08注释
-- LEFT JOIN
-- (SELECT T.loanno
-- ,T.transbankname
-- ,ROW_NUMBER() OVER(PARTITION BY T.loanno ORDER BY T.transpaydate DESC,T.transpayamt DESC,T.tradeseqno DESC) RN
-- FROM ODS_CCB_REPAY_LOAN_ACCOUNT_DELTA T
-- WHERE T.P_DT = '$(load_date)') P2
-- ON A.acctnbr = P2.loanno
-- AND P2.RN = 1
-- LEFT JOIN bdm_pub_hsbc_acct_branch t_branch
-- ON SUBSTR(B.bank_cust_id,0,9) = t_branch.branch_code
-- AND t_branch.data_dt = '$(load_date)'
LEFT JOIN ( --20240202调整科目号
SELECT *
,ROW_NUMBER() OVER(PARTITION BY arrangement_local_number ORDER BY SUBSTR(cb_pointer,2,5),BAL desc) AS rn
FROM (
SELECT
arrangement_local_number
,cb_pointer
,lrr_key
,account
,product
,abs(sum(from_ytd_bal)) AS BAL
,CN_SOURCE_SYSTEM_PDT_CODE
FROM bdm_fin_lrr_key_base_info bi
WHERE SUBSTR(glbl_source_chartfield,1,3) = '1CR'
AND data_dt = '$(load_date)'
AND EXISTS (SELECT 1
FROM ODS_CDP_GDC_TABLE_COA_LIST c1 --手工补录的COA科目LIST，全量补录，可沿用上一期
WHERE c1.p_dt = (SELECT MAX(p_dt) FROM ODS_CDP_GDC_TABLE_COA_LIST WHERE p_dt <= TO_DATE(LASTDAY(TO_DATE('$(load_date)','yyyy-mm-dd'))))
AND c1.source_chartfield = '1CR'
AND c1.value2 = 'loan'
AND bi.account = c1.nominal_accounts)
GROUP BY
arrangement_local_number
,cb_pointer
,account
,product
,lrr_key
,CN_SOURCE_SYSTEM_PDT_CODE
) km
) p3 --会出现重复科目（99999和其他科目）如果有99999和其他科目，剔除99999科目数据
ON SUBSTR(A.acctnbr,9) = p3.arrangement_local_number
AND p3.rn = 1
--贷款投向行业处理2024-04-08
LEFT JOIN BDM_CUS_ICUSTOMER p4
ON B.bank_cust_id = p4.cust_no
AND p4.data_dt = '$(load_date)'
--取对手方客户号判断脱敏
LEFT JOIN BDM_ACC_DEPOSIT_ACCT dsf_tm
ON p1.dkrzzh = dsf_tm.acct_no
AND dsf_tm.data_dt = '$(load_date)'
WHERE A.P_DT = '$(load_date)'
;


-- 操作日志记录
INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)
SELECT '$(load_date)' AS data_dt
,'BDM' AS object_domain
,'ACC' AS sub_src_system
,'BDM_ACC_LOAN_INFO' AS table_name
,'BDM_ACC_LOAN_INFO_Digitallending' AS job_name
,COUNT(1) AS total_rows
,getdate() AS load_time
,'Y' AS STATUS
,NULL AS remarks
FROM bdm_acc_loan_info
WHERE data_dt = '$(load_date)'
AND charge_department = 'WPB_CDT_Digitallending'
;
