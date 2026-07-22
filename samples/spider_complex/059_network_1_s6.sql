-- SPIDER: What are the names of students who have no friends?
-- DB: network_1 | Score: 6
SELECT name FROM Highschooler EXCEPT SELECT T2.name FROM Friend AS T1 JOIN Highschooler AS T2 ON T1.student_id  =  T2.id;
