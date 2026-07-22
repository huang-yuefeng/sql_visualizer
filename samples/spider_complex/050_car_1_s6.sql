-- SPIDER: What are the name of the countries where there is not a single car maker?
-- DB: car_1 | Score: 6
SELECT CountryName FROM countries EXCEPT SELECT T1.CountryName FROM countries AS T1 JOIN CAR_MAKERS AS T2 ON T1.countryId  =  T2.Country;;
