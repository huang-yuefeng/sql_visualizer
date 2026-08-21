--**所属主题：账户主题  [known-invalid OCR fragment at lines 770, 818: dangling AND predicates — not valid on a real engine]
--**功能描述：[贷款业务借据表]保理场景数据处理
--**目标表：[BDM_ACC_LOAN_INFO】【贷款业务借据表】
--**源表名：
--     ODS
--     [ODS_IFAI_FCLETWK]
--     [ODS_IFAI_IACLETWP] 删除依赖
--     [ODS_HUB_DDACMSP]
--     [ODS_HIE_EPACMSP]
--     [ODS_HUB_SSCUSTP]
--     [ODS_IFAI_IA_CUSTP]
--     [ODS_HUB_SSSTDPP]
--     [ODS_HUB_SS_CRGP]
--     [ODS_IFAI_IACLEAWP]
--     [ODS_HUB_SSSPINP]
--     [ods_ifai_foietwk] --20240301
--     [ods_ifai_iacurinp] -- 20250916 add by 160
--     [ODS_HUB_SSINRTP] --20250916 add by 160
--     中间表
--     [BDM_SYS_RFN_TZ_YE]
--     BDM
--     [BDM_PUB_BRANCH]
--     [BDM_PUB_HSBC_ACCT_BRANCH]
--     [BDM_CUS_CCUSTOMER]
--     [BDM_FIN_LRR_KEY_BASE_INFO]
--     [bdm_acc_deposit_acct]
--     [BDM_CUS_ADDRESS]
--     [BDM_ACC_WRITEOFF]
--     [BDM_CUS_ICUSTOMER] -- v_bdm_customer_ali视图依赖
--     [BDM_CUS_JOINTCUSTOMER] -- v_bdm_customer_ali视图依赖
--     [BDM_GDC_LABEL_FIN]
--     GDC手工表
--     [ods_cdp_gdc_label_fin] -- 20240229
--     [ods_gdc_split_fg_rating]
--     [ODS_GDC_RFN_RATE]
--     [ODS_GDC_RRCDM_BDM_ACC_ENTRUSTED_PAYMENT]
--     [ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS]
--     [ods_cdp_gdc_table_coa_list] --20240902
--     [ods_cdp_gdc_acct_migrate_to_diff_branches]
--     视图
--     [v_bdm_customer_ali]
--     [v_js_purpose_code] -- 15 add
--     静态表
--     [bdm_sys_bdm_acc_loan_info]
--**创建者：zhangjienan
--**创建时间：20230530
--**文件名：BDM_ACC_LOAN_INFO_RFN
--**修改日志：
--  修改日期        修改人        修改内容
--  yyyymmdd       name         comment
--  20230908       zhangjn      CR编号【EASTV-3292】
--  CR编号【EASTV-4146】
--  还款账号字段、还款账号所属行名
--  新增取值逻辑
--  贷款入账账号、贷款入账户名
--  新增兜底逻辑
--  20231109       CAOSHIYOU    修改ODS_IFAI_FCLETWK的取数范围
--  增加买方客户号逻辑：Reserved_Field13，Reserved_Field14
--  20231120       mayao        调整TAG_PRIMARY_ACCOUNTABLE_PARTY字段
--  20240115       mayao        调整tag_responsible_party字段 GTRF_RFN→WSB_GTRF_RFN
--  20240116       mayao        新增字段rec_creat_dt_tm，rec_updt_dt_tm，调整逻辑
--  调整字段dis_status_alias逻辑
--  20240125       mayao        调整到期日取数逻辑--1104需要用到--loan_ori_maturity_dt
--  20240202       mayao        接许飞扬需求，调整科目号取数逻辑
--  20240223       mayao        新增从手工表ods_gdc_split_fg_rating获取五级形态逻辑
--  20240229       mayao        调整科技贷款逻辑-ods_cdp_gdc_label_fin
--  20240407       mayao        占用Reserved_Field9字段，存放RFN的product_code字段
--  20240428       mayao        因原始ODS表ods_ifai_foietwk只有20240112及以后的数据，对于这一天特殊处理为全量跑批
--  20240430       sunhao       去除科技贷款field和value筛选条件
--  20240513       sunhao       增加脱敏字段逻辑
--  关联受托支付信息表更新放款方式逻辑
--  20240514       sunhao       新增DM_FLAG2字段逻辑
--  新增ODS_GDC_RFN_RATE，修改实际利率取值逻辑
--  20240515       sunhao       新增内部字段逻辑
--  20240625       sunhao       增加倒补逻辑
--  20240723       mayao        贷款借据表中RFN到期日的兜底逻辑需要调整为：如果到期日小于发放日，到期日是发放日加一天 HBCNRRCDM-765
--  20240726       sunhao       1104-FIN-G19补录字段接入问题&口径更新 HBCNRRCDM-771
--  20240815       sunhao       调整投向行业字段逻辑 HBCNRRCDM-781
--  20240902       sunhao       科目取数由（'1051114001'）调整为从ods_cdp_gdc_table_coa_list取数 HBCNRDQE-1505
--  20240919       sunhao       调整贷款原始到期日期逻辑（借据实际抓取日期在发放日期之后的）HBCNRRCDM-788
--  20240924       sunhao       调整贷款原始到期日期逻辑（Normal CLA）HBCNRDQE-2473
--  20241010       sunhao       到期日期优先取静态表数据 HBCNRDQE-2552
--  20241219       sunhao       蛇口支行需求，按ods_cdp_gdc_acct_migrate_to_diff_branches中包含客户调整对应客户的机构信息 HBCNRDQE-2738
--  20250310       sunhao       调整总行机构号取值范围，1.F.IGJXA<>520调整为F.IGJXA NOT IN（520，900）
--  2.F.IGJXA=520 AND F.IGJYA='N'调整为F.IGJXA IN（520,900）AND F.IGJYA='N' HBCNRDQE-3470
--  贷款到期日期逻辑调整 HBCNRDQE-2837
--  20250318       chenbinbin   HBCNRDQE-3524:dis_bank_id添加兜底：空值为'CNHSBC900Z'
--  20250327       chenbinbin   HBCNRDQE-3524:dis_bank_id添加兜底：空值为'CNHSBC900Z'
--  20250328       luowei       调整蛇口关联逻辑
--  20250604       chenbinbin   处理loan_purpose，loan_purpose_onoff_flag
--  20250615       sunhao       备用字段Reserved_Field11新增purpose code逻辑 modify 15e HBCNRDQE-3588
--  20250725       sunhao       去除loan_purpose字段，调整loan_purpose_indu字段逻辑 modify 15e HBCNRDQE-404 HBCNRDQE-4157
--  20250806       louyongliang HBCNRDQE-3951调整loan_ori_maturity_dt贷款原始到期日期字段逻辑
--  20250916       sunhao       1.新增base_rate基准利率字段逻辑 addby 150
--  2.启用备用字段Reserved_Field15接入150产品类别逻辑 addby 150
--  20251104       louyongliang 1.与业务老师沟通，在RFN宽限期逻辑中用到的IGNDA字段不再直取，仅截取该字段前四位使用
--  2.修改宽限期兜底逻辑顺序，从加宽限日期前移动到加宽限日期后，若加完宽限期后的日期仍早于发放日期，则将发放日期+1作为原始到期日
--**备注：
set odps.sql.decimal.odps2=true;
WITH ods_gdc_split_fg_rating_temp AS (--五级形态
SELECT 'CNHSBC'||REPLACE(borrower_ids,'-','') AS cust_no
,DECODE(SUBSTR(cbirc_fg,1,1)
,'1','01'
,'2','02'
,'3','03'
,'4','04'
,'5','05'
) AS grade
,ROW_NUMBER() OVER(PARTITION BY REPLACE(borrower_ids,'_','') ORDER BY p_dt DESC) AS rn -- [OCR-UNCERTAIN: replace char '_' vs '-' ambiguous]
FROM ods_gdc_split_fg_rating m
WHERE m.p_dt = (SELECT MAX(n.P_DT) FROM ods_gdc_split_fg_rating n WHERE n.P_DT <= TO_DATE(LASTDAY(TO_DATE('$(load_date)','yyy-mm-dd'))))
),
TEMP_RFN AS (
SELECT DISTINCT *
FROM BDM_SYS_RFN_TZ_YE TZ
JOIN ODS_IFAI_FCLETWK F
ON TZ.CLA = LPAD(F.IFZRMA,5,'0')
AND F.P_DT='$(load_date)'
WHERE
(TZ.JYYE <> 0 AND CJRQ = REPLACE('$(load_date)','-',''))
OR (TZ.JYYE = 0 AND SUBSTR(TZ.dqrq, 1, 6) = SUBSTR(REPLACE('$(load_date)','-',''), 1, 6))
AND (F.IGJXA <> 520 OR (F.IGJXA = 520 AND F.IGJYA ='N'))
AND (F.IGJXA NOT IN(520,900) OR (F.IGJXA IN(520,900) AND F.IGJYA='N'))
AND TZ.DATA_DT='$(load_date)'
),
--1.1 Bulk booking CLA 20250318 luowei 贷款到期日期逻辑调整HBCNRDQE-2837
--抓取CLA<IFZRMA>下最晚一张发票日<FOIETWKHSK.IFX13A>+paymentterm（天数）<FCLETWK.IGNBA右取4位>
temp_dqrq_bulk AS (--20250806(HBCNRDQE-3951)
SELECT a.ifzrma AS ACCT_NO
,CONCAT('20',SUBSTR(a.IFX13A,2,6)) --FOIETWKHSK.IFX13A
,SUBSTR(b.IGNBA,-4) --FCLETWK.IGNBA右取4位
,CAST(SUBSTR(b.IGNBA,-4) AS BIGINT)
,MAX(TO_CHAR(
DATEADD(TO_DATE(CONCAT('20',SUBSTR(a.IFX13A,2,6)),'YYYYMMDD')
,CAST(SUBSTR(b.IGNBA,5,4) AS BIGINT)
,'dd')
,'YYYY-MM-DD')) dqrq_bulk
FROM ods_ifai_foietwk a
LEFT JOIN ODS_IFAI_FCLETWK b
ON a.ifzrma = b.ifzrma
AND b.p_dt = '$(load_date)'
WHERE a.p_dt ='$(load_date)'
AND NVL(a.IFXONA,'0') ='0'
AND NVL(a.IFX13A,'')<>'' --IFX13A有值，IFXONA字段为空则代表为Bulk booking CLA
GROUP BY a.ifzrma
),
--1.1 Product code <FCLETWK.IGNOA>第4位 <>L(non-leasing)
--a.抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票到期日期<FOIETWKHSK.IFXONA-IFCTDueDate>;
--b.如果最晚一张发票到期日期为空值，抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票开票日<FOIETWKHSK.IFX13A-IFCTDocumentDate>+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>；
temp_dqrq_normal_01 AS (
SELECT ACCT_NO
,to_char(to_date(NVL(dqrq_a,dqrq_b),'YYYYMMDD'),'YYYY-MM-DD') AS dqrq_normal
FROM (
SELECT a.ifzrma AS ACCT_NO
,MAX(CONCAT('20',SUBSTR(a.IFXONA,2,6))) AS dqrq_a --最晚一张发票到期日期<FOIETWKHSK.IFXONA>
,MAX(TO_CHAR(DATEADD(TO_DATE(CONCAT('20',SUBSTR(a.IFX13A,2,6)),'YYYYMMDD'),CAST(SUBSTR(b.IGNBA,5,4) AS BIGINT),'dd'),'YYYYMMDD')) AS dqrq_b --最晚一张发票开票日<FOIETWKHSK.IFX13A>+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>
FROM ods_ifai_foietwk a
LEFT JOIN ODS_IFAI_FCLETWK b
ON a.ifzrma = b.ifzrma
AND b.p_dt = '$(load_date)'
WHERE a.p_dt = '$(load_date)'
AND NVL(a.IFXONA,'') <>''
AND NVL(a.IFX13A,'')<>'' --IFX13A有值，IFXONA有值则代表为Normal CLA
AND SUBSTR(b.IGNOA,4,1)<>'L'
GROUP BY a.ifzrma
) t
WHERE 1=1
),
--2.1 Product code <FCLETWK.IGNOA>第4位=L(leasing)
--a.优先抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票到期日期<FOIETWKHSK.IFXONA>；
--b.如果最晚一张发票到期日期为空值，抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票开票日<FOIETWKHSK.IFX13A>+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>；
--2.2放款日期issuedate+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>
--比较2.1和2.2，取较短的日期为到期日
--2.3如果最晚一张发票开票日仍为空值，则定义为利息和费用，直接取3个月后的最后一天，不用做2.2和相应比较
temp_dqrq_normal_02 AS (
SELECT dkjjbm
,to_char(to_date(least(NVL(dqrq_a,dqrq_b),TO_CHAR(DATEADD(TO_DATE(c.ffrq,'YYYYMMDD'),CAST(SUBSTR(b.IGNBA,5,4) AS BIGINT),'dd'),'YYYYMMDD')),'YYYYMMDD'),'YYYY-MM-DD')
AS dqrq_normal
FROM TEMP_RFN c
LEFT JOIN (
SELECT a.ifzrma AS ACCT_NO
,MAX(CONCAT('20',SUBSTR(a.IFXONA,2,6))) AS dqrq_a --最晚一张发票到期日期<FOIETWKHSK.IFXONA>
,MAX(TO_CHAR(DATEADD(TO_DATE(CONCAT('20',SUBSTR(a.IFX13A,2,6)),'YYYYMMDD'),CAST(SUBSTR(b.IGNBA,5,4) AS BIGINT),'dd'),'YYYYMMDD')) AS dqrq_b --最晚一张发票开票日<FOIETWKHSK.IFX13A>+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>
FROM ods_ifai_foietwk a
LEFT JOIN ODS_IFAI_FCLETWK b
ON a.ifzrma = b.ifzrma
AND b.p_dt ='$(load_date)'
AND a.p_dt = '$(load_date)'
WHERE NVL(a.IFXONA,'0') <>'0'
AND NVL(a.IFX13A,'0')<>'0' --IFX13A有值，IFXONA有值则代表为Normal CLA
GROUP BY a.ifzrma
) t
ON SUBSTR(c.dkjjbm,4,5) = LPAD(t.acct_no,5,'0')
LEFT JOIN ODS_IFAI_FCLETWK b
ON t.acct_no = b.ifzrma
AND b.p_dt = '$(load_date)'
WHERE SUBSTR(b.IGNOA,4,1) ='L'
),
TEMP_03 AS (
SELECT DISTINCT A.IFZRMA
,A.IGNOA
,A.IGMRA
,CASE WHEN SUBSTR(A.IGNOA, 3,1)='P' THEN (CASE WHEN SUBSTR(A.IGMRA,16,3)='180' THEN CONCAT('CNHSBC',LPAD(E.BADCB,3,'0'),LPAD(E.BADCS,6,'0'))
ELSE CONCAT('CNHSBC',LPAD(D.DFDCB,3,'0'),LPAD(D.DFDCS,6,'0'))
END)
ELSE NULL
END AS KHTYBH_BUYER
,CASE WHEN SUBSTR(A.IGNOA,3,1)='P' THEN 'Y'
ELSE 'N'
END AS KHTYBH_BUYER_BJ
FROM ODS_IFAI_FCLETWK A
LEFT JOIN ODS_HUB_DDACMSP D
ON D.DFCTCD = SUBSTR(A.IGMRA,1,2)
AND D.DFGMAB = SUBSTR(A.IGMRA,3,4)
AND D.DFACB = SUBSTR(A.IGMRA,7,3)
AND D.DFACS = SUBSTR(A.IGMRA,10,6)
AND D.DFACX = SUBSTR(A.IGMRA,16, 3)
AND D.P_DT = '$(load_date)'
JOIN ODS_HIE_EPACMSP E
ON E.BACTCD = SUBSTR(A.IGMRA,1,2)
AND E.BAGMAB = SUBSTR(A.IGMRA,3,4)
AND E.BAACB = SUBSTR(A.IGMRA,7,3)
AND E.BAACS = SUBSTR(A.IGMRA,10,6)
AND E.BAACX = SUBSTR(A.IGMRA,16, 3)
AND E.P_DT ='$(load_date)'
WHERE A.P_DT = '$(load_date)'
),
TEMP_TXHY AS (
SELECT P1.ZGCTCD,P1.ZGDCG,P1.ZGDCB,P1.ZGDCS,P1._COFSH
,CASE WHEN P1._COFSH ='F' THEN 'Z'
WHEN P1._COFSH ='0' THEN (CASE WHEN LENGTH(P1.TXHY) = 4 THEN SUBSTR(P2.YHDS50,50,1)||P1.TXHY
ELSE P1.TXHY
END)
END AS TXHY
,CASE WHEN LENGTH(P1.TXHY) = 4 THEN SUBSTR(P2.YHDS50,50,1)||P1.TXHY -- [OCR-UNCERTAIN: second AS TXHY alias may be a different alias]
ELSE P1.TXHY
END AS TXHY
FROM (
SELECT A.ZGCTCD,A.ZGDCG,A.ZGDCB,A.ZGDCS,NVL(B._COFSH,'0') AS _COFSH
,NVL(B._CRAPC,A.ZGINDY) AS TXHY
FROM ODS_HUB_SSCUSTP A
LEFT JOIN ODS_IFAI_IA_CUSTP B
ON A.ZGCTCD = B._CCTCD
AND A.ZGDCG = B._CDCG
AND A.ZGDCB = B._CDCB
AND A.ZGDCS = B._CDCS
AND A.P_DT = B.P_DT
WHERE A.P_DT = '$(load_date)'
) P1
LEFT JOIN ODS_HUB_SSSTDPP P2
ON P2.YHCODE = P1.TXHY
AND P2.YHTBID = 'Y1' -- [OCR-UNCERTAIN: 'YI'→'Y1'?]
AND P2.P_DT ='$(load_date)'
),
TEMP_HKXX AS (
SELECT B.DFDCS,B.DFDCB,B.DFGMAB,B.DFCTCD,B.DFCYCD,
CONCAT(A.YGCTCD,A.YGGMAB,LPAD(A.YGACB, 3,'0'),LPAD(A.YGACS,6,'0'),LPAD(A.YGACX, 3,'0')) AS HKZH
,COUNT(1) OVER(PARTITION BY B.DFDCS,B.DFDCB,B.DFGMAB,B.DFCTCD,B.DFCYCD) AS COUNT_NUMBER
FROM ODS_HUB_SSSPINP A
,ODS_HUB_DDACMSP B
WHERE B.DFACB = A.YGACB
AND B.DFACS = A.YGACS
AND YGNAR1 LIKE '%RFN%'
AND B.DFACX = A.YGACX
AND A.P_DT = B.P_DT
AND A.P_DT = '$(load_date)'
),
TEMP_JGXX AS (
SELECT DISTINCT B.BRANCH_CODE,A.ORG_NO,A.ORG_NAME FROM BDM_PUB_BRANCH A,BDM_PUB_HSBC_ACCT_BRANCH B
WHERE A.DATA_DT = B.DATA_DT
AND A.ORG_NO = B.ORG_NO
AND A.DATA_DT = '$(load_date)'
),
TEMP_ZCHX AS (
SELECT A.BUSI_NO,CASE WHEN COUNT(1)>0 THEN 'Y' ELSE 'N' END AS ZCHXBZ FROM BDM_ACC_WRITEOFF A
WHERE A.DATA_DT ='$(load_date)'
GROUP BY A.BUSI_NO
),
temp_1104_G19 AS (
SELECT vlookup_key_value AS lending_ref
,t.field AS bdm_table_field
,t.value AS value
,data_producer AS charge_department
FROM BDM_GDC_LABEL_FIN t
WHERE t.DATA_DT = '$(load_date)'
AND t.1104_report = 'G19'
AND t.field IN ('LOAN_PURPOSE_SNI','LOAN_PURPOSE_CUL','LOAN_PURPOSE_IND_UPDATE_FLAG')
AND t.vlookup_key ='LENDING_REF'
),
TEMP_BDM_ACC_LOAN_INFO_1 AS (
SELECT P1.DKJJBM AS LENDING_REF --借据编号
,NULL AS PCB_ACCT_NO --账户标识码
,NULL AS APPLY_NO --申请号
,P1.XDHTH AS LIMIT_NO --额度编号
,P1.XDHTH AS CONTRACT_NO --合同号
,NULL AS ORG_NO --机构号
,(CASE -- [OCR-UNCERTAIN: open paren assumed to balance closing ')']
WHEN LENGTH(P1.IGJXA)>3 THEN CONCAT('CNHSBC',LPAD(SUBSTR(P1.IGJXA,-3),3,'0'))
ELSE CONCAT('CNHSBC',LPAD(P1.IGJXA,3,'0'))
END) AS BRANCH_CODE --内部核算机构号
,SUBSTR(P1.XDHTH,1,15) AS CUST_NO --客户号
,NULL AS ITEM_CODE --科目号
,NULL AS LRR_KEY_ITEM_CODE --LRRKey科目号
,'A15000' AS HUB_ITEM_CODE --HUB科目号 -- [OCR-UNCERTAIN: HUB_ITEM_CODE CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value 'A15000']
,NULL AS NOMINAL_ACC --COA科目
,NULL AS FTP_PRODUCT_CODE --FTP产品编码
,'03' AS BUSINESS_TYPE --信贷业务种类
,P1.DKJJBM AS ACCT_NO --信贷分户账账号
,NULL AS BILL_NO --票据号码
,'A09' AS FUND_SOURCE --贷款资金来源
,'A01' AS SIGN_CHANNEL --贷款签约渠道
,'01' AS LOAN_ORIGI_TYPE --贷款发放类型
,NULL AS SRC_LOAN_ORIGI_TYPE --源系统贷款发放类型
,'1' AS PAY_MODE --放款方式
,NULL AS SRC_PAY_MODE --源系统放款方式
,P1.BZ AS CCY_CODE --币种
,P1.FFJE AS LOAN_AMT --放款金额
,P1.JYYE AS LOAN_BAL --本金余额
,NULL AS RESERVE --减值准备
,NULL AS LOAN_GRADE --五级分类 -- [OCR-UNCERTAIN: code for line with '五级分类' comment not captured]
,P1.FFRQ AS ISSUE_DT --贷款发放日期
,P1.FFRQ AS SRC_ISSUE_DT --源系统贷款发放日期
,P1.DQRQ AS LOAN_ORI_MATURITY_DT --贷款原始到期日期
,P1.DQRQ AS LOAN_MATURITY_DT --贷款最新到期日期 -- [OCR-UNCERTAIN: LOAN_MATURITY_DT CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value P1.DQRQ]
,P1.DQRQ AS SETTLE_DT --实际终止日期
,CASE WHEN SUBSTR(P1.IGNBA,1,3) IN ('LPe','ZBR') THEN 'F'
ELSE 'L'
END AS RATE_FLOAT_TYPE --利率类型
,'1' AS RATE_FLOAT_FREQ --利率浮动频率
,NULL AS BASE_RATE_TYPE --基准利率类型 -- [OCR-UNCERTAIN: BASE_RATE_TYPE CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value NULL]
,P8.X5INR1 AS BASE_RATE --基准利率
,P4.IGNOA AS ACTUAL_RATE --实际利率
,P1.DQRQ AS NEXT_RATE_CHANGE_DT --下一贷款利率重新定价日
,'99' AS PRI_PAY_METHOD --还本频率
,'按应收账款账期还款' AS SRC_PRI_PAY_METHOD --源系统还本频率
,'03' AS INT_PAY_METHOD --还息频率
,NULL AS SRC_INT_PAY_METHOD --源系统还息频率
,P1.BZ AS INT_CCY_CODE --利息币种
,'0' AS INTEREST --应收利息
,P1.IGJQA AS LOAN_IN_ACCT_NO --贷款入账账号
,NULL AS LOAN_IN_ACCT_NAME --贷款入账户名
,NULL AS LOAN_IN_BANK_NO --贷款入账行号 -- [OCR-UNCERTAIN: LOAN_IN_BANK_NO CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value NULL]
,NULL AS LOAN_IN_BANK_NAME --贷款入账行名
,'1' AS TOTAL_PERIOD --总期数
,'1' AS CURR_PERIOD --当前期数
,'9999-12-31' AS NEXT_PAY_DATE --下期还款日期
,'' AS NEXT_PAY_NOMINAL --下期应还本金
,'0' AS NEXT_PAY_RATE --下期应还利息
,'' AS DEBT_PERIOD --连续欠款期数
,'' AS TOTAL_DEBT_PERIOD --累计欠款期数
,'99' AS REPAY_MODE --还款方式
,'按应收账款账期还款' AS SRC_REPAY_MODE --源系统还款方式
,P5.HKZH AS REPAY_ACCT_NO --还款账号
,NULL AS REPAY_BANK_NO --还款账号所属行号
,NULL AS REPAY_BANK_NAME --还款账号所属行名
,NULL AS LOAN_PURPOSE_COUNTRY_CODE --贷款投向国家
,NULL AS LOAN_PURPOSE_DIST --贷款投向地区
,P6.TXHY AS LOAN_PURPOSE_INDU --投向行业
,NULL AS LOAN_PURPOSE_SNI --投向战略性新兴产业分类
,NULL AS LOAN_PURPOSE_CUL --投向文化及相关产业分类
,NULL AS LOAN_PURPOSE_IND_UPDATE_FLAG --是否投向工业企业技术改造升级项目
,'应收账款' AS PURPOSE --贷款用途
,NULL AS ABROAD_LOAN_PURPOSE --境外贷款资金用途
,'N' AS SYNDICATED_LOAN_FLAG --是否银团贷款
,'N' AS IS_OUTSHEET --贷款是否出表
,CASE WHEN P1.JYYE <> 0 THEN '01' ELSE '03' END AS LOAN_STATUS --贷款状态
,NULL AS SRC_STATUS --源系统贷款状态
,NULL AS COLLECTION --催收标志
,NULL AS COLLECTION_TYPE --催收方式
,NULL AS SETTLE_MODE --贷款终结方式
,NULL AS SRC_SETTLE_MODE --源系统贷款终结方式
,NULL AS CREDITOR_NO --客户经理工号
,NULL AS PRIN_OD_DT --本金逾期日期
,'' AS PRIN_OD_AMT --欠本金额
,NULL AS INT_OD_DT --利息逾期日期
,'' AS INT_OD_AMT --表内欠息余额
,'' AS INTEREST_BALANCE2 --表外欠息余额
,'' AS PENALTYINT_AMT --罚息金额
,NULL AS COMPOUNDINT_AMT --逾期复利金额
,NULL AS MITIGATE --减免金额
,'0' AS EXTRA_FEE --其他费用金额
,NULL AS CURR_NON_TRADING_ADJ_AMT --本月非交易变动
,NULL AS CAPTIAL_RATIO --出资比例
,NULL AS COOPER_NAME --合作机构名称
,NULL AS INT_SUBSIDY --贷款财政扶持方式
,NULL AS SRC_INT_SUBSIDY --源系统贷款财政扶持方式
,NULL AS INDUSTRI_STRUCT_TYPE --产业结构调整类型
,NULL AS UPGRADE_FLAG --工业转型升级标识
,'N' AS IS_INTERNET_LOAN --是否互联网贷款
,'N' AS IS_TECHNOLOGY_LOAN --是否科技贷款
,'N' AS IS_GREENLOAN --是否绿色贷款
,NULL AS GREENLOAN_TYPE --绿色贷款用途
,NULL AS IS_GREEN_TRANSFINA --是否绿色贸易融资
,NULL AS GREEN_TRANSFINA_TYPE --绿色贸易融资用途
,NULL AS IS_GREEN_CONSUME --是否绿色消费融资
,NULL AS GREEN_CONSUME_TYPE --绿色消费融资用途
,NULL AS IS_VTR_GTR --是否创业担保贷款
,NULL AS FIRST_LOAN_FLG --是否首次贷款
,NULL AS IS_FARMERS_INSUR --是否农户联保
,NULL AS OTHRE_PY_GUARWAY --其他还款保证方式
,NULL AS VTR_GTR_TYPE --创业担保贷款类型
,NULL AS SRC_VTR_GTR_TYPE --源系统创业担保贷款类型
,NULL AS ENVSAFE_ENPR_LOAN --环境及安全等重大风险企业贷款
,'N' AS IS_AGRIC_LOAN --是否涉农贷款
,'N' AS IS_PRATTWHITNEY_LOAN --是否普惠型贷款
,NULL AS PGUPER_AMT --购汇履约金额
,NULL AS EXT_DEBT_NO --外债编号
,NULL AS LOAN_EX_GU_NO --外保内贷编号
,NULL AS CFEO_GUD_APPROVAL_NO --外保内贷批准文件号
,NULL AS CFEO_GUD_APPROVAL_CCY_CODE --外保内贷批准额度币种
,NULL AS CFEO_GUD_APPROVAL_AMT --外保内贷批准额度金额
,NULL AS BAD_LOAN_RELEASE_TYPE --不良贷款风险分担方式
,NULL AS SRC_BAD_LOAN_RELEASE_TYPE --源系统不良贷款风险分担方式
,'N' AS IS_COVERED_ASSET --是否被抵押或担保
,NULL AS COLL_RES_MATURITY --担保品剩余期限
,NULL AS OVERDUE_TYPE --逾期分类
,NULL AS USEOFUNDS_TYPE --外汇资金用途
,NULL AS REMARK --备注
,'HUB' AS SYS_SRC_CODE --源系统代码
,LPAD(p1.IFZRMA,9,'0') AS FTP_KEY --FTP ALN
,P2.KHTYBH_BUYER --买方-客户统一编号
,P2.KHTYBH_BUYER_BJ --买方-客户统一编号--标记
,P1.IGNOA
,P1.IGNDA --20250806(HBCNRDQE-3951)
,P1.IGJYA --20250806(HBCNRDQE-3951)
,P1.IGNBA --20250806(HBCNRDQE-3951)
,CASE WHEN SUBSTR(P1.IGNOA,4,1)='0' AND P1.IFX2AA <>'99' THEN 'F081'
WHEN SUBSTR(P1.IGNOA,4,1)='0' AND P1.IFX2AA ='99' AND TO_CHAR(P1.IGJXA) NOT LIKE '5%' THEN 'F082'
WHEN SUBSTR(P1.IGNOA,4,1) IN ('E','0','T','X','I') THEN 'F081'
ELSE 'F082'
END DKCPLB
FROM TEMP_RFN P1
LEFT JOIN TEMP_03 P2
ON P1.IFZRMA = P2.IFZRMA
AND P1.IGNOA = P2.IGNOA
AND P1.IGMRA = P2.IGMRA
LEFT JOIN ODS_HUB_SS_CRGP P3
ON P3.C_CTCD = SUBSTR(SUBSTR(P1.XDHTH,1,15), 1, 2)
AND P3.C_DCG = SUBSTR(SUBSTR(P1.XDHTH,1,15), 3, 4)
AND P3.C_DCB = SUBSTR(SUBSTR(P1.XDHTH,1,15),7,3)
AND P3.C_DCS = SUBSTR(SUBSTR(P1.XDHTH,1,15),10,6)
AND P3.P_DT ='$(load_date)'
LEFT JOIN ODS_IFAI_IACLEAWP P4
ON P1.IFZRMA = P4.IFZRMA
AND P4.P_DT = '$(load_date)'
LEFT JOIN TEMP_HKXX P5
ON DFCYCD = P1.BZ
AND DFCTCD = SUBSTR(SUBSTR(P1.XDHTH,1,15), 1, 2)
AND DFGMAB = SUBSTR(SUBSTR(P1.XDHTH,1,15), 3, 4)
AND DFDCB = SUBSTR(SUBSTR(P1.XDHTH,1,15), 7, 3)
AND DFDCS = SUBSTR(SUBSTR(P1.XDHTH,1,15),10, 6)
AND COUNT_NUMBER ='1'
LEFT JOIN TEMP_TXHY P6
ON P6.ZGCTCD = SUBSTR(SUBSTR(P1.XDHTH,1,15), 1, 2)
AND P6.ZGDCG = SUBSTR(SUBSTR(P1.XDHTH,1,15), 3, 4)
AND P6.ZGDCB = SUBSTR(SUBSTR(P1.XDHTH,1,15),7,3)
AND P6.ZGDCS = SUBSTR(SUBSTR(P1.XDHTH,1,15),10,6)
--addby150新增基准利率逻辑
LEFT JOIN ods_ifai_iacurinp p7
ON p7.iacrco = p1.ifx2aa
AND p7.p_dt ='$(load_date)'
LEFT JOIN (
SELECT X5CTCD
,X5GMAB
,X5CYCD
,X5RTTY
,X5TERM
,X5STDT
,X5ENDT
,CASE WHEN X5INR1 < 0 THEN 0
ELSE X5INR1
END X5INR1
,ROW_NUMBER() OVER(PARTITION BY X5CTCD,X5GMAB,X5CYCD,X5RTTY,X5TERM ORDER BY X5STDT DESC) AS NUM
FROM ODS_HUB_SSINRTP
WHERE p_dt ='$(load_date)'
) p8
ON p8.X5CTCD = 'CN'
AND p8.X5GMAB ='HSBC'
AND p8.X5CYCD = p7.IACYCD
AND p8.X5RTTY = SUBSTR(P1.IGNBA,1,3)
AND REPLACE(p8.X5TERM,' ','') = REPLACE(P1.X5TERM,' ','') -- [OCR-UNCERTAIN: RHS of REPLACE comparison not captured; reconstructed as REPLACE(P1.X5TERM,' ','') matching the p8.X5RTTY=SUBSTR(P1.IGNBA,1,3) term-code pattern]
AND p8.NUM = 1
),
TEMP_BDM_ACC_LOAN_INFO_02 AS (
SELECT DISTINCT P1.LENDING_REF AS LENDING_REF --借据编号
,P1.PCB_ACCT_NO AS PCB_ACCT_NO --账户标识码
,P1.APPLY_NO AS APPLY_NO --申请号
,P1.LIMIT_NO AS LIMIT_NO --额度编号
,P1.CONTRACT_NO AS CONTRACT_NO --合同号
,P3.ORG_NO AS ORG_NO --机构号
,P1.BRANCH_CODE AS BRANCH_CODE --内部核算机构号
,P1.CUST_NO AS CUST_NO --客户号
,KM.cb_pointer AS ITEM_CODE --科目号
,KM.lrr_key AS LRR_KEY_ITEM_CODE --LRRKey科目号
,P1.HUB_ITEM_CODE AS HUB_ITEM_CODE --HUB科目号
,KM.account AS NOMINAL_ACC --COA科目
,KM.product AS FTP_PRODUCT_CODE --FTP产品编码
,P1.BUSINESS_TYPE AS BUSINESS_TYPE --信贷业务种类
,P1.ACCT_NO AS ACCT_NO --信贷分户账账号
,P1.BILL_NO AS BILL_NO --票据号码
,P1.FUND_SOURCE AS FUND_SOURCE --贷款资金来源
,P1.SIGN_CHANNEL AS SIGN_CHANNEL --贷款签约渠道
,P1.LOAN_ORIGI_TYPE AS LOAN_ORIGI_TYPE --贷款发放类型
,P1.SRC_LOAN_ORIGI_TYPE AS SRC_LOAN_ORIGI_TYPE --源系统贷款发放类型
,CASE WHEN NVL(stzf.lending_ref,'')<>'' THEN '2' ELSE P1.PAY_MODE END AS PAY_MODE --放款方式
,P1.SRC_PAY_MODE AS SRC_PAY_MODE --源系统放款方式
,P1.CCY_CODE AS CCY_CODE --币种
,P1.LOAN_AMT AS LOAN_AMT --放款金额
,P1.LOAN_BAL AS LOAN_BAL --本金余额
,P1.RESERVE AS RESERVE --减值准备
,NVL(gdc_wjf1.grade,NVL(P1.LOAN_GRADE,P5.LOAN_GRADE)) AS LOAN_GRADE --五级分类
,TO_CHAR(TO_DATE(P1.ISSUE_DT,'YYYYMMDD'),'YYYY-MM-DD') AS ACCT_OPEN_DT --信贷账户开户日期
,TO_CHAR(TO_DATE(P1.SRC_ISSUE_DT,'YYYYMMDD'),'YYYY-MM-DD') AS SRC_ACCT_OPEN_DT --源系统开户日期
,TO_CHAR(TO_DATE(P1.ISSUE_DT,'YYYYMMDD'),'YYYY-MM-DD') AS ISSUE_DT --贷款发放日期
,TO_CHAR(TO_DATE(P1.SRC_ISSUE_DT,'YYYYMMDD'),'YYYY-MM-DD') AS SRC_ISSUE_DT --源系统贷款发放日期
,CASE --202401251104的到期日逻辑加工
WHEN NVL(P20.LOAN_ORI_MATURITY_DT,'')<>'' THEN P20.LOAN_ORI_MATURITY_DT --20241019优先取静态表到期日期
WHEN P1.LENDING_REF='RFN206192022031800001' THEN '2025-03-17'
WHEN P1.LENDING_REF='RFN208892022030200001' THEN '2026-12-20'
WHEN P1.LENDING_REF='RFN210162022031800001' THEN '2026-06-20'
WHEN P1.LENDING_REF='RFN211122022022200001' THEN '2024-10-12'
WHEN P1.LENDING_REF='RFN2107512024012600002' THEN '2025-11-30' -- [OCR-UNCERTAIN: LENDING_REF digits]
WHEN P1.LENDING_REF='RFN2124712024012600002' THEN '2025-01-27' -- [OCR-UNCERTAIN: LENDING_REF digits]
--因历史遗留问题以及系统录入问题，对六笔借据特殊处理
WHEN P1.LENDING_REF='RFN20619112024043000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023063000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023073100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023083100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023093000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023103100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023113000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112023123100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112024013100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112024022900001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112024033100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20889112024043000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20896112024033100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20896112024043000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20920112024013100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20920112024022900001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20920112024033100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN20920112024043000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21016112024043000001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21112112024022900001' THEN '2024-10-31'
WHEN P1.LENDING_REF='RFN21112112024033100001' THEN '2024-10-31'
WHEN P1.LENDING_REF='RFN21112112024043000001' THEN '2024-10-31'
WHEN P1.LENDING_REF='RFN21112112024053100001' THEN '2024-10-31'
WHEN P1.LENDING_REF='RFN21112112024063000001' THEN '2024-10-31'
WHEN P1.LENDING_REF='RFN21189112023123100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21189112024013100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21189112024022900001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21189112024033100001' THEN '2024-12-31'
WHEN P1.LENDING_REF='RFN21189112024043000001' THEN '2024-12-31'
--首次发放+交易类型：利息/服务费（借据号最后数字为1)
WHEN SUBSTR(P1.LENDING_REF,-1) = '1'
THEN CASE WHEN SUBSTR(P1.IGNOA,-1) IN ('L') THEN LAST_DAY(DATEADD(DATE('$(load_date)'),3,'mm')) --取T+3月最后一天
WHEN SUBSTR(P1.IGNOA,-1) NOT IN ('L') THEN LAST_DAY(DATEADD(DATE('$(load_date)'),1,'mm')) --取次月最后一天
END --20250806(HBCNRDQE-3951)
--HBCNRDQE-3951:
--1.1 Product code <FCLETWK.IGNOA>第4位<>L (non-leasing)
--a.抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票到期日期<FOIETWKHSK.IFXONA-IFCTDueDate>;
--如果最晚一张发票开票日仍为空值，则定义为利息和费用，直接取报送月份次月最后一天。
--2.1 Product code <FCLETWK.IGNOA>第4位=L(leasing)
--b.如果最晚一张发票到期日期为空值，抓取<FCLETWK.IFZRMA=CLIENTNUMBER>下最晚一张发票开票日<FOIETWKHSK.IFX13A>+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>；
--2.2放款日期issuedate+paymentterm（天数）<FCLETWK.IGNBA－中间第5位起开始取4位>
--比较2.1和2.2，取较短的日期为到期日
--2.3如果最晚一张发票开票日仍为空值，则定义为利息和费用，直接取3个月后的最后一天，不用做2.2和相应比较
--首次发放+交易类型：融资发放（借据号最后数字为2)
WHEN SUBSTR(P1.LENDING_REF,-1) = '2'
THEN CASE WHEN SUBSTR(P1.IGNOA,-1) IN ('L') AND NVL(p19.dqrq_normal,'')<>'' THEN LEAST(CAST(DATE(p19.dqrq_normal) AS STRING),CAST(DATEADD(DATE(TO_DATE(p1.issue_dt,'YYYYMMDD')),CAST(SUBSTR(p1.IGNBA,5,4) AS BIGINT),'dd') AS STRING))
WHEN SUBSTR(P1.IGNOA,-1) IN ('L') AND NVL(p19.dqrq_normal,'')='' THEN LAST_DAY(DATEADD(DATE('$(load_date)'),1,'mm')) -- [OCR-UNCERTAIN: exact WHEN condition for this branch]
WHEN SUBSTR(P1.IGNOA,-1) NOT IN ('L') AND NVL(p14.dqrq_normal,'')<>'' THEN p14.dqrq_normal
WHEN SUBSTR(P1.IGNOA,-1) NOT IN ('L') AND NVL(p14.dqrq_normal,'')='' THEN LAST_DAY(DATEADD(DATE('$(load_date)'),1,'mm'))
END --20250806(HBCNRDQE-3951)
END AS LOAN_ORI_MATURITY_DT --贷款原始到期日期
,TO_CHAR(
TO_DATE(P1.LOAN_MATURITY_DT,'YYYYMMDD')
,'YYYY-MM-DD'
) AS LOAN_MATURITY_DT --贷款最新到期日期
,TO_CHAR(TO_DATE(P1.SETTLE_DT,'YYYYMMDD'),'YYYY-MM-DD') AS SETTLE_DT --实际终止日期
,NULL AS ACCT_CLOSE_DT --信贷账户销户日期
,P1.RATE_FLOAT_TYPE AS RATE_FLOAT_TYPE --利率类型
,P1.RATE_FLOAT_FREQ AS RATE_FLOAT_FREQ --利率浮动频率
,P1.BASE_RATE_TYPE AS BASE_RATE_TYPE --基准利率类型
,P1.BASE_RATE AS BASE_RATE --基准利率
,NVL(P15.actual_rate,P1.ACTUAL_RATE) AS ACTUAL_RATE --实际利率
,P1.NEXT_RATE_CHANGE_DT AS NEXT_RATE_CHANGE_DT --下一贷款利率重新定价日
,P1.PRI_PAY_METHOD AS PRI_PAY_METHOD --还本频率
,P1.SRC_PRI_PAY_METHOD AS SRC_PRI_PAY_METHOD --源系统还本频率
,P1.INT_PAY_METHOD AS INT_PAY_METHOD --还息频率
,P1.SRC_INT_PAY_METHOD AS SRC_INT_PAY_METHOD --源系统还息频率
,P1.INT_CCY_CODE AS INT_CCY_CODE --利息币种
,P1.INTEREST AS INTEREST --应收利息
,NVL(CONCAT('CNHSBC',P1.LOAN_IN_ACCT_NO),P1.CONTRACT_NO) AS LOAN_IN_ACCT_NO --贷款入账账号 -- [OCR-UNCERTAIN: LOAN_IN_ACCT_NO CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value CONCAT('CNHSBC',P1.LOAN_IN_ACCT_NO)]
,CASE WHEN NVL(P12.COUNTRY_CODE,'') NOT IN ('CHN','TWN','MAC','HKG') THEN NVL(CASE WHEN TRIM(P9.CUST_NAM_EN)='' THEN NULL ELSE P9.CUST_NAM_EN END, P9.CUST_NAM_CH)
ELSE NVL(CASE WHEN TRIM(P9.CUST_NAM_CH)='' THEN NULL ELSE P9.CUST_NAM_CH END, P9.CUST_NAM_EN)
END AS LOAN_IN_ACCT_NAME --贷款入账户名
,NVL(P6.ORG_NO,P5.LOAN_IN_BANK_NO) AS LOAN_IN_BANK_NO --贷款入账行号
,NVL(
CASE WHEN SUBSTR(P1.LOAN_IN_BANK_NO,1,9) IS NOT NULL THEN P6.ORG_NAME
ELSE P5.LOAN_IN_BANK_NAME
END
) AS LOAN_IN_BANK_NAME --贷款入账行名
,P1.TOTAL_PERIOD AS TOTAL_PERIOD --总期数
,P1.CURR_PERIOD AS CURR_PERIOD --当前期数
,P1.NEXT_PAY_DATE AS NEXT_PAY_DATE --下期还款日期
,P1.NEXT_PAY_NOMINAL AS NEXT_PAY_NOMINAL --下期应还本金
,P1.NEXT_PAY_RATE AS NEXT_PAY_RATE --下期应还利息
,P1.DEBT_PERIOD AS DEBT_PERIOD --连续欠款期数
,P1.TOTAL_DEBT_PERIOD AS TOTAL_DEBT_PERIOD --累计欠款期数
,P1.REPAY_MODE AS REPAY_MODE --还款方式
,P1.SRC_REPAY_MODE AS SRC_REPAY_MODE --源系统还款方式
,NVL(P1.REPAY_ACCT_NO,NVL(CONCAT('CNHSBC',P1.LOAN_IN_ACCT_NO),P1.CONTRACT_NO)) AS REPAY_ACCT_NO --还款账号 -- [OCR-UNCERTAIN: nested REPAY_ACCT_NO CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value CONCAT('CNHSBC',P1.LOAN_IN_ACCT_NO)]
,NVL(P8.ORG_NO,NVL(P6.ORG_NO,P5.LOAN_IN_BANK_NO)) AS REPAY_BANK_NO --还款账号所属行号
,NVL(P8.ORG_NAME,NVL(P5.LOAN_IN_BANK_NAME,P1.CONTRACT_NO)) AS REPAY_BANK_NAME --还款账号所属行名 -- [OCR-UNCERTAIN: nested REPAY_BANK_NAME CASE WHEN/THEN branch unreadable; collapsed to its legible ELSE value P5.LOAN_IN_BANK_NAME]
,NVL(P12.COUNTRY_CODE,'') AS LOAN_PURPOSE_COUNTRY_CODE --贷款投向国家
,NVL(SUBSTR(P10.YHDS50,1,6),P5.LOAN_PURPOSE_DIST) AS LOAN_PURPOSE_DIST --贷款投向地区
,P1.LOAN_PURPOSE_INDU AS LOAN_PURPOSE_INDU --投向行业
,p16.value AS LOAN_PURPOSE_SNI --投向战略性新兴产业分类
,p17.value AS LOAN_PURPOSE_CUL --投向文化及相关产业分类
,p18.value AS LOAN_PURPOSE_IND_UPDATE_FLAG --是否投向工业企业技术改造升级项目
,P1.PURPOSE AS PURPOSE --贷款用途
,P1.ABROAD_LOAN_PURPOSE AS ABROAD_LOAN_PURPOSE --境外贷款资金用途
,P1.SYNDICATED_LOAN_FLAG AS SYNDICATED_LOAN_FLAG --是否银团贷款
,P1.IS_OUTSHEET AS IS_OUTSHEET --贷款是否出表
,P1.LOAN_STATUS AS LOAN_STATUS --贷款状态
,P1.SRC_STATUS AS SRC_LOAN_STATUS --源系统贷款状态
,P1.LOAN_STATUS AS LOAN_ACCT_STATUS --信贷账户状态
,P1.SRC_STATUS AS SRC_LOAN_ACCT_STATUS --源系统信贷账户状态
,P1.COLLECTION AS COLLECTION --催收标志
,P1.COLLECTION_TYPE AS COLLECTION_TYPE --催收方式
,CASE WHEN P1.LOAN_STATUS='03' THEN CASE
WHEN P11.ZCHXBZ='Y' THEN '05'
ELSE '01'
END END AS SETTLE_MODE --贷款终结方式
,P1.SRC_SETTLE_MODE AS SRC_SETTLE_MODE --源系统贷款终结方式
,NULL AS ACCT_STATUS --账户状态
,NULL AS SRC_ACCT_STATUS --源系统账户状态
,P9.customer_manager_no AS CREDITOR_NO --客户经理工号
,P1.PRIN_OD_DT AS PRIN_OD_DT --本金逾期日期
,'' AS PRIN_OD_AMT --欠本金额
,P1.INT_OD_DT AS INT_OD_DT --利息逾期日期
,P1.INT_OD_AMT AS INT_OD_AMT --表内欠息余额
,P1.INTEREST_BALANCE2 AS INTEREST_BALANCE2 --表外欠息余额
,P1.PENALTYINT_AMT AS PENALTYINT_AMT --罚息金额
,P1.COMPOUNDINT_AMT AS COMPOUNDINT_AMT --逾期复利金额
,P1.MITIGATE AS MITIGATE --减免金额
,P1.EXTRA_FEE AS EXTRA_FEE --其他费用金额
,P1.CURR_NON_TRADING_ADJ_AMT AS CURR_NON_TRADING_ADJ_AMT --本月非交易变动
,P1.CAPTIAL_RATIO AS CAPTIAL_RATIO --出资比例
,P1.COOPER_NAME AS COOPER_NAME --合作机构名称
,P1.INT_SUBSIDY AS INT_SUBSIDY --贷款财政扶持方式
,P1.SRC_INT_SUBSIDY AS SRC_INT_SUBSIDY --源系统贷款财政扶持方式
,P1.INDUSTRI_STRUCT_TYPE AS INDUSTRI_STRUCT_TYPE --产业结构调整类型
,P1.UPGRADE_FLAG AS UPGRADE_FLAG --工业转型升级标识
,P1.IS_INTERNET_LOAN AS IS_INTERNET_LOAN --是否互联网贷款
,NVL(KJDK.KJDK_FLAG,'N') AS is_technology_loan --是否科技贷款
,P1.IS_GREENLOAN AS IS_GREENLOAN --是否绿色贷款
,P1.GREENLOAN_TYPE AS GREENLOAN_TYPE --绿色贷款用途
,P1.IS_GREEN_TRANSFINA AS IS_GREEN_TRANSFINA --是否绿色贸易融资
,P1.GREEN_TRANSFINA_TYPE AS GREEN_TRANSFINA_TYPE --绿色贸易融资用途
,P1.IS_GREEN_CONSUME AS IS_GREEN_CONSUME --是否绿色消费融资
,P1.GREEN_CONSUME_TYPE AS GREEN_CONSUME_TYPE --绿色消费融资用途
,P1.IS_VTR_GTR AS IS_VTR_GTR --是否创业担保贷款
,P1.FIRST_LOAN_FLG AS FIRST_LOAN_FLG --是否首次贷款
,P1.IS_FARMERS_INSUR AS IS_FARMERS_INSUR --是否农户联保
,P1.OTHRE_PY_GUARWAY AS OTHRE_PY_GUARWAY --其他还款保证方式
,P1.VTR_GTR_TYPE AS VTR_GTR_TYPE --创业担保贷款类型
,P1.SRC_VTR_GTR_TYPE AS SRC_VTR_GTR_TYPE  -- 源系统创业担保贷款类型
,P1.ENVSAFE_ENPR_LOAN AS ENVSAFE_ENPR_LOAN  -- 环境及安全等重大风险企业贷款
,P1.IS_AGRIC_LOAN AS IS_AGRIC_LOAN  -- 是否涉农贷款
,P1.IS_PRATTWHITNEY_LOAN AS IS_PRATTWHITNEY_LOAN  -- 是否普惠型贷款
,P1.PGUPER_AMT AS PGUPER_AMT  -- 购汇履约金额
,P1.EXT_DEBT_NO AS EXT_DEBT_NO  -- 外债编号
,P1.LOAN_EX_GU_NO AS LOAN_EX_GU_NO  -- 外保内贷编号
,P1.CFEO_GUD_APPROVAL_NO AS CFEO_GUD_APPROVAL_NO  -- 外保内贷批准文件号
,P1.CFEO_GUD_APPROVAL_CCY_CODE AS CFEO_GUD_APPROVAL_CCY_CODE  -- 外保内贷批准额度币种
,P1.CFEO_GUD_APPROVAL_AMT AS CFEO_GUD_APPROVAL_AMT  -- 外保内贷批准额度金额
,P1.BAD_LOAN_RELEASE_TYPE AS BAD_LOAN_RELEASE_TYPE  -- 不良贷款风险分担方式
,P1.SRC_BAD_LOAN_RELEASE_TYPE AS SRC_BAD_LOAN_RELEASE_TYPE  -- 源系统不良贷款风险分担方式
,P1.IS_COVERED_ASSET AS IS_COVERED_ASSET  -- 是否被抵押或担保
,P1.COLL_RES_MATURITY AS COLL_RES_MATURITY  -- 担保品剩余期限
,P1.OVERDUE_TYPE AS OVERDUE_TYPE  -- 逾期分类
,P1.USEOFUNDS_TYPE AS USEOFUNDS_TYPE  -- 外汇资金用途
,P1.REMARK AS REMARK  -- 备注
,P1.SYS_SRC_CODE AS SYS_SRC_CODE  -- 源系统代码
,NULL AS business_line
,SUBSTR(P1.BRANCH_CODE,1,2) AS tag_country
,SUBSTR(P1.BRANCH_CODE,3,4) AS tag_entity
,SUBSTR(P1.BRANCH_CODE,-3) AS tag_branch
,NULL AS tag_gbgf
,NULL AS tag_reserve
,'WSB_GTRF_RFN' AS tag_primary_accountable_party
,'WSB_GTRF_RFN' AS tag_responsible_party
,NULL AS Reserved_Field1
,NULL AS Reserved_Field2
,NULL AS Reserved_Field3
,NULL AS Reserved_Field4
,NULL AS Reserved_Field5
,NULL AS Reserved_Field6
,NULL AS Reserved_Field7
,NULL AS Reserved_Field8
,P1.IGNOA AS Reserved_Field9  -- 20240407增加RFN的PRODUCT_CODE字段
,NULL AS Reserved_Field10
,NULL AS Reserved_Field11
,NULL AS Reserved_Field12
,KHTYBH_BUYER_BJ AS Reserved_Field13  -- 买方是否存在的标记：Y是N否
,KHTYBH_BUYER AS Reserved_Field14  -- 买方客户号
,NULL AS Reserved_Field15
,P1.DKCPLB AS Reserved_Field15  -- 贷款产品类别
,NULL AS Reserved_Field16
,NULL AS Reserved_Field17
,'1CF' AS Reserved_Field18
,NULL AS Reserved_Field19
,P1.FTP_KEY AS Reserved_Field20
,NULL AS dis_user
,NULL AS dis_operate_flag
,NULL AS dis_data_from
,NULL AS dis_edit_lock
,NULL AS dis_verify_status
,'${load_date}' AS dis_data_date
-- 20250327 chenbinbin HBCNRDQE-3524: dis_bank_id 添加兜底：空值为'CNHSBC900Z'
,NVL(P3.ORG_NO,'CNHSBC900Z') AS dis_bank_id
,NULL AS dis_curr_step
,NULL AS dis_step_id
,NULL AS dis_modify_user
,NULL AS dis_status_alias
,getdate() AS rec_creat_dt_tm  -- 20240116新增
,NULL AS rec_updt_dt_tm  -- 20240116新增
,P1.loan_purpose_onoff_flag  -- 境内外标识"F"境外/"I"境内
,SUBSTR(P1.IGNDA,1,4) AS IGNDA  -- 20250806(HBCNRDQE-3951)(20251104:修改逻辑，只截取该字段前四位)
,P1.IGJYA  -- 20250806(HBCNRDQE3951)
,P1.IGNBA  -- 20250806(HBCNRDQE3951)
FROM TEMP_BDM_ACC_LOAN_INFO_01 P1
LEFT JOIN TEMP_JGXX P3
ON P3.BRANCH_CODE = P1.BRANCH_CODE
JOIN BDM_ACC_LOAN_INFO P4
ON P4.lending_ref = P1.lending_ref
AND P4.DATA_DT = DATEADD(DATE '${load_date}', - 1, 'dd')
LEFT JOIN BDM_ACC_LOAN_INFO P5
ON P5.CONTRACT_NO = P1.CONTRACT_NO
AND P5.DATA_DT = TO_CHAR(LASTDAY(TO_DATE(DATEADD(DATE '${load_date}', - 1, 'mm'),'yyyy-MM-dd')),'yyyy-MM-dd')
LEFT JOIN TEMP_JGXX P6
ON P6.BRANCH_CODE = SUBSTR(P1.LOAN_IN_BANK_NO,1,9)
LEFT JOIN TEMP_JGXX P8
ON P8.BRANCH_CODE = SUBSTR(P1.REPAY_ACCT_NO,1,9)
JOIN BDM_CUS_CCUSTOMER P9
ON P1.CUST_NO = P9.CUST_NO
AND P9.DATA_DT = '${load_date}'
LEFT JOIN ODS_HUB_SSSTDPP P10
ON P10.YHTBID = 'Z4'
AND P10.YHCODE = SUBSTR(P3.ORG_NO,-3)
AND P10.P_DT = '${load_date}'
JOIN TEMP_ZCHX P11
ON P11.BUSI_NO = P1.LENDING_REF
LEFT JOIN BDM_CUS_ADDRESS P12
ON P9.CUST_NO = P12.CUST_NO
AND P12.add_type = 'col'
AND P12.ADD_STATUS = '1'
AND P12.DATA_DT = '${load_date}'
LEFT JOIN temp_dqrq_bulk p13
ON SUBSTR(p1.lending_ref,4,5) = lpad(p13.acct_no,5,'0')
LEFT JOIN temp_dqrg_normal_01 p14
ON SUBSTR(p1.lending_ref,4,5) = lpad(p14.acct_no,5,'0')
JOIN (  -- 20240229修改科技贷款逻辑
    SELECT DISTINCT vlookup_key_value AS CUST_NO
    ,'Y' AS KJDK_FLAG
    FROM ods_cdp_gdc_label_fin
    WHERE 1104_report = 'G19'  -- [OCR-UNCERTAIN: value shown as 's70']
    AND  -- known-invalid OCR fragment: dangling AND predicate (not valid on a real engine) -- AND field = 'IS_SIENCE_TECH' AND value = '1'  -- 20240401增的数据
) KJDK
ON P1.CUST_NO = KJDK.CUST_NO
LEFT JOIN ods_gdc_split_fg_rating_temp gdc_wjfl  -- 五级形态手工表
ON p1.cust_no = gdc_wjfl.cust_no
-- 科目
AND gdc_wjfl.rn = 1
JOIN (  -- 20240202调整科目号
    SELECT arrangement_local_number
    ,cb_pointer
    ,lrr_key
    ,account
    ,product
    ,ROW_NUMBER() OVER(PARTITION BY arrangement_local_number ORDER BY SUBSTR(cb_pointer,2,5),BAL DESC) AS rn
    FROM (
        SELECT substr(arrangement_local_number,1,9) AS arrangement_local_number
        ,cb_pointer
        ,lrr_key
        ,account
        ,product
        ,abs(sum(from_ytd_bal)) AS BAL
        FROM bdm_fin_lrr_key_base_info
        WHERE account IN(SELECT DISTINCT nominal_accounts
            FROM ODS_CDP_GDC_TABLE_COA_LIST
            WHERE source_chartfield = '1CF'
            AND NVL(value1,'') <> 'off_balance_sheet'
            AND P_dt = (SELECT
                max(p_dt)
                FROM ods_cdp_gdc_table_coa_list
                WHERE
                p_dt <= TO_DATE(LASTDAY(TO_DATE('${load_date}','yyyy-mm-dd')))
                AND source_chartfield = '1CF'
                AND NVL(value1,'') <> 'off_balance_sheet'))
        -- account IN ('1051114001')  -- 待验证
        AND SUBSTR(glbl_source_chartfield,1,3) = '1CF'
        AND data_dt = '${load_date}'
        GROUP BY arrangement_local_number
    ) tmp_km
) KM
ON KM.arrangement_local_number = P1.FTP_KEY
AND KM.rn = 1
-- 受托支付信息表
LEFT JOIN ODS_GDC_RRCDM_BDM_ACC_ENTRUSTED_PAYMENT stzf
ON stzf.lending_ref = P1.LENDING_REF
-- 利率手工表
AND SUBSTR(stzf.p_dt,1,7) = SUBSTR('${load_date}',1,7)
LEFT JOIN ODS_GDC_RFN_RATE p15
ON p15.contract_no = P1.CONTRACT_NO
AND  -- known-invalid OCR fragment: dangling AND predicate (not valid on a real engine) [OCR-UNCERTAIN: dangling AND - following condition not captured]
LEFT JOIN temp_1104_G19 p16
ON p16.lending_ref = p1.lending_ref
AND p16.bdm_table_field = 'LOAN_PURPOSE_SNI'
LEFT JOIN temp_1104_G19 p17
ON p17.lending_ref = p1.lending_ref
AND p17.bdm_table_field = 'LOAN_PURPOSE_CUL'
LEFT JOIN temp_1104_G19 p18
ON p18.lending_ref = p1.lending_ref
AND p18.bdm_table_field = 'LOAN_PURPOSE_IND_UPDATE_FLAG'
LEFT JOIN temp_dqrq_normal_02 p19
ON p1.lending_ref = p19.dkjjbm
LEFT JOIN bdm_sys_bdm_acc_loan_info p20
ON p20.lending_ref = p1.lending_ref
WHERE 1 = 1


INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}',CHARGE_DEPARTMENT='GTRF_RFN')
SELECT A.LENDING_REF  -- 借据编号
,A.PCB_ACCT_NO  -- 账户标识码
,A.APPLY_NO  -- 申请号
,A.LIMIT_NO  -- 额度编号
,A.CONTRACT_NO  -- 合同号
,A.ORG_NO  -- 机构号
,NVL(branch1.target_branch_internal_code,A.ORG_NO)  -- 机构号
,A.BRANCH_CODE  -- 内部核算机构号
,NVL(branch1.target_branch_internal_code,A.BRANCH_CODE)  -- 内部核算机构号
,A.CUST_NO  -- 客户号
,A.ITEM_CODE  -- 科目号
,A.LRR_KEY_ITEM_CODE  -- LRRKey科目号
,A.HUB_ITEM_CODE  -- HUB科目号
,A.NOMINAL_ACC  -- COA科目
,A.FTP_PRODUCT_CODE  -- FTP产品编码
,A.BUSINESS_TYPE  -- 信贷业务种类
,A.ACCT_NO  -- 信贷分户账账号
,A.BILL_NO  -- 票据号码
,A.FUND_SOURCE  -- 贷款资金来源
,A.SIGN_CHANNEL  -- 贷款签约渠道
,A.LOAN_ORIGI_TYPE  -- 贷款发放类型
,A.SRC_LOAN_ORIGI_TYPE  -- 源系统贷款发放类型
,A.PAY_MODE  -- 放款方式
,A.SRC_PAY_MODE  -- 源系统放款方式
,A.CCY_CODE  -- 币种
,A.LOAN_AMT  -- 放款金额
,A.LOAN_BAL  -- 本金余额
,A.RESERVE  -- 减值准备
,A.LOAN_GRADE  -- 五级分类
,A.ACCT_OPEN_DT  -- 信贷账户开户日期
,A.SRC_ACCT_OPEN_DT  -- 源系统开户日期
,A.ISSUE_DT  -- 贷款发放日期
,A.SRC_ISSUE_DT  -- 源系统贷款发放日期
,CASE WHEN NVL(A.LOAN_ORI_MATURITY_DT,'')<>'' THEN A.LOAN_ORI_MATURITY_DT  -- 贷款原始到期日期 -- [OCR-UNCERTAIN: outer CASE opening / WHEN condition (original line 927) unreadable — reconstructed as NVL(...)<>'' from the legible THEN value A.LOAN_ORI_MATURITY_DT + the "系统报送掉落→兜底" comment]
-- 3.以上逻辑取得的到期日仍小于放款日期，如果系统报送的确掉落的话，则兜底到期日期=放款日期+1day
ELSE CASE WHEN
    (CASE WHEN SUBSTR(A.LENDING_REF,-1)='2' AND A.IGJYA='R'  -- 有追授信情况下（IGJYA=R），本金原有贷款到期日+加graceperiod宽限期<FCLETWK.
          THEN DATEADD(DATE(A.LOAN_ORI_MATURITY_DT),CAST(NVL(A.IGNDA,0) AS BIGINT),'dd')
          WHEN SUBSTR(A.LENDING_REF,-1)='2' AND A.IGJYA='N'  -- 无追授信情况下（IGJYA=N），原有贷款到期日+加宽限期90天
          THEN DATEADD(DATE(A.LOAN_ORI_MATURITY_DT),90,'dd')  -- 20250806(HBCNRDQE3951)
          ELSE A.LOAN_ORI_MATURITY_DT
    END) < A.ISSUE_DT THEN DATEADD(DATE(A.issue_dt),1,'dd')  -- (20251104:以上逻辑取得的到期日仍小于放款日期，如果系统报送的确掉落的话，则兜底到期日期=放款日期+1day)
    ELSE
        (CASE WHEN SUBSTR(A.LENDING_REF,-1)='2' AND A.IGJYA='R'  -- 有追授信情况下，（IGJYA=R），本金原有贷款到期日+加graceperiod宽限期<FCLETWK.
              THEN DATEADD(DATE(A.LOAN_ORI_MATURITY_DT),CAST(NVL(A.IGNDA,0) AS BIGINT),'dd')
              WHEN SUBSTR(A.LENDING_REF,-1)='2' AND A.IGJYA='N'  -- 无追授信情况下（IGJYA=N），原有贷款到期日+加宽限期90天
              THEN DATEADD(DATE(A.LOAN_ORI_MATURITY_DT),90,'dd')  -- 20250806(HBCNRDQE3951)

              ELSE A.LOAN_ORI_MATURITY_DT
        END)
