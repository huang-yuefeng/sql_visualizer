"""
SQL Field & Logical Operation Extractor v2
===========================================
Extended for complex financial/GPS domain SQL patterns:

  * CTE (WITH clause) - tracking CTE tables & internal conditions
  * Window functions - PARTITION BY, ORDER BY, frame specs
  * MERGE/UPSERT statements - source/target, ON, WHEN conditions
  * GROUP BY field extraction
  * ORDER BY field extraction (with sort direction)
  * Selected expressions - columns, functions, computed fields
  * UNION ALL / UNION - multi-source table aggregation
  * Function-level field extraction (COALESCE, CAST, CONCAT, etc.)
"""

import json
from pathlib import Path
from typing import Any, Optional

import sqlglot
from sqlglot import exp


# ══════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════

def _node_name(node: Optional[exp.Expression]) -> str:
    if node is None:
        return "NULL"
    return node.sql(dialect="mysql")


def _leaf_columns(
    node: exp.Expression,
    prune_types: tuple = (exp.Subquery, exp.Case),
) -> list[dict]:
    """Recursively extract all column references from an expression."""
    cols = []
    for child in node.walk(prune=lambda n: isinstance(n, prune_types)):
        if isinstance(child, exp.Column):
            table = child.table or ""
            cols.append({
                "table": table,
                "column": child.name,
                "full_name": child.sql(dialect="mysql"),
            })
    return cols


def _is_window_func(node: exp.Expression) -> bool:
    """Check if an expression is or wraps a window function."""
    for child in node.walk():
        if isinstance(child, exp.Window):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════
#  Condition extractors  (WHERE / HAVING / JOIN ON / CASE WHEN / MERGE ON)
# ══════════════════════════════════════════════════════════════════════════

def _extract_binary_op(op: exp.Binary, location: str) -> list[dict]:
    results = []
    cols = _leaf_columns(op.this)
    op_name = op.key.upper()
    right_sql = _node_name(op.expression)
    for col in cols:
        results.append({
            "field": col["full_name"], "table": col["table"],
            "column": col["column"], "operation": op_name,
            "value": right_sql, "location": location,
        })
    return results


def _extract_in(op: exp.In, location: str) -> list[dict]:
    results = []
    cols = _leaf_columns(op.this)
    if op.expressions:
        values = ", ".join(_node_name(v) for v in op.expressions)
    elif op.args.get("query"):
        values = _node_name(op.args["query"])
    else:
        values = ""
    for col in cols:
        results.append({
            "field": col["full_name"], "table": col["table"],
            "column": col["column"], "operation": "IN",
            "value": values, "location": location,
        })
    return results


def _extract_between(op: exp.Between, location: str) -> list[dict]:
    results = []
    cols = _leaf_columns(op.this)
    low = _node_name(op.args.get("low"))
    high = _node_name(op.args.get("high"))
    for col in cols:
        results.append({
            "field": col["full_name"], "table": col["table"],
            "column": col["column"], "operation": "BETWEEN",
            "value": f"{low} AND {high}", "location": location,
        })
    return results


def _extract_is(op: exp.Is, location: str) -> list[dict]:
    results = []
    cols = _leaf_columns(op.this)
    val = _node_name(op.expression)
    for col in cols:
        results.append({
            "field": col["full_name"], "table": col["table"],
            "column": col["column"], "operation": f"IS {val}",
            "value": val, "location": location,
        })
    return results


def _extract_like(op: exp.Like, location: str) -> list[dict]:
    results = []
    cols = _leaf_columns(op.this)
    pattern = _node_name(op.expression)
    op_name = "NOT LIKE" if op.args.get("negate") else "LIKE"
    for col in cols:
        results.append({
            "field": col["full_name"], "table": col["table"],
            "column": col["column"], "operation": op_name,
            "value": pattern, "location": location,
        })
    return results


# ══════════════════════════════════════════════════════════════════════════
#  Expression dispatcher
# ══════════════════════════════════════════════════════════════════════════

