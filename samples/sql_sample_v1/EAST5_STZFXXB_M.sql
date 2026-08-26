
--ODPS EAST5_STZFXXB_M受托支付信息表取数逻辑
--author:shengze.wei
--create time:2022-09-10 10:26
--****************************************
--表：［east5.east5_stzfxxb］［受托支付信息表］
--名：
--[BDM.BDM_ACC_ENTRUSTED_PAYMENT]
--[BDM.BDM_ACC_LOAN_INFO]
--[BDM.BDM_PUB_BRANCH]
--［BDM_ACC_INTERNAL_COUNTERPARTY］20240124新增
--BDM_SYS_FTPSJE_JYDSF
--BDM_SYS_FTPSJE_JYDSF_MONTH
--BDM_ACC_DEPOSIT_ACCT
--BDM_PUB_HSBC_ACCT_BRANCH
--ODS_HUB_HD_PRFP
--脚本功能：受托支付信息表数据处理
--创建时间：2022-09-22
--文件名：EAST5_STZFXXB_M
--作者：chenwei
--修改记录：
--20240116 luowei gsfzjg字段置空
--20240117 luowei WPB_RBB,OPS_CDT部门对手方信息字段取值修改
--20240129 luowei 去除distinct
--20240201 SUNXIAOTONG 增加coretrade备注逻辑
--20240328 mengting.liu 新增备用字段，脱敏字段DM_FLAG1、DM_FLAG2
--20240501 SUNXIAOTONG 增加east自定义字段
--20240507 luowei CDTRBB对手方逻辑修改
--20240510 luowei RFN备注字段处理
--20240510 XIUSHUAI 脱敏字段DM_FLAG1、DM_FLAG2逻辑改动
--20240511 XIUSHUAI 备用字段和脱敏修改
--20240704 mengting.liu 脱敏字段添加兜底逻辑：DM_FLAG1-若取值为空，则默认NI
--20240807 mengting.liu 增加CHARGE_DEPARTMENT自动分区，COM_RESERVED_1增加CHARGE_DEPARTMENT
--20240812 luowei OPS_MBS部门受托支付对象户名字符调整成与信贷分户账明细一致
--20241030 linfa.xiao 修改备用字段RESERVED_7
--20250331 chenbinbin HBCNRDQE-3524:调整dis_bank_id取数口径
--20241018 xiushuai HBCNRDQE-1346兜底逻辑添加
--****************************************

