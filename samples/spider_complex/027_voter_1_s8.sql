-- SPIDER: List the area codes in which voters voted both for the contestant 'Tabatha Gehling' and the contesta
-- DB: voter_1 | Score: 8
SELECT T3.area_code FROM contestants AS T1 JOIN votes AS T2 ON T1.contestant_number  =  T2.contestant_number JOIN area_code_state AS T3 ON T2.state  =  T3.state WHERE T1.contestant_name  =  'Tabatha Gehling' INTERSECT SELECT T3.area_code FROM contestants AS T1 JOIN votes AS T2 ON T1.contestant_number  =  T2.contestant_number JOIN area_code_state AS T3 ON T2.state  =  T3.state WHERE T1.contestant_name  =  'Kelly Clauss';