def extract_conditions(node: exp.Expression, location: str) -> list[dict]:
    """Recursively extract all logical conditions from an expression tree."""
    results: list[dict] = []

    if isinstance(node, exp.And):
        results.extend(extract_conditions(node.this, location))
        results.extend(extract_conditions(node.expression, location))
    elif isinstance(node, exp.Or):
        results.extend(extract_conditions(node.this, location))
        results.extend(extract_conditions(node.expression, location))
    elif isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.In):
            for r in _extract_in(inner, location):
                r["operation"] = "NOT IN"
                results.append(r)
        elif isinstance(inner, exp.Is):
            for r in _extract_is(inner, location):
                r["operation"] = r["operation"].replace("IS ", "IS NOT ")
                results.append(r)
        elif isinstance(inner, exp.Like):
            results.extend(_extract_like(inner, location))
        elif isinstance(inner, exp.Between):
            for r in _extract_between(inner, location):
                r["operation"] = "NOT BETWEEN"
                results.append(r)
        else:
            results.extend(extract_conditions(inner, f"NOT ({location})"))
    elif isinstance(node, exp.Paren):
        results.extend(extract_conditions(node.this, f"({location})"))
    elif isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        results.extend(_extract_binary_op(node, location))
    elif isinstance(node, exp.Like):
        results.extend(_extract_like(node, location))
    elif isinstance(node, exp.In):
        results.extend(_extract_in(node, location))
    elif isinstance(node, exp.Between):
        results.extend(_extract_between(node, location))
    elif isinstance(node, exp.Is):
        results.extend(_extract_is(node, location))
    elif isinstance(node, exp.Null):
        pass
    elif isinstance(node, exp.Boolean):
        pass
    elif isinstance(node, exp.Literal):
        pass
    elif isinstance(node, exp.Column):
        pass
    elif isinstance(node, exp.Exists):
        if node.this:
            subq = node.this
            subq_sql = subq.sql(dialect="mysql") if isinstance(subq, exp.Subquery) else _node_name(subq)
            results.append({
                "field": "EXISTS(subquery)", "table": "", "column": "",
                "operation": "EXISTS", "value": subq_sql[:200], "location": location,
            })
    elif isinstance(node, exp.Subquery):
        results.extend(extract_from_statement(node.this, location))
    elif isinstance(node, exp.Alias):
        results.extend(extract_conditions(node.this, location))
    elif isinstance(node, exp.Func):
        pass
    else:
        for col in _leaf_columns(node):
            results.append({
                "field": col["full_name"], "table": col["table"],
                "column": col["column"],
                "operation": node.key.upper() if node.key else "REF",
                "value": node.sql(dialect="mysql")[:200], "location": location,
            })
    return results


# ══════════════════════════════════════════════════════════════════════════
#  Enhanced extractors: GROUP BY, ORDER BY, Window, Selected Columns
# ══════════════════════════════════════════════════════════════════════════

def extract_group_by(statement: exp.Select, context: str) -> list[dict]:
    """Extract GROUP BY column references."""
    results = []
    group = statement.args.get("group")
    if group is None:
        return results
    for expr in group.expressions:
        cols = _leaf_columns(expr)
        for col in cols:
            results.append({
                "type": "group_by",
                "field": col["full_name"], "table": col["table"],
                "column": col["column"], "location": "GROUP BY",
            })
        # Also handle GROUPING SETS / ROLLUP / CUBE
        if isinstance(expr, (exp.Rollup, exp.Cube, exp.GroupingSets)):
            for sub_expr in (expr.expressions or []):
                for col in _leaf_columns(sub_expr):
                    results.append({
                        "type": "group_by",
                        "field": col["full_name"], "table": col["table"],
                        "column": col["column"],
                        "location": f"GROUP BY ({expr.key.upper()})",
                    })
    return results


def extract_order_by(statement: exp.Select, context: str) -> list[dict]:
    """Extract ORDER BY column references with sort direction."""
    results = []
    order = statement.args.get("order")
    if order is None:
        return results
    for expr in order.expressions:
        direction = "DESC" if isinstance(expr, exp.Ordered) and expr.args.get("desc") else "ASC"
        cols = _leaf_columns(expr)
        for col in cols:
            results.append({
                "type": "order_by",
                "field": col["full_name"], "table": col["table"],
                "column": col["column"], "direction": direction,
                "location": "ORDER BY",
            })
    return results