SET odps.sql.decimal.odps2=true;
INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)
--BDM取数逻辑
SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh, --金融许可证号
b.org_no AS nbjgh, --内部机构号
b.contract_no AS xdhth, --信贷合同号
b.lending_ref AS xdjjh, --信贷借据号
a.ccy_code AS bz, --币种
b.loan_amt AS dkje, --贷款金额
REPLACE(a.entd_paym_amt,"_","") As stzfje, --受托支付金额
REPLACE(a.entd_paym_dt,"_","") As stzfrq, --受托支付日期
CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)
ELSE a.entd_opp_acct_no
END As stzfdxzh, --受托支付对象账号
CASE WHEN a.CHARGE_DEPARTMENT ="GTRF_CoreTrade_SCSAI" THEN a.entd_opp_acct_name
WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_acct_name,f.df_dfhm)
WHEN a.charge_department = "OPS_MBS" THEN REGEXP_REPLACE( --有英文字符
trim(
REGEXP_REPLACE(CASE WHEN a.entd_opp_acct_name not RLIKE('[A-Za-z0-9]')
THEN replace(replace(replace(a.entd_opp_acct_name,'(',''),')',''),'-','')
ELSE a.entd_opp_acct_name
END, "[~!@#$%&{}><+/=?、《》\[\]]",'*')
)
, "[~!@#$%&{}><+/=?、《》\[\]]", '*')
ELSE TRIM(TRIM(a.entd_opp_acct_name))
END AS stzfdxhm, --受托支付对象户名
CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_no,f.df_dfxh)
ELSE a.entd_opp_bank_no END AS stzfdxhh, --受托支付对象行号
CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_name,f.df_dfxm)
ELSE trim(a.entd_opp_bank_name) END As stzfdxxm, --受托支付对象行名
CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark
WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY="WSB_GTRF_CoreTrade" AND A.ccy_code<>B.ccy_code THEN '融资放款币种："'||B.ccy_code
ELSE NULL
END AS BBZ, --备注
REPLACE("$(load_date)","-","") AS cjrq, --采集日期
'$(load_date)' AS dis_data_date, --系统字段
b.org_no As dis_bank_id, --系统字段
nvl(b.dis_bank_id,'CNHSBC900Z') As dis_bank_id, --20250331 chenbinbin HBCNRDQE-3524:调整dis_bank_id取数口径
NULL As gsfzjg, --归属分支机构
a.TAG_COUNTRY AS TAG_COUNTRY,
a.TAG_ENTITY AS TAG_ENTITY,
a.TAG_BRANCH AS TAG_BRANCH,
a.TAG_GBGF AS TAG_GBGF,
a.TAG_RESERVE AS TAG_RESERVE,
a.TAG_PRIMARY_ACCOUNTABLE_PARTY AS TAG_PRIMARY_ACCOUNTABLE_PARTY,
a.TAG_RESPONSIBLE_PARTY AS TAG_RESPONSIBLE_PARTY,
a.CHARGE_DEPARTMENT AS CHARGE_DEPARTMENT,
NULL As reserved_field1, --备用字段1
NULL As reserved_field2, --备用字段2
NULL As reserved_field3, --备用字段3
NULL AS RESERVED_1, --备用字段1
A.RESERVED_2 AS RESERVED_2, --备用字段2
NULL AS RESERVED_3, --备用字段3
--HBCNRDQE1346 S
A.RESERVED_4 AS RESERVED_4, --备用字段4 MCA使用原逻辑标记字段
--HBCNRDQE1346S-
NULL AS RESERVED_5, --备用字段5
A.Reserved_Field18 AS RESERVED_6, --备用字段6业务区分
CASE WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY ="WSB_GTRF_CoreTrade"
THEN (CASE WHEN A.Reserved_Field18 IN ('6.1:LOAN PRODUCT CODE ILAPTY=REPAY BADI','7.1-OTHER LOAN','7.2 EP_OAE_XOA')
THEN '内部字段-贷款发放日期：'||REPLACE(B.ISSUE_DT,"-","")||'：'||"内部字段-关联支付编号："||A.Reserved_Field17
WHEN A.Reserved_Field18="5:PRODUCT CODE ILAPTY=CIL/YCL且ILRREF(前3位）为：IBC/YCB"
THEN '内部字段-贷款发放日期：'||REPLACE(B.ISSUE_DT,'-','')||'：'||"内部字段-关联支付编号："
ELSE '内部字段-贷款发放日期：'||REPLACE(B.ISSUE_DT,'-','')||'：'||"内部字段-关联支付编号："
END)
ELSE NULL
END AS RESERVED_7, --备用字段7--贷款发放日期
CASE WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY ="WSB_GTRF_CoreTrade"
THEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY
ELSE NULL
END AS RESERVED_8, --备用字段8
CASE WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY ="WSB_GTRF_CoreTrade"
THEN (CASE WHEN A.Reserved_Field18='6.1:LOAN PRODUCT CODE ILAPTY=REPAY BADI'
THEN '内部字段-BADI保证金编号：'||A.Reserved_Field15
ELSE NULL
END)
ELSE NULL
END AS RESERVED_9, --备用字段9保证金比例编号
CASE WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY ="WSB_GTRF_CoreTrade"
THEN (CASE WHEN A.Reserved_Field18='6.1:LOAN PRODUCT CODE ILAPTY=REPAY BADI'
THEN A.Reserved_Field14
ELSE NULL
END)
ELSE NULL
END AS RESERVED_10, --备用字段10 --保证金金额
NULL AS RESERVED_11, --备用字段11
NULL AS RESERVED_12, --备用字段12
NULL AS RESERVED_13, --备用字段13
NULL AS RESERVED_14, --备用字段14
NULL AS RESERVED_15, --备用字段15
A.PRIMARY_SRC_SYSTEM AS PRIMARY_SRC_SYSTEM, --数据来源系统
NULL AS DQ_RESULT, --检验说明
a.CHARGE_DEPARTMENT AS COM_RESERVED_1, --备用字段1
NULL AS COM_RESERVED_2, --备用字段2
NULL AS COM_RESERVED_3, --备用字段3
NULL AS COM_RESERVED_4, --备用字段4
NULL AS COM_RESERVED_5, --备用字段5
NULL AS COM_RESERVED_6, --备用字段6
NVL_WS(a.DM_FLAG1,"NI") AS DM_FLAG1, --主数据脱敏标志
NULL AS DM_FLAG2, --非主数据脱敏标志
A.CHARGE_DEPARTMENT AS CHARGE_DEPARTMENT --归属部门20240807增加CHARGE_DEPARTMENT自动分区
FROM bdm_acc_entrusted_payment a --受托支付信息表
LEFT JOIN bdm_acc_loan_info b --贷款借据信息表
ON b.data_dt ='$(load_date)'
AND b.lending_ref = a.lending_ref
LEFT JOIN bdm_pub_branch c --机构信息表
ON c.data_dt ='$(load_date)'
AND b.org_no = c.org_no
LEFT JOIN bdm_pub_branch d --机构信息表
ON d.data_dt ='$(load_date)'
AND d.org_no = c.parent_vir_no

LEFT JOIN BDM_ACC_INTERNAL_COUNTERPARTY e
ON e.internal_key = a.Reserved_Field6
AND e.DATA_DT ='$(load_date)'
LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f
ON f.EAST_TRANS_SEQ_NO = a.Reserved_Field6
AND f.SJE_FUNCTION_SYS_CDE_17 IN ("1C5","1C6","1JB")

WHERE a.data_dt ='$(load_date)'
AND (b.loan_status <>'03'
OR (b.loan_status ="03" AND b.settle_dt BETWEEN DATETRUNC(DATE'$(load_date)',"mm") AND "$(load_date)"));



--新建部门分区
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='OPS_CDT');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_CoreTrade_EPBL_MYRZ');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_CoreTrade_IPBL');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_CoreTrade_LOAN');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_CoreTrade_SCSAI');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_GTE');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='OPS_MBS');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='WPB_RBB');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='GTRF_RFN');
ALTER TABLE east5_stzfxxb ADD IF NOT EXISTS PARTITION (P_DT='$(load_date)',charge_department='WPB_CDT_Digitallending');


--操作日志记录
INSERT INTO TABLE rrcdm_job_log_exec_par( data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks )
SELECT '$(load_date)' AS data_dt
,'ADS' AS object_domain
,"EAST5" AS sub_src_system
,'EAST5_STZFXXB' AS table_name
,'EAST5_STZFXXB_M' AS job_name
,COUNT(1) AS total_rows
,getdate() AS load_time
,'Y' AS STATUS
,NULL AS remarks
FROM EAST5_STZFXXB
WHERE p_dt = '$(load_date)'
;
