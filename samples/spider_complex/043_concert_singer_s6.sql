-- SPIDER: What are the names of all stadiums that did not have a concert in 2014?
-- DB: concert_singer | Score: 6
SELECT name FROM stadium EXCEPT SELECT T2.name FROM concert AS T1 JOIN stadium AS T2 ON T1.stadium_id  =  T2.stadium_id WHERE T1.year  =  2014;