def extract_window_functions(statement: exp.Select, context: str) -> list[dict]:
    """Extract window function usage: function name, PARTITION BY, ORDER BY, alias."""
    results = []
    for win in (n for n in statement.walk(prune=lambda n: isinstance(n, exp.Subquery)) if isinstance(n, exp.Window)):
        func_node = win.this
        func_name = func_node.key.upper() if func_node.key else "WINDOW"

        partition_cols = []
        for pb in (win.args.get("partition_by") or []):
            for col in _leaf_columns(pb, prune_types=(exp.Subquery,)):
                partition_cols.append(col["full_name"])

        order_cols = []
        win_order = win.args.get("order")
        if win_order:
            for oe in win_order.expressions or [win_order]:
                direction = "DESC" if isinstance(oe, exp.Ordered) and oe.args.get("desc") else "ASC"
                for col in _leaf_columns(oe, prune_types=(exp.Subquery,)):
                    order_cols.append(f"{col['full_name']} {direction}")

        win_alias = ""
        for c in func_node.walk():
            if isinstance(c, exp.Alias) and c.alias:
                win_alias = c.alias
                break

        results.append({
            "type": "window",
            "function": func_name,
            "alias": win_alias,
            "partition_by": partition_cols,
            "order_by": order_cols,
            "frame_sql": _node_name(win.args.get("spec")) if win.args.get("spec") else "",
            "window_sql": win.sql(dialect="mysql")[:200],
            "location": "SELECT",
        })
    return results


def extract_selected_columns(statement: exp.Select, context: str) -> list[dict]:
    """Extract selected expressions: plain columns, functions, computed fields."""
    results = []
    for expr in statement.expressions:
        if expr is None:
            continue

        expr_sql = expr.sql(dialect="mysql")

        # Prune subquery/CASE to avoid deeply nested column overcounting
        for col in _leaf_columns(expr, prune_types=(exp.Subquery, exp.Case, exp.Window)):
            results.append({
                "type": "selected_field",
                "field": col["full_name"], "table": col["table"],
                "column": col["column"],
                "expression_type": _classify_expression(expr),
                "full_expression": expr_sql[:200],
                "location": "SELECT",
            })
    return results


def _classify_expression(expr: exp.Expression) -> str:
    """Classify what kind of SELECT expression this is."""
    if isinstance(expr, exp.Column):
        return "column"
    if isinstance(expr, exp.Alias):
        return _classify_expression(expr.this)
    if _is_window_func(expr):
        return "window"
    if isinstance(expr, exp.Case):
        return "case"
    if isinstance(expr, exp.Func):
        return f"function:{expr.key.lower()}"
    if isinstance(expr, exp.Literal):
        return "literal"
    if isinstance(expr, exp.Binary):
        return "computed"
    if isinstance(expr, exp.Subquery):
        return "subquery"
    return "other"


# ══════════════════════════════════════════════════════════════════════════
#  Function-level field extraction  (COALESCE, CAST, CONCAT, JSON_EXTRACT)
# ══════════════════════════════════════════════════════════════════════════

def extract_function_usage(statement: exp.Expression, context: str) -> list[dict]:
    """Extract columns used inside SQL functions (COALESCE, CAST, CONCAT, etc.).

    Prunes subqueries to avoid double-counting functions from sub-statement processing."""
    results = []
    for func in (n for n in statement.walk(prune=lambda n: isinstance(n, exp.Subquery)) if isinstance(n, exp.Func)):
        # Skip window function wrappers (handled separately)
        if isinstance(func, exp.Window):
            continue
        cols = _leaf_columns(func, prune_types=(exp.Subquery, exp.Case, exp.Window))
        for col in cols:
            results.append({
                "type": "function_field",
                "function": func.key.lower(),
                "field": col["full_name"], "table": col["table"],
                "column": col["column"],
                "expression": func.sql(dialect="mysql")[:200],
                "location": context,
            })
    return results


# ══════════════════════════════════════════════════════════════════════════
#  Top-level statement dispatcher  (enhanced)
# ══════════════════════════════════════════════════════════════════════════

_CTE_TABLE_MAP: dict[str, exp.Select] = {}
"""Global CTE table -> definition map, for cross-CTE references."""


def _collect_tables(statement: exp.Expression) -> list[str]:
    """Collect all table references from any statement."""
    tables = []
    for tbl in statement.find_all(exp.Table):
        name = tbl.name
        # Also report CTE tables
        if name in _CTE_TABLE_MAP:
            tables.append(f"CTE:{name}")
        else:
            tables.append(name)
    return tables


