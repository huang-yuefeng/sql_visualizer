-- SPIDER: What are the names of high schoolers who both have friends and are liked?
-- DB: network_1 | Score: 8
SELECT T2.name FROM Friend AS T1 JOIN Highschooler AS T2 ON T1.student_id  =  T2.id INTERSECT SELECT T2.name FROM Likes AS T1 JOIN Highschooler AS T2 ON T1.liked_id  =  T2.id;
