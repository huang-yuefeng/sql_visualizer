-- SPIDER: Which airports do not have departing or arriving flights?
-- DB: flight_2 | Score: 6
SELECT AirportName FROM Airports WHERE AirportCode NOT IN (SELECT SourceAirport FROM Flights UNION SELECT DestAirport FROM Flights);