def extract_from_statement(
    statement: exp.Expression,
    context: str = "",
    cte_map: Optional[dict] = None,
) -> list[dict]:
    """Dispatch on statement type. Returns list of structured extraction dicts."""
    results: list[dict] = []

    # ── CTE / WITH ────────────────────────────────────────────────────
    with_ = statement.args.get("with_")
    if with_:
        cte_exprs = with_.args.get("expressions", [])
        for cte in cte_exprs:
            alias = cte.alias
            cte_body = cte.this
            if alias:
                _CTE_TABLE_MAP[alias] = cte_body if isinstance(cte_body, exp.Select) else None
            cte_tables = _collect_tables(cte_body) if cte_body else []
            results.append({
                "type": "cte_definition",
                "alias": alias,
                "tables": cte_tables,
                "cte_sql": _node_name(cte_body)[:200] if cte_body else "",
                "context": context,
            })
            if cte_body:
                results.extend(
                    extract_from_statement(cte_body, f"CTE:{alias}", cte_map)
                )

    # ── SELECT ────────────────────────────────────────────────────────
    if isinstance(statement, exp.Select):
        tables = _collect_tables(statement)
        results.append({"type": "tables", "tables": tables, "context": context})

        where = statement.args.get("where")
        if where:
            results.extend(extract_conditions(where.this, "WHERE"))

        for join in statement.args.get("joins") or []:
            on_expr = join.args.get("on")
            if on_expr:
                results.extend(extract_conditions(on_expr, "JOIN ON"))

        having = statement.args.get("having")
        if having:
            results.extend(extract_conditions(having.this, "HAVING"))

        for case in statement.find_all(exp.Case):
            for if_node in case.args.get("ifs", []):
                results.extend(
                    extract_conditions(if_node.this, "CASE WHEN (SELECT)")
                )

        results.extend(extract_group_by(statement, context))
        results.extend(extract_order_by(statement, context))
        results.extend(extract_window_functions(statement, context))
        results.extend(extract_selected_columns(statement, context))
        results.extend(extract_function_usage(statement, "SELECT"))

        for subq in statement.find_all(exp.Subquery):
            results.extend(
                extract_from_statement(subq.this, f"SUBQUERY ({context})", cte_map)
            )

    # ── UNION / UNION ALL ─────────────────────────────────────────────
    elif isinstance(statement, exp.Union):
        is_all = statement.args.get("distinct", True) is False
        label = "UNION ALL" if is_all else "UNION"
        results.append({"type": "union_info", "union_type": label, "context": context})
        results.extend(extract_from_statement(statement.this, f"{label} LEFT", cte_map))
        results.extend(extract_from_statement(statement.expression, f"{label} RIGHT", cte_map))

    # ── MERGE ─────────────────────────────────────────────────────────
    elif isinstance(statement, exp.Merge):
        target_node = statement.args.get("this")
        target_name = target_node.name if isinstance(target_node, exp.Table) else _node_name(target_node)

        using_node = statement.args.get("using")
        using_name = using_node.name if isinstance(using_node, exp.Table) else _node_name(using_node)

        # Collect target table name
        results.append({"type": "tables", "tables": [target_name], "context": context})
        results.append({
            "type": "merge_info",
            "target": target_name,
            "source": using_name,
            "context": context,
        })

        # MERGE ON condition
        on_cond = statement.args.get("on")
        if on_cond:
            results.extend(extract_conditions(on_cond, "MERGE ON"))

        # Extract tables/subqueries from USING clause
        if isinstance(using_node, exp.Subquery):
            results.extend(
                extract_from_statement(using_node.this, "MERGE USING SUBQUERY", cte_map)
            )

        # WHEN clauses
        for wh in statement.args.get("whens") or []:
            matched = "MATCHED" if wh.args.get("matched") else "NOT MATCHED"
            action_node = wh.args.get("then")
            action_type = action_node.key.upper() if action_node and action_node.key else "UNKNOWN"

            results.append({
                "type": "merge_when",
                "matched": matched,
                "action": action_type,
                "context": context,
            })

            # WHEN conditions (extra AND after WHEN MATCHED AND ...)
            when_cond = wh.args.get("condition")
            if when_cond:
                results.extend(extract_conditions(when_cond, f"MERGE WHEN {matched}"))

            # Extract SET clause column references from UPDATE action
            if action_node:
                for set_item in action_node.find_all(exp.EQ):
                    cols = _leaf_columns(set_item.this)
                    for col in cols:
                        results.append({
                            "field": col["full_name"], "table": col["table"],
                            "column": col["column"],
                            "operation": "MERGE SET",
                            "value": _node_name(set_item.expression),
                            "location": f"MERGE {matched} UPDATE",
                        })

    # ── UPDATE ────────────────────────────────────────────────────────
    elif isinstance(statement, exp.Update):
        tables = _collect_tables(statement)
        results.append({"type": "tables", "tables": tables, "context": context})
        where = statement.args.get("where")
        if where:
            results.extend(extract_conditions(where.this, "WHERE (UPDATE)"))
        for subq in statement.find_all(exp.Subquery):
            results.extend(
                extract_from_statement(subq.this, f"SUBQUERY ({context})", cte_map)
            )

    # ── DELETE ────────────────────────────────────────────────────────
    elif isinstance(statement, exp.Delete):
        tables = _collect_tables(statement)
        results.append({"type": "tables", "tables": tables, "context": context})
        where = statement.args.get("where")
        if where:
            results.extend(extract_conditions(where.this, "WHERE (DELETE)"))
        for subq in statement.find_all(exp.Subquery):
            results.extend(
                extract_from_statement(subq.this, f"SUBQUERY ({context})", cte_map)
            )

    # ── INSERT ────────────────────────────────────────────────────────
    elif isinstance(statement, exp.Insert):
        tables = _collect_tables(statement)
        results.append({"type": "tables", "tables": tables, "context": context})
        for subq in statement.find_all(exp.Subquery):
            results.extend(
                extract_from_statement(subq.this, f"SUBQUERY ({context})", cte_map)
            )

    # ── CREATE TABLE (DDL) ────────────────────────────────────────────
    elif isinstance(statement, exp.Create):
        tbl = statement.this
        if tbl and isinstance(tbl, exp.Table):
            results.append({
                "type": "ddl_create_table",
                "table": tbl.name,
                "context": context,
            })

    # ── UNSUPPORTED ───────────────────────────────────────────────────
    else:
        results.append({
            "type": "unsupported",
            "statement_type": statement.key,
            "sql": statement.sql(dialect="mysql")[:150],
            "context": context,
        })

    return results


