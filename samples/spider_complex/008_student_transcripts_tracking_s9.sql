-- SPIDER: What is the id of the semester that had both Masters and Bachelors students enrolled?
-- DB: student_transcripts_tracking | Score: 9
SELECT DISTINCT T2.semester_id FROM Degree_Programs AS T1 JOIN Student_Enrolment AS T2 ON T1.degree_program_id  =  T2.degree_program_id WHERE degree_summary_name  =  'Master' INTERSECT SELECT DISTINCT T2.semester_id FROM Degree_Programs AS T1 JOIN Student_Enrolment AS T2 ON T1.degree_program_id  =  T2.degree_program_id WHERE degree_summary_name  =  'Bachelor';
