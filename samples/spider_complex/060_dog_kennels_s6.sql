-- SPIDER: Which dogs have not cost their owner more than 1000 for treatment ? List the dog names .
-- DB: dog_kennels | Score: 6
select name from dogs where dog_id not in ( select dog_id from treatments group by dog_id having sum(cost_of_treatment)  >  1000 );
