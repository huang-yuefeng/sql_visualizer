-- Oracle-style: DECODE, NVL, CONNECT BY
SELECT
    e.employee_id,
    e.first_name || ' ' || e.last_name AS full_name,
    DECODE(e.status, 'A', 'Active', 'I', 'Inactive', 'Unknown') AS status_desc,
    NVL(e.salary, 0) AS salary,
    NVL(e.commission_pct, 0.05) AS commission,
    e.manager_id,
    LEVEL AS org_level
FROM employees e
START WITH e.manager_id IS NULL
CONNECT BY PRIOR e.employee_id = e.manager_id
ORDER SIBLINGS BY e.last_name;
