-- SPIDER: Show names of all high school students who do not have any friends.
-- DB: network_1 | Score: 6
SELECT name FROM Highschooler EXCEPT SELECT T2.name FROM Friend AS T1 JOIN Highschooler AS T2 ON T1.student_id  =  T2.id;
