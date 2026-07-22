-- SPIDER: Find the name of airports which do not have any flight in and out.
-- DB: flight_2 | Score: 6
SELECT AirportName FROM Airports WHERE AirportCode NOT IN (SELECT SourceAirport FROM Flights UNION SELECT DestAirport FROM Flights);
