-- SPIDER: Which countries have either English or Dutch as an official language?
-- DB: world_1 | Score: 8
SELECT * FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code  =  T2.CountryCode WHERE T2.Language  =  "English" AND IsOfficial  =  "T" UNION SELECT * FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code  =  T2.CountryCode WHERE T2.Language  =  "Dutch" AND IsOfficial  =  "T";
