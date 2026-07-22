-- SPIDER: Give the names of countries with English and French as official languages.
-- DB: world_1 | Score: 8
SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code  =  T2.CountryCode WHERE T2.Language  =  "English" AND T2.IsOfficial  =  "T" INTERSECT SELECT T1.Name FROM country AS T1 JOIN countrylanguage AS T2 ON T1.Code  =  T2.CountryCode WHERE T2.Language  =  "French" AND T2.IsOfficial  =  "T";
