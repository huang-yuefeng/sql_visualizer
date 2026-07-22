-- SPIDER: Show names, results and bulgarian commanders of the battles with no ships lost in the 'English Chann
-- DB: battle_death | Score: 6
SELECT name ,  RESULT ,  bulgarian_commander FROM battle EXCEPT SELECT T1.name ,  T1.result ,  T1.bulgarian_commander FROM battle AS T1 JOIN ship AS T2 ON T1.id  =  T2.lost_in_battle WHERE T2.location  =  'English Channel';