# ══════════════════════════════════════════════════════════════════════════
#  Entry point & summarization
# ══════════════════════════════════════════════════════════════════════════

def parse_sql(sql_text: str, label: str = "") -> dict:
    global _CTE_TABLE_MAP
    _CTE_TABLE_MAP.clear()

    parsed = sqlglot.parse(sql_text, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE)
    all_results: list[dict] = []

    for statement in parsed:
        if statement is None:
            continue
        try:
            all_results.extend(extract_from_statement(statement, "TOP"))
        except Exception as e:
            all_results.append({
                "type": "error", "message": str(e),
                "sql": statement.sql(dialect="mysql")[:200],
            })

    return {"script": label, "raw_operations": all_results}


def summarize(results: dict) -> dict:
    ops = results.get("raw_operations", [])
    all_tables: list[str] = []
    ctes: list[dict] = []
    where_ops: list[dict] = []
    join_ops: list[dict] = []
    having_ops: list[dict] = []
    case_ops: list[dict] = []
    group_by_fields: list[dict] = []
    order_by_fields: list[dict] = []
    window_funcs: list[dict] = []
    selected_fields: list[dict] = []
    function_fields: list[dict] = []
    merge_info: list[dict] = []
    union_info: list[dict] = []

    for item in ops:
        t = item.get("type", "")

        if t == "tables":
            all_tables.extend(item.get("tables", []))
        elif t == "cte_definition":
            ctes.append(item)
        elif t in ("group_by",):
            group_by_fields.append(item)
        elif t in ("order_by",):
            order_by_fields.append(item)
        elif t == "window":
            window_funcs.append(item)
        elif t == "selected_field":
            selected_fields.append(item)
        elif t == "function_field":
            function_fields.append(item)
        elif t in ("merge_info", "merge_when",):
            merge_info.append(item)
        elif t == "union_info":
            union_info.append(item)
        elif "field" in item and item.get("operation"):
            loc = item.get("location", "")
            if "JOIN" in loc:
                join_ops.append(item)
            elif "HAVING" in loc:
                having_ops.append(item)
            elif "CASE" in loc:
                case_ops.append(item)
            elif "MERGE" in loc:
                merge_info.append(item)
            else:
                where_ops.append(item)

    return {
        "script": results["script"],
        "tables": sorted(set(all_tables)),
        "ctes": ctes,
        "conditions": {
            "where": where_ops,
            "join_on": join_ops,
            "having": having_ops,
            "case_when": case_ops,
        },
        "group_by_fields": group_by_fields,
        "order_by_fields": order_by_fields,
        "window_functions": window_funcs,
        "selected_fields": selected_fields,
        "function_fields": function_fields,
        "merge_operations": merge_info,
        "union_operations": union_info,
        "field_operations": where_ops + join_ops + having_ops + case_ops,
        "table_details": _table_field_summary(where_ops + join_ops),
    }


