-- SPIDER: which countries' tv channels are not playing any cartoon written by Todd Casey?
-- DB: tvshow | Score: 7
SELECT country FROM TV_Channel EXCEPT SELECT T1.country FROM TV_Channel AS T1 JOIN cartoon AS T2 ON T1.id = T2.Channel WHERE T2.written_by  =  'Todd Casey';
