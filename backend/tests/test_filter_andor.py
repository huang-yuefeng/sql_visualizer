from app.services.sql_range_finder import find_sql_range

sql = """-- Step 2: Enrich customer data
INSERT INTO stg_customers (customer_id, full_name, is_active, segment, region)
SELECT c.customer_id, c.full_name, c.is_active, c.segment, c.region
FROM crm_customers c
WHERE c.is_active = 1
  AND c.region IN (SELECT region FROM active_regions);
"""

edge = {"edge_type": "FILTER", "source_label": "crm_customers", "target_label": "stg_customers"}
result = find_sql_range(edge, sql)
print(f"FILTER range: {result}")
if result:
    print(f"Lines: {result[0]}-{result[2]}")
    for i, line in enumerate(sql.split("\n"), 1):
        marker = ">>>" if result[0] <= i <= result[2] else "   "
        print(f"{marker} L{i}: {line}")
    assert result[2] >= 6, f"Expected at least line 6 (AND line), got {result[2]}"
    assert result[0] == 5, f"Expected line 5 (WHERE line), got {result[0]}"
    print("PASS: FILTER covers WHERE + AND continuation")