def _table_field_summary(field_ops: list[dict]) -> dict:
    table_map: dict[str, dict] = {}
    for op in field_ops:
        tbl = op.get("table") or "(implicit)"
        col = op.get("column", "")
        if tbl not in table_map:
            table_map[tbl] = {}
        if col not in table_map[tbl]:
            table_map[tbl][col] = {"operations": []}
        table_map[tbl][col]["operations"].append({
            "op": op["operation"],
            "value": op.get("value", ""),
            "location": op.get("location", ""),
        })
    return table_map


# ══════════════════════════════════════════════════════════════════════════
#  CLI entry point
# ══════════════════════════════════════════════════════════════════════════

def main():
    base_dir = Path(__file__).parent / "samples"
    all_sql_files = sorted(base_dir.rglob("*.sql"))

    if not all_sql_files:
        print(f"No SQL files found in {base_dir}")
        return

    all_results = []
    for fpath in all_sql_files:
        if fpath.name == "tables.sql" or fpath.name == "tables_financial.sql":
            continue

        print(f"\n{'='*70}")
        print(f"Processing: {fpath.relative_to(base_dir)}")
        print(f"{'='*70}")

        sql_text = fpath.read_text()
        result = parse_sql(sql_text, label=str(fpath.relative_to(base_dir)))
        summary = summarize(result)
        all_results.append(summary)

        print(f"  Tables:            {', '.join(summary['tables'][:12]) or '(none)'}{' ...' if len(summary['tables']) > 12 else ''}")
        print(f"  CTEs:              {len(summary['ctes'])}")
        print(f"  Conditions (WHERE):  {len(summary['conditions']['where'])}")
        print(f"  Conditions (JOIN):   {len(summary['conditions']['join_on'])}")
        print(f"  Conditions (HAVING): {len(summary['conditions']['having'])}")
        print(f"  Conditions (CASE):   {len(summary['conditions']['case_when'])}")
        print(f"  GROUP BY fields:   {len(summary['group_by_fields'])}")
        print(f"  ORDER BY fields:   {len(summary['order_by_fields'])}")
        print(f"  Window functions:  {len(summary['window_functions'])}")
        print(f"  Selected fields:   {len(summary['selected_fields'])}")
        print(f"  Func fields:       {len(summary['function_fields'])}")
        print(f"  Merge operations:  {len(summary['merge_operations'])}")
        print(f"  Union operations:  {len(summary['union_operations'])}")

        if summary["window_functions"]:
            print(f"  ── Window Functions ──")
            for w in summary["window_functions"]:
                print(f"    {w['function']:20s} PARTITION BY: {w['partition_by']}  ORDER BY: {w['order_by']}")

        if summary["group_by_fields"]:
            print(f"  ── GROUP BY ──")
            for g in summary["group_by_fields"]:
                print(f"    {g['field']}")

        if summary["order_by_fields"]:
            print(f"  ── ORDER BY ──")
            for o in summary["order_by_fields"]:
                print(f"    {o['field']:30s} {o['direction']}")

        if summary["conditions"]["where"]:
            print(f"  ── WHERE Conditions ──")
            for op in summary["conditions"]["where"][:15]:
                print(f"    [{op['location']:25s}] {op['field']:32s} {op['operation']:14s} {str(op['value'])[:60]}")

    out_path = Path(__file__).parent / "extraction_result_v2.json"
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n{'='*70}")
    print(f"Full JSON result saved to: {out_path}")


if __name__ == "__main__":
    main()
