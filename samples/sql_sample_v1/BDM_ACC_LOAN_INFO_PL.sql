-- 源表名:
-- ODS_CUPD_PLOAN_ACCTM_NEW5
-- ODS_CUPD_PLOAN_APS_CREDINF5
-- BDM_FIN_LRR_KEY_BASE_INFO
-- BDM_PUB_HSBC_ACCT_BRANCH
-- 目标表: BDM_ACC_LOAN_INFO (贷款信息表)
-- 创建者: wei.chen
-- 创建时间: 20221116
-- 文件名: BDM_ACC_LOAN_INFO_PL
-- 修改日志:
-- yyyymmdd  name       comment
-- 20240116  马遥        新增 rec_creat_dt_tm, rec_updt_dt_tm, 修改 dis_status_alias
-- 20240202  陈宝根      修改备注
-- 20240904  luowei     HBCNRDQE-1504
-- 20250327  chenbinbin HBCNRDQE-3526:dis_bank_id兜底'CNHSBC900Z'
-- 20250604  chenbinbin 新增 loan_purpose, loan_purpose_onoff_flag
-- 20250725  sunhao     修改 loan_purpose, 新增 loan_purpose_indus 字段 modify 150 HBCNRDQE-4040 HBCNRDQE-4157
SET odps.sql.decimal.odps2=true;
INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan');
--PLOAN 部分贷款
SELECT distinct a.acnw AS LENDING_REF,  -- 借据号
NULL AS PCBACCT_NO,  -- 表内账号
a.acnw AS APPLY_NO,  -- 申请号
a.acnw AS LIMIT_NO,  -- 额度号
a.acnw AS CONTRACT_NO,  -- 合同号
T_BRANCH.org_no AS ORG_NO,  -- 机构号
a.ctcd||a.gmab||LPAD(a.acb,3,'0') AS BRANCH_CODE,  -- 网点机构号
a.khtybh AS CUST_NO,  -- 客户号
p2.cb_pointer AS ITEM_CODE,  -- 科目号
p2.lrr_key AS LRR_KEY_ITEM_CODE,  -- LRR Key 科目号
'172206' AS HUB_ITEM_CODE,  -- HUB科目号
p2.account AS NOMINAL_ACCT,  -- COA核算账号
p2.product AS FTP_PRODUCT_CODE,  -- FTP 产品代码
'102029902' AS BUSINESS_TYPE,  -- 业务种类
NULL AS ACCT_NO,  -- 账号
NULL AS BILL_NO,  -- 借据号
'A09' AS FUND_SOURCE,  -- 资金来源
'AGLL' AS STGR_CHANNEL,  -- 存储渠道
'01' AS LOAN_ORIGIN_TYPE,  -- 贷款发起类型
NULL AS SRC_LOAN_ORIGIN_TYPE,  -- 来源贷款发起类型
CASE WHEN a.fkfs='自主支付' THEN '01' WHEN a.fkfs='受托支付' THEN '02' END AS PAY_MODE,  -- 支付方式
NULL AS SRC_PAY_MODE,  -- 来源支付方式
a.cycd AS CCY_CODE,  -- 币种
a.ctba AS LOAN_AMT,  -- 贷款金额
CASE WHEN a.dkzt='核销' THEN '01' ELSE a.dkye END AS LOAN_BAL,  -- 贷款余额
NULL AS RESERVE,  -- 备用
CASE WHEN a.dkwjf1='正常' THEN '01' WHEN a.dkwjf1='次级' THEN '02' WHEN a.dkwjf1='关注' THEN '03' WHEN a.dkwjf1='可疑' THEN '04' WHEN a.dkwjf1='损失' THEN '05' END AS LOAN_GRADE,  -- 贷款五级分类
NULL AS ACCT_OPEN_DT,  -- 账户开户日期
NULL AS SRC_ACCT_OPEN_DT,  -- 来源账户开户日期
TO_CHAR(TO_DATE(a.idat,'YYYYMMDD'),'YYYY-MM-DD') AS ISSUE_DT,  -- 借据发放日期
TO_CHAR(TO_DATE(a.idat,'YYYYMMDD'),'YYYY-MM-DD') AS SRC_ISSUE_DT,  -- 来源借据发放日期
TO_CHAR(TO_DATE(a.dkdara,'YYYYMMDD'),'YYYY-MM-DD') AS LOAN_ORI_MATURITY_DT,  -- 贷款到期日期
TO_CHAR(TO_DATE(a.dkdara,'YYYYMMDD'),'YYYY-MM-DD') AS LOAN_MATURITY_DT,  -- 贷款到期日期
TO_CHAR(TO_DATE(a.ja,'YYYYMMDD'),'YYYY-MM-DD') AS SETTLE_DT,  -- 结清日期
NULL AS ACCT_CLOSE_DT,  -- 账户关闭日期
'UF' AS RATE_FLOAT_TYPE,  -- 利率浮动方式
NULL AS RATE_FLOAT_FREQ,  -- 利率浮动频率
'TB88' AS BASE_RATE_TYPE,  -- 基准利率类型
NULL AS BASE_RATE,  -- 基准利率
'a.sjlv' AS ACTUAL_RATE,  -- 实际利率
TO_CHAR(TO_DATE(a.htdqrq, 'YYYYMMDD'), 'YYYY-MM-DD') AS NEXT_RATE_CHANGE_DT,  -- 下次利率调整日期
'83' AS PRI_PAY_METHOD,  -- 本金偿还方式
NULL AS SRC_PRI_PAY_METHOD,  -- 来源本金偿还方式
'83' AS INT_PAY_METHOD,  -- 利息偿还方式
NULL AS SRC_INT_PAY_METHOD,  -- 来源利息偿还方式
a.cycd AS INT_CCY_CODE,  -- 利息币种
NULL AS INTEREST,  -- 利息
a.dkrzzh AS LOAN_IN_ACCT_NO,  -- 贷款入账账号
a.dkrzhm AS LOAN_IN_ACCT_NAME,  -- 贷款入账户名
NULL AS LOAN_IN_BANK_NO,  -- 贷款入账行号
NULL AS LOAN_IN_BANK_NAME,  -- 贷款入账行名
NULL AS TOTAL_PERIOD,  -- 总期数
NULL AS CURR_PERIOD,  -- 当前期数
NULL AS NEXT_PAY_DATE,  -- 下次还款日期
NULL AS NEXT_PAY_NOMINAL,  -- 下次还款本金
NULL AS NEXT_PAY_RATE,  -- 下次还款利率
NULL AS DEBT_PERIOD,  -- 逾期期数
NULL AS TOTAL_DEBT_PERIOD,  -- 累计逾期期数
'99' AS REPAY_MODE,  -- 还款方式
NULL AS SRC_REPAY_MODE,  -- 来源还款方式
a.hkzh AS REPAY_ACCT_NO,  -- 还款账号
NULL AS REPAY_BANK_NO,  -- 还款行号
NULL AS REPAY_BANK_NAME,  -- 还款行名
'CHN' AS LOAN_PURPOSE_COUNTRY_CODE,  -- 贷款用途国家
T_BRANCH.ORG_AREA_CODE AS LOAN_PURPOSE_DIST,  -- 贷款用途地区
NULL AS LOAN_PURPOSE_INDU,  -- 贷款用途行业
NULL AS LOAN_PURPOSE_ISSUE,  -- 贷款用途分类
NULL AS LOAN_PURPOSE_CUL,  -- 贷款用途文化
NULL AS LOAN_PURPOSE_IND_UPDATE_FLAG,  -- 贷款用途行业更新标识
a.sydkyt AS PURPOSE,  -- 贷款用途
NULL AS ABROAD_LOAN_PURPOSE,  -- 境外贷款用途
NULL AS SYNDICATED_LOAN_FLAG,  -- 银团贷款标识
NULL AS TS_OUTSHEET,  -- 表外标识
CASE WHEN a.dkzt='正常' THEN '01' WHEN a.dkzt='逾期' THEN '02' ELSE '03' END AS LOAN_STATUS,  -- 贷款状态
NULL AS SRC_LOAN_STATUS,  -- 来源贷款状态
NULL AS LOAN_ACCT_STATUS,  -- 贷款账户状态
NULL AS SRC_LOAN_ACCT_STATUS,  -- 来源贷款账户状态
NULL AS COLLECTION,  -- 核销
NULL AS COLLECTION_TYPE,  -- 核销类型
CASE WHEN a.dkzt='结清' THEN '01' WHEN a.dkzt='核销' THEN '05' WHEN a.dkzt LIKE '%转让%' THEN '02' END AS SETTLE_MODE,  -- 结清方式
NULL AS SRC_SETTLE_MODE,  -- 来源结清方式
NULL AS ACCT_STATUS,  -- 账户状态
NULL AS SRC_ACCT_STATUS,  -- 来源账户状态
CASE WHEN NVL(c.jbrgh,'')='' THEN 'EXITSTAFF' ELSE c.jbrgh END AS CREDITOR_NO,  -- 客户经理
TO_CHAR(TO_DATE(a.abza,'YYYYMMDD'),'YYYY-MM-DD') AS PRIN_OD_DT,  -- 本金逾期日期
a.qbje AS PRIN_OD_AMT,  -- 本金逾期金额
TO_CHAR(TO_DATE(a.qxxa,'YYYYMMDD'),'YYYY-MM-DD') AS INT_OD_DT,  -- 利息逾期日期
a.bnaxye AS INT_OD_AMT,  -- 利息逾期金额
a.bwaxye AS INTEREST_BALANCE,  -- 表内欠息
NULL AS PENALTY_INT_AMT,  -- 罚息金额
NULL AS COMPOUND_INT_AMT,  -- 复利金额
NULL AS MITIGATE,  -- 缓释
NULL AS EXTRA_FEE,  -- 额外费用
NULL AS CURR_NON_TRADING_ADJ_AMT,  -- 当期非交易调整金额
NULL AS CAPITAL_RATIO,  -- 资本占比
NULL AS COOPER_NAME,  -- 合作方名称
NULL AS INT_SUBSIDY,  -- 利息补贴
NULL AS SRC_INT_SUBSIDY,  -- 来源利息补贴
NULL AS INDUSTRI_STRUCT_TYPE,  -- 产业结构类型
NULL AS UPGRADE_FLAG,  -- 升级标识
'N' AS TS_INTERNET_LOAN,  -- 互联网贷款标识
'N' AS TS_TECHNOLOGY_LOAN,  -- 科技贷款标识
'N' AS TS_GREEN_LOAN,  -- 绿色贷款标识
NULL AS GREEN_LOAN_TYPE,  -- 绿色贷款类型
NULL AS TS_GREEN_TRANS_FIN,  -- 绿色转型金融标识
NULL AS GREEN_TRANS_FIN_TYPE,  -- 绿色转型金融类型
NULL AS TS_GREEN_CONSUME,  -- 绿色消费标识
NULL AS GREEN_CONSUME_TYPE,  -- 绿色消费类型
NULL AS TS_VIR_CTR,  -- 虚拟柜台标识
NULL AS FIRST_LOAN_FLG,  -- 首贷标识
NULL AS IS_FARMERS_INSUR,  -- 涉农保险标识
NULL AS OTHER_PY_GUARWAY,  -- 其他担保方式
NULL AS VIR_CTR_TYPE,  -- 虚拟柜台类型
NULL AS SRC_VIR_CTR_TYPE,  -- 来源虚拟柜台类型
NULL AS ENVSAFE_ENPR_LOAN,  -- 环境安全企业贷款
'N' AS TS_AGRIC_LOAN,  -- 涉农贷款标识
'N' AS TS_PRAT_TV_HITNEY_LOAN,  -- 普惠电视惠农贷款标识
NULL AS POUPER_AMT,  -- 扶贫金额
NULL AS EXT_DEBT_NO,  -- 外部借据号
NULL AS LOAN_EXG_NO,  -- 贷款交换号
NULL AS CFEO_GUD_APPROVAL_NO,  -- 跨境担保业务核准件号
NULL AS CFEO_GUD_APPROVAL_CCY_CODE,  -- 跨境担保业务核准币种
NULL AS CFEO_GUD_APPROVAL_AMT,  -- 跨境担保业务核准金额
NULL AS BAD_LOAN_RELEASE_TYPE,  -- 不良贷款释放类型
NULL AS SRC_BAD_LOAN_RELEASE_TYPE,  -- 来源不良贷款释放类型
NULL AS TS_COVERED_ASSET,  -- 抵债资产标识
NULL AS COLL_RES_MATURITY,  -- 担保物到期日
NULL AS OVERDUE_TYPE,  -- 逾期类型
NULL AS USE_OF_FUNDS_TYPE,  -- 资金用途类型
NULL AS REMARK,  -- 备注
NULL AS SYS_SRC_CODE,  -- 系统来源代码
NULL AS business_line,
NULL AS tag_country,
NULL AS tag_entity,
NULL AS tag_branch,
NULL AS tag_gbaf,
NULL AS tag_reserve,
'WPB_Ploan' AS tag_primary_accountable_party,
'OPS_CLBS_PLoan' AS tag_responsible_party,
NULL AS Reserved_Field1,
NULL AS Reserved_Field2,
NULL AS Reserved_Field3,
NULL AS Reserved_Field4,
NULL AS Reserved_Field5,
NULL AS Reserved_Field6,
NULL AS Reserved_Field7,
NULL AS Reserved_Field8,
NULL AS Reserved_Field9,
NULL AS Reserved_Field10,
NULL AS Reserved_Field11,
NULL AS Reserved_Field12,
NULL AS Reserved_Field13,
NULL AS Reserved_Field14,
NULL AS Reserved_Field15,
NULL AS Reserved_Field16,
NULL AS Reserved_Field17,
'ACR' AS Reserved_Field18,
NULL AS Reserved_Field19,
a.acnw AS Reserved_Field20,
NULL AS dis_user,
NULL AS dis_operate_flag,
NULL AS dis_data_from,
NULL AS dis_edit_lock,
NULL AS dis_verify_status,
'${load_date}' AS dis_data_date,
--20250327 chenbinbin HBCNRDQE-3526:dis_bank_id兜底'CNHSBC900Z'
NVL(T_BRANCH.org_no,'CNHSBC900Z') AS dis_bank_id,
NULL AS dis_curr_step,
NULL AS dis_step_id,
NULL AS dis_modify_user,
NULL AS dis_status_alias,
getdate() AS rec_creat_dt_tm,  --20240116 新增
NULL AS rec_updt_dt_tm,  --20240116 新增
NULL AS reserved_1,
NULL AS reserved_2,
NULL AS reserved_3,
NULL AS reserved_4,
NULL AS reserved_5,
NULL AS reserved_6,
NULL AS reserved_7,
NULL AS reserved_8,
NULL AS reserved_9,
NULL AS reserved_10,
NULL AS reserved_11,
NULL AS reserved_12,
NULL AS reserved_13,
NULL AS reserved_14,
NULL AS reserved_15,
NULL AS primary_src_system,
NULL AS dq_result,
NULL AS com_reserved_1,
NULL AS com_reserved_2,
NULL AS com_reserved_3,
NULL AS com_reserved_4,
NULL AS com_reserved_5,
NULL AS com_reserved_6,
NULL AS dm_flag1,
NULL AS dm_flag2,
'T' AS loan_purpose_onoff_flag  --贷款用途标识
FROM (select *,row_number() over (partition by acnw) as rn from ODS_CUPD_PLOAN_ACCTM_NEW5 where p_dt='${load_date}') a
LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'
--ODS_CUPD_PLOAN_APS_CREDINF5 信贷信息
LEFT JOIN BDM_PUB_BRANCH D ON SUBSTR(A.HKZH,1,9) = D.org_no AND D.DATA_DT = '${load_date}' --贷款入账账号取值
AND a.p_dt = c.p_dt
JOIN (
SELECT *, ROW_NUMBER() OVER(PARTITION BY arrangement_local_number ORDER BY SUBSTR(cb_pointer,2,5),BAL desc) AS rn
FROM (
SELECT arrangement_local_number,
cb_pointer,
lrr_key,
account,
product,
abs(sum(from_ytd_bal)) AS BAL
FROM bdm_fin_lrr_key_base_info bi
WHERE SUBSTR(glbl_source_chartfield,1,3)='ACR'
AND data_dt='${load_date}'
AND exists (select 1
from ODS_CDP_GDC_TABLE_COA_LIST cl
where cl.p_dt=(select max(p_dt) from ODS_CDP_GDC_TABLE_COA_LIST where p_dt<=TO_DATE(LAST_DAY(TO_DATE('${load_date}','yyyy-mm-dd'))))
and cl.source_chartfield='ACR'
and cl.value2='loan'
and bi.account=cl.nominal_accounts)
group by arrangement_local_number,
cb_pointer,
account,
product,
lrr_key) km1
) p2 --会出现重复科目（99999和其他科目）如果有99999和其他科目，剔除99999科目数据
ON a.acnw = p2.arrangement_local_number AND p2.rn = 1
LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'
WHERE a.p_dt = '${load_date}' and a.rn='1';
--操作日志记录
INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)
SELECT '${load_date}' AS data_dt,
'BDM' AS object_domain,
'ACR' AS sub_src_system,
'BDM_ACC_LOAN_INFO' AS table_name,
'BDM_ACC_LOAN_INFO_PL' AS job_name,
COUNT(1) AS total_rows,
getdate() AS load_time,
'Y' AS STATUS,
NULL AS remarks
FROM bdm_acc_loan_info
WHERE data_dt = '${load_date}'
AND charge_department = 'OPS_CLBS_PLoan';
