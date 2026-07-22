-- SPIDER: Find the first name of students who have both cat and dog pets .
-- DB: pets_1 | Score: 8
select t1.fname from student as t1 join has_pet as t2 on t1.stuid  =  t2.stuid join pets as t3 on t3.petid  =  t2.petid where t3.pettype  =  'cat' intersect select t1.fname from student as t1 join has_pet as t2 on t1.stuid  =  t2.stuid join pets as t3 on t3.petid  =  t2.petid where t3.pettype  =  'dog';