END
END AS LOAN_ORI_MATURITY_DT
,A.LOAN_MATURITY_DT  -- 贷款最新到期日期
,A.SETTLE_DT  -- 实际终止日期
,A.ACCT_CLOSE_DT  -- 信贷账户销户日期
,A.RATE_FLOAT_TYPE  -- 利率类型
,A.RATE_FLOAT_FREQ  -- 利率浮动频率
,A.BASE_RATE_TYPE  -- 基准利率类型
,A.BASE_RATE  -- 基准利率
,A.ACTUAL_RATE  -- 实际利率
,A.NEXT_RATE_CHANGE_DT  -- 下一贷款利率重新定价日
,A.PRI_PAY_METHOD  -- 还本频率
,A.SRC_PRI_PAY_METHOD  -- 源系统还本频率
,A.INT_PAY_METHOD  -- 还息频率
,A.SRC_INT_PAY_METHOD  -- 源系统还息频率
,A.INT_CCY_CODE  -- 利息币种
,A.INTEREST  -- 应收利息
,A.LOAN_IN_ACCT_NO  -- 贷款入账账号
,A.LOAN_IN_ACCT_NAME  -- 贷款入账户名
--,A.LOAN_IN_BANK_NO  -- 贷款入账行号
,NVL(branch2.target_branch_code,A.LOAN_IN_BANK_NO)  -- 贷款入账行号
,A.LOAN_IN_BANK_NAME  -- 贷款入账行名
,NVL(t_branch2.org_name,A.LOAN_IN_BANK_NAME)  -- 贷款入账行名
,A.TOTAL_PERIOD  -- 总期数
,A.CURR_PERIOD  -- 当前期数
,A.NEXT_PAY_DATE  -- 下期还款日期
,A.NEXT_PAY_NOMINAL  -- 下期应还本金
,A.NEXT_PAY_RATE  -- 下期应还利息
,A.DEBT_PERIOD  -- 连续欠款期数
,A.TOTAL_DEBT_PERIOD  -- 累计欠款期数
,A.REPAY_MODE  -- 还款方式
,A.SRC_REPAY_MODE  -- 源系统还款方式
,A.REPAY_ACCT_NO  -- 还款账号
,A.REPAY_BANK_NO  -- 还款账号所属行号
,NVL(branch3.target_branch_code,a.repay_bank_no)  -- 还款账号所属行号
,A.REPAY_BANK_NAME  -- 还款账号所属行名
,NVL(t_branch3.org_name,a.repay_bank_name)  -- 还款账号所属行名
,A.LOAN_PURPOSE_COUNTRY_CODE  -- 贷款投向国家
,A.LOAN_PURPOSE_DIST  -- 贷款投向地区
,A.LOAN_PURPOSE_INDU  -- 投向行业
,A.LOAN_PURPOSE_SNI  -- 投向战略性新兴产业分类
,A.LOAN_PURPOSE_CUL  -- 投向文化及相关产业分类
,A.LOAN_PURPOSE_IND_UPDATE_FLAG  -- 是否投向工业企业技术改造升级项目
,A.PURPOSE  -- 贷款用途
,A.ABROAD_LOAN_PURPOSE  -- 境外贷款资金用途
,A.SYNDICATED_LOAN_FLAG  -- 是否银团贷款
,A.IS_OUTSHEET  -- 贷款是否出表
,A.LOAN_STATUS  -- 贷款状态
,A.SRC_LOAN_STATUS  -- 源系统贷款状态
,A.LOAN_ACCT_STATUS  -- 信贷账户状态
,A.SRC_LOAN_ACCT_STATUS  -- 源系统信贷账户状态
,A.COLLECTION  -- 催收标志
,A.COLLECTION_TYPE  -- 催收方式
,A.SETTLE_MODE  -- 贷款终结方式
,A.SRC_SETTLE_MODE  -- 源系统贷款终结方式
,A.ACCT_STATUS  -- 账户状态
,A.SRC_ACCT_STATUS  -- 源系统账户状态
,A.CREDITOR_NO  -- 客户经理工号
,A.PRIN_OD_DT  -- 本金逾期日期
,A.PRIN_OD_AMT  -- 欠本金额
,A.INT_OD_DT  -- 利息逾期日期
,A.INT_OD_AMT  -- 表内欠息余额
,A.INTEREST_BALANCE2  -- 表外欠息余额
,A.PENALTYINT_AMT  -- 罚息金额
,A.COMPOUNDINT_AMT  -- 逾期复利金额
,A.MITIGATE  -- 减免金额
,A.EXTRA_FEE  -- 其他费用金额
,A.CURR_NON_TRADING_ADJ_AMT  -- 本月非交易变动
,A.CAPTIAL_RATIO  -- 出资比例
,A.COOPER_NAME  -- 合作机构名称
,A.INT_SUBSIDY  -- 贷款财政扶持方式
,A.SRC_INT_SUBSIDY  -- 源系统贷款财政扶持方式
,A.INDUSTRI_STRUCT_TYPE  -- 产业结构调整类型
,A.UPGRADE_FLAG  -- 工业转型升级标识
,A.IS_INTERNET_LOAN  -- 是否互联网贷款
,A.IS_TECHNOLOGY_LOAN  -- 是否科技贷款
,A.IS_GREENLOAN  -- 是否绿色贷款
,A.GREENLOAN_TYPE  -- 绿色贷款用途
,A.IS_GREEN_TRANSFINA  -- 是否绿色贸易融资
,A.GREEN_TRANSFINA_TYPE  -- 绿色贸易融资用途
,A.IS_GREEN_CONSUME  -- 是否绿色消费融资
,A.GREEN_CONSUME_TYPE  -- 绿色消费融资用途
,A.IS_VTR_GTR  -- 是否创业担保贷款
,A.FIRST_LOAN_FLG  -- 是否首次贷款
,A.IS_FARMERS_INSUR  -- 是否农户联保
,A.OTHRE_PY_GUARWAY  -- 其他还款保证方式
,A.VTR_GTR_TYPE  -- 创业担保贷款类型
,A.SRC_VTR_GTR_TYPE  -- 源系统创业担保贷款类型
,A.ENVSAFE_ENPR_LOAN  -- 环境及安全等重大风险企业贷款
,A.IS_AGRIC_LOAN  -- 是否涉农贷款
,A.IS_PRATTWHITNEY_LOAN  -- 是否普惠型贷款
,A.PGUPER_AMT  -- 购汇履约金额
,A.EXT_DEBT_NO  -- 外债编号
,A.LOAN_EX_GU_NO  -- 外保内贷编号
,A.CFEO_GUD_APPROVAL_NO  -- 外保内贷批准文件号
,A.CFEO_GUD_APPROVAL_CCY_CODE  -- 外保内贷批准额度币种
,A.CFEO_GUD_APPROVAL_AMT  -- 外保内贷批准额度金额
,A.BAD_LOAN_RELEASE_TYPE  -- 不良贷款风险分担方式
,A.SRC_BAD_LOAN_RELEASE_TYPE  -- 源系统不良贷款风险分担方式
,A.IS_COVERED_ASSET  -- 是否被抵押或担保
,A.COLL_RES_MATURITY  -- 担保品剩余期限
,A.OVERDUE_TYPE  -- 逾期分类
,A.USEOFUNDS_TYPE  -- 外汇资金用途
,A.REMARK  -- 备注
,A.SYS_SRC_CODE  -- 源系统代码
,A.business_line
,A.tag_country
,NVL(SUBSTR(branch1.target_branch_internal_code,1,2),A.tag_country)
,A.tag_entity
,NVL(SUBSTR(branch1.target_branch_internal_code,3,4),A.tag_entity)
,A.tag_branch
,NVL(SUBSTR(branch1.target_branch_internal_code,-3),A.tag_branch)
,A.tag_gbgf
,A.tag_reserve
,A.tag_primary_accountable_party
,A.tag_responsible_party
,A.Reserved_Field1
,A.Reserved_Field2
,A.Reserved_Field3
,A.Reserved_Field4
,A.Reserved_Field5
,A.Reserved_Field6
,A.Reserved_Field7
,A.Reserved_Field8
,A.Reserved_Field9
,A.Reserved_Field10
,p1.purpose_code AS Reserved_Field11  -- purpose_code110使用
,A.Reserved_Field12
,A.Reserved_Field13
,A.Reserved_Field14
,A.Reserved_Field15
,A.Reserved_Field16
,A.Reserved_Field17
,A.Reserved_Field18
,A.Reserved_Field19
,A.Reserved_Field20
,A.dis_user
,A.dis_operate_flag
,A.dis_data_from
,A.dis_edit_lock
,A.dis_verify_status
,A.dis_data_date
,A.dis_bank_id
-- 20250327 chenbinbin HBCNRDQE-3524: dis_bank_id 添加兜底：空值为'CNHSBC900Z'
,NVL(NVL(branch1.target_branch_internal_code,A.dis_bank_id),'CNHSBC900Z') AS dis_bank_id
,A.dis_curr_step
,A.dis_step_id
,A.dis_modify_user
,A.dis_status_alias
,A.rec_creat_dt_tm  -- 20240115新增
,A.rec_updt_dt_tm  -- 20240115新增
,NULL AS RESERVED_1
,NULL AS RESERVED_2
,NULL AS RESERVED_3
,NULL AS RESERVED_4
,NULL AS RESERVED_5
,NULL AS RESERVED_6
,B.ZGGHCLI + C.IGNOA AS RESERVED_7
,NULL AS RESERVED_8
,NULL AS RESERVED_9
,NULL AS RESERVED_10
,SUBSTR(A.IGNBA,1,3) AS RESERVED_10  -- [OCR-UNCERTAIN: both NULL and SUBSTR captured for RESERVED_10]
,NULL AS RESERVED_11
,NULL AS RESERVED_12
,NULL AS RESERVED_13
,NULL AS RESERVED_14
,NULL AS RESERVED_15
,'RFN-对公信贷业务借据' AS PRIMARY_SRC_SYSTEM
,NULL AS DQ_RESULT
,NULL AS COM_RESERVED_1
,NULL AS COM_RESERVED_2
,NULL AS COM_RESERVED_3
,NULL AS COM_RESERVED_4
,NULL AS COM_RESERVED_5
,NULL AS COM_RESERVED_6
,NULL AS DM_FLAG1
,CASE WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6)='CNHSBC' AND SUBSTR(A.LOAN_IN_ACCT_NO,13,1) ='9' THEN 'NI'
WHEN EXISTS(SELECT 1 FROM BDM_ACC_INTERNAL_ACCT WHERE data_dt = '${load_date}' AND acct_no = A.LOAN_IN_ACCT_NO) THEN 'NI'
WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a
    LEFT JOIN bdm_acc_deposit_acct b
    ON a.cust_no = b.cust_no
    WHERE A.LOAN_IN_ACCT_NO = b.acct_no
    AND b.data_dt = '${load_date}'
    AND a.CUST_TYPE in ('I','J')) THEN 'I'
WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a
    LEFT JOIN bdm_acc_deposit_acct b
    ON a.cust_no = b.cust_no
    WHERE A.LOAN_IN_ACCT_NO = b.acct_no
    AND b.data_dt = '${load_date}'
    AND a.CUST_TYPE = 'C') THEN 'NI'
WHEN EXISTS(
    SELECT 1
    FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS b
    WHERE b.p_dt = (select max(p_dt) p_dt from ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS)  -- 最新的脱敏白名单数据
    AND nvl('1',b.p_dt) = nvl('1',a.dis_data_date)  -- 必须加一个恒等式
    AND LOWER(A.loan_in_acct_name) like concat('%',LOWER(b.datamask_keywords),'%')
    THEN 'NI'
WHEN regexp_instr(A.LOAN_IN_ACCT_NAME,'[0-9]+$') > 0  -- 判断客户名称是否含有数字
OR (regexp_instr(A.LOAN_IN_ACCT_NAME,'[A-Za-z]+$') >= 1 AND length(A.LOAN_IN_ACCT_NAME) <> lengthb(A.LOAN_IN_ACCT_NAME))  -- 判断客户名称是否同时含有中文和英文
THEN 'NI'
END AS DM_FLAG2  -- 境内外标识"F"境外/"I"境内
,A.loan_purpose_onoff_flag
FROM TEMP_BDM_ACC_LOAN_INFO_02 A
LEFT JOIN ODS_HUB_SSCUSTP B
ON B.ZGCTCD = SUBSTR(A.CUST_NO,1,2)
AND B.ZGDCG = SUBSTR(A.CUST_NO,3,4)
AND LPAD(B.ZGDCB,3,'0') = SUBSTR(A.CUST_NO,7,3)
AND LPAD(B.ZGDCS,6,'0') = SUBSTR(A.CUST_NO,10,6)
AND B.P_DT = '${load_date}'
LEFT JOIN TEMP_RFN C
ON C.DKJJBM = A.LENDING_REF
-- 蛇口需求
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch1
ON branch1.account_no = A.acct_no  -- 信贷分户账号关联
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    ,target_branch_code
    ,target_branch_name
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch2
ON branch2.account_no = A.loan_in_acct_no  -- 入账账号关联
LEFT JOIN bdm_pub_hsbc_acct_branch t_branch2
ON t_branch2.branch_code = branch2.target_branch_internal_code
AND t_branch2.data_dt = '${load_date}'
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    ,target_branch_code
    ,target_branch_name
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch3
ON branch3.account_no = A.repay_acct_no  -- 还款账号关联
LEFT JOIN bdm_pub_hsbc_acct_branch t_branch3
ON t_branch3.branch_code = branch3.target_branch_internal_code
AND t_branch3.data_dt = '${load_date}'
LEFT JOIN v_js_purpose_code('${load_date}') p1
ON p1.khtybh = a.cust_no
AND p1.flag = 'GTRF_RFN' ;


-- 倒补逻辑
INSERT INTO TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}',CHARGE_DEPARTMENT='GTRF_RFN')
SELECT A.LENDING_REF  -- 借据编号
,A.PCB_ACCT_NO  -- 账户标识码
,A.APPLY_NO  -- 申请号
,A.LIMIT_NO  -- 额度编号
,A.CONTRACT_NO  -- 合同号
,A.ORG_NO  -- 机构号
,NVL(branch1.target_branch_internal_code,A.ORG_NO)  -- 机构号
,A.BRANCH_CODE  -- 内部核算机构号
,NVL(branch1.target_branch_internal_code,A.BRANCH_CODE)  -- 内部核算机构号
,A.CUST_NO  -- 客户号
,A.ITEM_CODE  -- 科目号
,A.LRR_KEY_ITEM_CODE  -- LRRKey科目号
,A.HUB_ITEM_CODE  -- HUB科目号
,A.NOMINAL_ACC  -- COA科目
,A.FTP_PRODUCT_CODE  -- FTP产品编码
,A.BUSINESS_TYPE  -- 信贷业务种类
,A.ACCT_NO  -- 信贷分户账账号
,A.BILL_NO  -- 票据号码
,A.FUND_SOURCE  -- 贷款资金来源
,A.SIGN_CHANNEL  -- 贷款签约渠道
,A.LOAN_ORIGI_TYPE  -- 贷款发放类型
,A.SRC_LOAN_ORIGI_TYPE  -- 源系统贷款发放类型
,A.PAY_MODE  -- 放款方式
,A.SRC_PAY_MODE  -- 源系统放款方式
,A.CCY_CODE  -- 币种
,A.LOAN_AMT  -- 放款金额
,A.LOAN_BAL  -- 本金余额
,A.RESERVE  -- 减值准备
,A.LOAN_GRADE  -- 五级分类
,A.ACCT_OPEN_DT  -- 信贷账户开户日期
,A.SRC_ACCT_OPEN_DT  -- 源系统开户日期
,A.ISSUE_DT  -- 贷款发放日期
,A.SRC_ISSUE_DT  -- 源系统贷款发放日期
,A.LOAN_ORI_MATURITY_DT  -- 贷款原始到期日期
,CASE WHEN NVL(B.LOAN_ORI_MATURITY_DT,'') <> '' THEN REPLACE(B.LOAN_ORI_MATURITY_DT,'/','-')
ELSE A.LOAN_ORI_MATURITY_DT
END AS LOAN_ORI_MATURITY_DT  -- 贷款原始到期日期
,A.LOAN_MATURITY_DT  -- 贷款最新到期日期
,A.SETTLE_DT  -- 实际终止日期
,A.ACCT_CLOSE_DT  -- 信贷账户销户日期
,A.RATE_FLOAT_TYPE  -- 利率类型
,A.RATE_FLOAT_FREQ  -- 利率浮动频率
,A.BASE_RATE_TYPE  -- 基准利率类型
,A.BASE_RATE  -- 基准利率
,A.ACTUAL_RATE  -- 实际利率
,A.NEXT_RATE_CHANGE_DT  -- 下一贷款利率重新定价日
,A.PRI_PAY_METHOD  -- 还本频率
,A.SRC_PRI_PAY_METHOD  -- 源系统还本频率
,A.INT_PAY_METHOD  -- 还息频率
,A.SRC_INT_PAY_METHOD  -- 源系统还息频率
,A.INT_CCY_CODE  -- 利息币种
,A.INTEREST  -- 应收利息
,A.LOAN_IN_ACCT_NO  -- 贷款入账账号
,A.LOAN_IN_ACCT_NAME  -- 贷款入账户名
,A.LOAN_IN_BANK_NO  -- 贷款入账行号
,NVL(branch2.target_branch_code,A.LOAN_IN_BANK_NO)  -- 贷款入账行号
,A.LOAN_IN_BANK_NAME  -- 贷款入账行名
,NVL(t_branch2.org_name,A.LOAN_IN_BANK_NAME)  -- 贷款入账行名
,A.TOTAL_PERIOD  -- 总期数
,A.CURR_PERIOD  -- 当前期数
,A.NEXT_PAY_DATE  -- 下期还款日期
,A.NEXT_PAY_NOMINAL  -- 下期应还本金
,A.NEXT_PAY_RATE  -- 下期应还利息
,A.DEBT_PERIOD  -- 连续欠款期数
,A.TOTAL_DEBT_PERIOD  -- 累计欠款期数
,A.REPAY_MODE  -- 还款方式
,A.SRC_REPAY_MODE  -- 源系统还款方式
,A.REPAY_ACCT_NO  -- 还款账号
,A.REPAY_BANK_NO  -- 还款账号所属行号
,NVL(branch3.target_branch_code,a.repay_bank_no)  -- 还款账号所属行号
,A.REPAY_BANK_NAME  -- 还款账号所属行名
,NVL(t_branch3.org_name,a.repay_bank_name)  -- 还款账号所属行名
,A.LOAN_PURPOSE_COUNTRY_CODE  -- 贷款投向国家
,A.LOAN_PURPOSE_DIST  -- 贷款投向地区
,A.LOAN_PURPOSE_INDU  -- 投向行业
,A.LOAN_PURPOSE_SNI  -- 投向战略性新兴产业分类
,A.LOAN_PURPOSE_CUL  -- 投向文化及相关产业分类
,A.LOAN_PURPOSE_IND_UPDATE_FLAG  -- 是否投向工业企业技术改造升级项目
,A.PURPOSE  -- 贷款用途
,A.ABROAD_LOAN_PURPOSE  -- 境外贷款资金用途
,A.SYNDICATED_LOAN_FLAG  -- 是否银团贷款
,A.IS_OUTSHEET  -- 贷款是否出表
,A.LOAN_STATUS  -- 贷款状态
,A.SRC_LOAN_STATUS  -- 源系统贷款状态
,A.LOAN_ACCT_STATUS  -- 信贷账户状态
,A.SRC_LOAN_ACCT_STATUS  -- 源系统信贷账户状态
,A.COLLECTION  -- 催收标志
,A.COLLECTION_TYPE  -- 催收方式
,A.SETTLE_MODE  -- 贷款终结方式
,A.SRC_SETTLE_MODE  -- 源系统贷款终结方式
,A.ACCT_STATUS  -- 账户状态
,A.SRC_ACCT_STATUS  -- 源系统账户状态
,A.CREDITOR_NO  -- 客户经理工号
,A.PRIN_OD_DT  -- 本金逾期日期
,A.PRIN_OD_AMT  -- 欠本金额
,A.INT_OD_DT  -- 利息逾期日期
,A.INT_OD_AMT  -- 表内欠息余额
,A.INTEREST_BALANCE2  -- 表外欠息余额
,A.PENALTYINT_AMT  -- 罚息金额
,A.COMPOUNDINT_AMT  -- 逾期复利金额
,A.MITIGATE  -- 减免金额
,A.EXTRA_FEE  -- 其他费用金额
,A.CURR_NON_TRADING_ADJ_AMT  -- 本月非交易变动
,A.CAPTIAL_RATIO  -- 出资比例
,A.COOPER_NAME  -- 合作机构名称
,A.INT_SUBSIDY  -- 贷款财政扶持方式
,A.SRC_INT_SUBSIDY  -- 源系统贷款财政扶持方式
,A.INDUSTRI_STRUCT_TYPE  -- 产业结构调整类型
,A.UPGRADE_FLAG  -- 工业转型升级标识
,A.IS_INTERNET_LOAN  -- 是否互联网贷款
,A.IS_TECHNOLOGY_LOAN  -- 是否科技贷款
,A.IS_GREENLOAN  -- 是否绿色贷款
,A.GREENLOAN_TYPE  -- 绿色贷款用途
,A.IS_GREEN_TRANSFINA  -- 是否绿色贸易融资
,A.GREEN_TRANSFINA_TYPE  -- 绿色贸易融资用途
,A.IS_GREEN_CONSUME  -- 是否绿色消费融资
,A.GREEN_CONSUME_TYPE  -- 绿色消费融资用途
,A.IS_VTR_GTR  -- 是否创业担保贷款
,A.FIRST_LOAN_FLG  -- 是否首次贷款
,A.IS_FARMERS_INSUR  -- 是否农户联保
,A.OTHRE_PY_GUARWAY  -- 其他还款保证方式
,A.VTR_GTR_TYPE  -- 创业担保贷款类型
,A.SRC_VTR_GTR_TYPE  -- 源系统创业担保贷款类型
,A.ENVSAFE_ENPR_LOAN  -- 环境及安全等重大风险企业贷款
,A.IS_AGRIC_LOAN  -- 是否涉农贷款
,A.IS_PRATTWHITNEY_LOAN  -- 是否普惠型贷款
,A.PGUPER_AMT  -- 购汇履约金额
,A.EXT_DEBT_NO  -- 外债编号
,A.LOAN_EX_GU_NO  -- 外保内贷编号
,A.CFEO_GUD_APPROVAL_NO  -- 外保内贷批准文件号
,A.CFEO_GUD_APPROVAL_CCY_CODE  -- 外保内贷批准额度币种
,A.CFEO_GUD_APPROVAL_AMT  -- 外保内贷批准额度金额
,A.BAD_LOAN_RELEASE_TYPE  -- 不良贷款风险分担方式
,A.SRC_BAD_LOAN_RELEASE_TYPE  -- 源系统不良贷款风险分担方式
,A.IS_COVERED_ASSET  -- 是否被抵押或担保
,A.COLL_RES_MATURITY  -- 担保品剩余期限
,A.OVERDUE_TYPE  -- 逾期分类
,A.USEOFUNDS_TYPE  -- 外汇资金用途
,A.REMARK  -- 备注
,A.SYS_SRC_CODE  -- 源系统代码
,A.business_line
,A.tag_country
,NVL(SUBSTR(branch1.target_branch_internal_code,1,2),A.tag_country)
,A.tag_entity
,NVL(SUBSTR(branch1.target_branch_internal_code,3,4),A.tag_entity)
,A.tag_branch
,NVL(SUBSTR(branch1.target_branch_internal_code,-3),A.tag_branch)
,A.tag_gbgf
,A.tag_reserve
,A.tag_primary_accountable_party
,A.tag_responsible_party
,A.Reserved_Field1
,A.Reserved_Field2
,A.Reserved_Field3
,A.Reserved_Field4
,A.Reserved_Field5
,A.Reserved_Field6
,A.Reserved_Field7
,A.Reserved_Field8
,A.Reserved_Field9
,A.Reserved_Field10
,A.Reserved_Field11
,p1.purpose_code AS Reserved_Field11  -- purpose_code110使用
,A.Reserved_Field12
,A.Reserved_Field13
,A.Reserved_Field14
,A.Reserved_Field15
,A.Reserved_Field16
,A.Reserved_Field17
,A.Reserved_Field18
,A.Reserved_Field19
,A.Reserved_Field20
,A.dis_user
,A.dis_operate_flag
,A.dis_data_from
,A.dis_edit_lock
,A.dis_verify_status
,'${load_date}' AS dis_data_date
,A.dis_bank_id
-- 20250327 chenbinbin HBCNRDQE-3524: dis_bank_id 添加兜底：空值为'CNHSBC900Z'
,NVL(NVL(branch1.target_branch_internal_code,A.dis_bank_id),'CNHSBC900Z') AS dis_bank_id
,A.dis_curr_step
,A.dis_step_id
,A.dis_modify_user
,A.dis_status_alias
,getdate() AS rec_creat_dt_tm  -- 20240115新增
,NULL AS rec_updt_dt_tm  -- 20240115新增
,A.RESERVED_1
,A.RESERVED_2
,A.RESERVED_3
,A.RESERVED_4
,A.RESERVED_5
,A.RESERVED_6
,A.RESERVED_7
,A.RESERVED_8
,A.RESERVED_9
,A.RESERVED_10
,A.RESERVED_11
,A.RESERVED_12
,A.RESERVED_13
,A.RESERVED_14
,A.RESERVED_15
,A.PRIMARY_SRC_SYSTEM
,A.DQ_RESULT
,A.COM_RESERVED_1
,A.COM_RESERVED_2
,A.COM_RESERVED_3
,A.COM_RESERVED_4
,A.COM_RESERVED_5
,A.COM_RESERVED_6
,A.DM_FLAG1
,A.DM_FLAG2
,A.loan_purpose_onoff_flag  -- 境内外标识"F"境外/"I"境内
FROM bdm_acc_loan_info A
LEFT JOIN bdm_sys_bdm_acc_loan_info B  -- 更新历史结清借据的到期日期
ON B.lending_ref = A.lending_ref
-- 蛇口需求
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch1
ON branch1.account_no = A.acct_no  -- 信贷分户账号关联
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    ,target_branch_code
    ,target_branch_name
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch2
ON branch2.account_no = A.loan_in_acct_no  -- 入账账号关联
LEFT JOIN bdm_pub_hsbc_acct_branch t_branch2
ON t_branch2.branch_code = branch2.target_branch_internal_code
AND t_branch2.data_dt = '${load_date}'
LEFT JOIN (
    SELECT account_no
    ,target_branch_internal_code
    ,target_branch_code
    ,target_branch_name
    FROM ods_cdp_gdc_acct_migrate_to_diff_branches
    WHERE p_dt = (SELECT MAX(p_dt) FROM ods_cdp_gdc_acct_migrate_to_diff_branches a WHERE SUBSTR(p_dt,1,7) <= SUBSTR('${load_date}',1,7))  -- 取到跑数日期为止最新的一期数据
) branch3
ON branch3.account_no = A.repay_acct_no  -- 还款账号关联
LEFT JOIN bdm_pub_hsbc_acct_branch t_branch3
ON t_branch3.branch_code = branch3.target_branch_internal_code
AND t_branch3.data_dt = '${load_date}'
LEFT JOIN v_js_purpose_code('${load_date}') p1
ON p1.khtybh = a.cust_no
AND p1.flag = 'GTRF_RFN'
WHERE A.DATA_DT = DATE_ADD(DATE '${load_date}', - 1)  -- 前一天
AND A.CHARGE_DEPARTMENT = 'GTRF_RFN'
AND NOT EXISTS (SELECT 1 FROM bdm_acc_loan_info B WHERE B.CHARGE_DEPARTMENT = 'GTRF_RFN' AND B.DATA_DT = '${load_date}' AND B.LENDING_REF = A.LENDING_REF) ;





-- 操作日志记录
SELECT '${load_date}' AS data_dt
,'BDM' AS object_domain
,'Acc' AS sub_src_system
,'BDM_ACC_LOAN_INFO' AS table_name
,'BDM_ACC_LOAN_INFO_RFN' AS job_name
,COUNT(1) AS total_rows
,getdate() AS load_time  -- [OCR-UNCERTAIN: leading char ambiguous (',' vs '--')]
,'Y' AS STATUS
,NULL AS remarks
FROM bdm_acc_loan_info
WHERE data_dt = '${load_date}'
AND charge_department = 'GTRF_RFN' ;
