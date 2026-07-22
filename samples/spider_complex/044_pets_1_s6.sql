-- SPIDER: Find the major and age of students who do not have a cat pet.
-- DB: pets_1 | Score: 6
SELECT major ,  age FROM student WHERE stuid NOT IN (SELECT T1.stuid FROM student AS T1 JOIN has_pet AS T2 ON T1.stuid  =  T2.stuid JOIN pets AS T3 ON T3.petid  =  T2.petid WHERE T3.pettype  =  'cat');
