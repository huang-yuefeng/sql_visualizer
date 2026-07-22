-- SPIDER: What are the ids and names of the battles that led to more than 10 people killed in total.
-- DB: battle_death | Score: 6
SELECT T1.id ,  T1.name FROM battle AS T1 JOIN ship AS T2 ON T1.id  =  T2.lost_in_battle JOIN death AS T3 ON T2.id  =  T3.caused_by_ship_id GROUP BY T1.id HAVING sum(T3.killed)  >  10;
