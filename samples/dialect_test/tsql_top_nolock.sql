-- TSQL/SQL Server: TOP, NOLOCK, brackets
SELECT TOP 100
    o.[order_id],
    c.[customer_name],
    o.[total_amount],
    o.[order_date]
FROM [dbo].[orders] o WITH (NOLOCK)
INNER JOIN [dbo].[customers] c WITH (NOLOCK)
    ON o.[customer_id] = c.[customer_id]
WHERE o.[order_date] >= '2024-01-01'
ORDER BY o.[total_amount] DESC;
