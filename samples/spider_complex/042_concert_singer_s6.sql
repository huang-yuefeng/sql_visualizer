-- SPIDER: Show names for all stadiums except for stadiums having a concert in year 2014.
-- DB: concert_singer | Score: 6
SELECT name FROM stadium EXCEPT SELECT T2.name FROM concert AS T1 JOIN stadium AS T2 ON T1.stadium_id  =  T2.stadium_id WHERE T1.year  =  2014;
