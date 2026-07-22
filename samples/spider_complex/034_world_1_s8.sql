-- SPIDER: What are the countries where either English or Dutch is the official language ?
-- DB: world_1 | Score: 8
select t1.name from country as t1 join countrylanguage as t2 on t1.code  =  t2.countrycode where t2.language  =  "english" and isofficial  =  "t" union select t1.name from country as t1 join countrylanguage as t2 on t1.code  =  t2.countrycode where t2.language  =  "dutch" and isofficial  =  "t";
