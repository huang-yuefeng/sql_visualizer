-- SPIDER: What are the codes of template types that are not used for any document?
-- DB: cre_Doc_Template_Mgt | Score: 6
SELECT template_type_code FROM Templates EXCEPT SELECT template_type_code FROM Templates AS T1 JOIN Documents AS T2 ON T1.template_id  =  T2.template_id;
