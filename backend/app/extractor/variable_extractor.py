"""
Variable Extractor — extract and classify variables from SQL AST.

Walks a sqlglot-parsed AST to identify every variable (named reference)
and classify it as a database table field, CTE column, intermediate variable,
window result, aggregate, CASE result, function result, etc.
"""

import re
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from app.models.variable import VariableDefinition, VariableType


# ── Aggregation function names ─────────────────────────────────────────

_AGGREGATE_FUNCTIONS = {
    "sum", "count", "avg", "min", "max",
    "group_concat", "stddev", "variance", "stddev_pop", "stddev_samp",
    "var_pop", "var_samp", "bit_and", "bit_or", "bit_xor",
}

_WINDOW_ONLY_FUNCTIONS = {
    "row_number", "rownumber", "rank", "dense_rank", "denserank",
    "percent_rank", "percentrank", "cume_dist", "cumedist",
    "ntile", "lag", "lead", "first_value", "firstvalue",
    "last_value", "lastvalue", "nth_value", "nthvalue",
}


# ── Main extractor ─────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """The result of extracting variables from a SQL script."""
    script_name: str
    variables: list[VariableDefinition] = field(default_factory=list)


def _make_id(script_name: str, context: str, name: str, suffix: int = 0) -> str:
    """Create a deterministic variable ID."""
    base = f"{script_name}:{context}:{name}"
    if suffix:
        base = f"{base}_{suffix}"
    return hashlib.md5(base.encode()).hexdigest()[:16]


def _clean_name(name: str) -> str:
    """Strip quotes and backticks from a name."""
    name = name.strip()
    if (name.startswith('"') and name.endswith('"')) or \
       (name.startswith("'") and name.endswith("'")) or \
       (name.startswith("`") and name.endswith("`")):
        name = name[1:-1]
    return name


def _is_aggregate(expr: exp.Expression) -> bool:
    """Check if an expression is an aggregate function call."""
    if isinstance(expr, exp.AggFunc):
        return True
    if isinstance(expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max,
                          exp.Stddev, exp.Variance, exp.GroupConcat)):
        return True
    return False


def _is_window_function(expr: exp.Expression) -> bool:
    """Check if an expression contains a window function."""
    if isinstance(expr, exp.Window):
        return True
    # Check if any child is a window
    for node in expr.walk():
        if isinstance(node, exp.Window):
            return True
        if isinstance(node, exp.Anonymous):
            name = (node.name or "").upper()
            if name in _WINDOW_ONLY_FUNCTIONS:
                return True
    return False


def _is_aggregate_or_window(expr: exp.Expression) -> tuple[bool, bool]:
    """Return (is_agg, is_window) for an expression."""
    is_win = False
    is_agg = False
    for node in expr.walk():
        if isinstance(node, exp.Window):
            is_win = True
        name = ""
        if isinstance(node, (exp.Anonymous,)):
            name = (node.name or "").upper()
        elif hasattr(node, "sql_name"):
            try:
                name = node.sql_name().upper()
            except Exception:
                pass
        if name in _WINDOW_ONLY_FUNCTIONS:
            is_win = True
        if name in _AGGREGATE_FUNCTIONS:
            is_agg = True
        if _is_aggregate(node):
            is_agg = True
    return is_agg, is_win


def _classify_select_expression(expr: exp.Expression) -> list[VariableType]:
    """Classify a SELECT expression into one or more variable types.

    Priority order (first match wins for top-level expressions):
      1. Subquery     → SUBQUERY_RESULT  (highest priority)
      2. Window func  → WINDOW_RESULT
      3. Aggregate    → AGGREGATE
      4. CASE         → CASE_RESULT
      5. Known func   → FUNCTION_RESULT  (COALESCE, CAST, CONCAT, etc.)
      6. Literal      → LITERAL
      7. Bare Column  → TABLE_COLUMN
      8. Default      → INTERMEDIATE

    A subquery containing an aggregate inside should be SUBQUERY_RESULT,
    not AGGREGATE — the subquery is the container.
    """
    # Subquery takes highest priority — it wraps anything else inside
    if isinstance(expr, exp.Subquery):
        return [VariableType.SUBQUERY]

    is_agg, is_win = _is_aggregate_or_window(expr)

    if is_win:
        return [VariableType.WINDOW]

    if is_agg:
        return [VariableType.AGGREGATE]

    if isinstance(expr, exp.Case):
        return [VariableType.CASE]

    if isinstance(expr, (exp.Coalesce, exp.Cast, exp.Concat, exp.JSONExtract,
                          exp.If, exp.Nullif, exp.Greatest, exp.Least,
                          exp.DateAdd, exp.DateSub, exp.DateDiff,
                          exp.TsOrDsAdd, exp.TsOrDsDiff)):
        return [VariableType.TRANSFORM]

    if isinstance(expr, exp.Anonymous):
        name = (expr.name or "").upper()
        if name not in _AGGREGATE_FUNCTIONS and name not in _WINDOW_ONLY_FUNCTIONS:
            return [VariableType.TRANSFORM]

    # Generic function (Func but not a known specific type)
    if isinstance(expr, exp.Func) and not isinstance(expr, (
        exp.AggFunc, exp.Case, exp.Coalesce, exp.Cast, exp.Concat,
        exp.JSONExtract, exp.If, exp.Nullif, exp.Greatest, exp.Least,
        exp.DateAdd, exp.DateSub, exp.DateDiff, exp.TsOrDsAdd, exp.TsOrDsDiff,
        exp.Column,  # Column inherits from Func in some sqlglot versions
    )):
        return [VariableType.TRANSFORM]

    if isinstance(expr, exp.Literal):
        return [VariableType.LITERAL]

    # Bare column reference
    if isinstance(expr, exp.Column):
        return [VariableType.COLUMN]

    # Default: computed / intermediate
    return [VariableType.EXPRESSION]


def _extract_source_columns(expr: exp.Expression) -> list[str]:
    """Extract table.column references from an expression."""
    cols = []
    if expr is None or not hasattr(expr, 'walk'):
        return cols
    try:
        for node in expr.walk(prune=lambda n: isinstance(n, (exp.Subquery, exp.Case))):
            if isinstance(node, exp.Column):
                table = node.table or ""
                col_name = node.name or ""
                if table:
                    cols.append(f"{table}.{col_name}")
                else:
                    cols.append(col_name)
    except Exception:
        pass
    return list(set(cols))


def _extract_source_table_names(expr: exp.Expression) -> list[str]:
    """Extract table references from an expression."""
    tables = set()
    for node in expr.walk():
        if isinstance(node, exp.Table):
            name = node.name or ""
            if name:
                tables.add(name)
    return list(tables)


def _try_sql(expr) -> str:
    """Try to render an expression as SQL; return empty string on failure."""
    if expr is None:
        return ""
    try:
        return expr.sql(dialect="mysql")
    except Exception:
        return ""


def extract_variables_from_sql(
    sql_text: str, script_name: str
) -> ExtractionResult:
    """Main entry point: extract all variables from a SQL script.

    Args:
        sql_text: The SQL script text.
        script_name: A label for the script (used in variable IDs).

    Returns:
        ExtractionResult containing the list of VariableDefinitions.
    """
    result = ExtractionResult(script_name=script_name)

    try:
        parsed = sqlglot.parse(sql_text, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE)
    except Exception:
        # Try parsing each statement separately
        statements = sql_text.split(";")
        parsed = []
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                try:
                    parsed.extend(sqlglot.parse(stmt, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE))
                except Exception:
                    pass

    if not parsed:
        return result

    extractor = _StatementVariableExtractor(result, script_name, sql_text)
    for statement in parsed:
        if statement is None:
            continue
        extractor.extract_from_statement(statement, "TOP")

    return result


class _StatementVariableExtractor:
    """Internal class that walks statements and extracts variables."""

    def __init__(self, result: ExtractionResult, script_name: str, sql_text: str):
        self.result = result
        self.script_name = script_name
        self.sql_text = sql_text
        self._id_counters: dict[str, int] = {}
        self._cte_aliases: set[str] = set()
        self._cte_context: Optional[str] = None  # Current CTE context

    def _next_id(self, base: str) -> str:
        """Generate a unique variable ID."""
        self._id_counters[base] = self._id_counters.get(base, 0) + 1
        suffix = self._id_counters[base]
        return _make_id(self.script_name, base, base, suffix)

    def _find_line_number(self, expr_sql: str) -> tuple[int, int]:
        """Find the approximate line numbers for a SQL expression in the source."""
        if not expr_sql or not self.sql_text:
            return 0, 0

        # Try to find the expression in the source text
        lines = self.sql_text.split("\n")
        search = expr_sql.strip()[:60]  # First 60 chars as search key

        if not search:
            return 0, 0

        for i, line in enumerate(lines, start=1):
            if search[:20] in line:
                return i, i

        return 0, 0

    def _add_variable(
        self,
        name: str,
        var_type: VariableType,
        sql_expression: str = "",
        defined_in: str = "",
        context: str = "TOP",
        source_columns: list[str] | None = None,
        source_tables: list[str] | None = None,
        is_output: bool = False,
    ) -> VariableDefinition:
        """Create and add a VariableDefinition to the result."""
        line_start, line_end = self._find_line_number(sql_expression)
        var_id = self._next_id(f"{context}:{name}")
        var = VariableDefinition(
            id=var_id,
            name=name,
            variable_type=var_type,
            sql_expression=sql_expression,
            source_columns=source_columns or [],
            source_tables=source_tables or [],
            defined_in=defined_in,
            line_start=line_start,
            line_end=line_end,
            context=context,
            is_output=is_output,
        )
        self.result.variables.append(var)
        return var

    def _collect_table_references(self, node: exp.Expression) -> list[str]:
        """Collect all table references from an expression tree."""
        tables = []
        for child in node.walk():
            if isinstance(child, exp.Table):
                name = (child.alias or child.name or "")
                if name:
                    tables.append(name)
        return tables

    def extract_from_statement(self, statement: exp.Expression, context: str):
        """Dispatch to the appropriate handler based on statement type."""
        # Process CTE/WITH clause first — can appear on any statement type
        with_clause = statement.args.get("with") or statement.args.get("with_")
        if with_clause:
            self._extract_cte(with_clause)

        if isinstance(statement, exp.Select):
            self._extract_select(statement, context)
        elif isinstance(statement, exp.Union):
            self._extract_union(statement, context)
        elif isinstance(statement, exp.Intersect):
            self._extract_intersect(statement, context)
        elif isinstance(statement, exp.Except):
            self._extract_except(statement, context)
        elif isinstance(statement, exp.Merge):
            self._extract_merge(statement, context)
        elif isinstance(statement, exp.Insert):
            self._extract_insert(statement, context)
        elif isinstance(statement, exp.Update):
            self._extract_select(statement, context)
        elif isinstance(statement, exp.Delete):
            self._extract_select(statement, context)
        elif isinstance(statement, exp.Create):
            self._extract_create(statement, context)
        elif isinstance(statement, exp.CTE):
            self._extract_cte_as_statement(statement, context)
        # For other types, try generic extraction
        else:
            self._extract_generic(statement, context)

    def _extract_select(self, select: exp.Select, context: str, is_cte: bool = False):
        """Extract variables from a SELECT statement."""
        # Extract FROM tables
        from_exp = select.args.get("from") or select.args.get("from_")
        if from_exp:
            self._extract_from_clause(from_exp, context)

        # Extract JOIN tables (including LATERAL / CROSS JOIN LATERAL)
        joins = select.args.get("joins") or []
        for join in joins:
            join_expr = join.this
            lateral_alias = None
            # Unwrap Lateral wrapper (CROSS JOIN LATERAL (...))
            if isinstance(join_expr, exp.Lateral):
                lateral_alias = join_expr.alias_or_name or join_expr.alias or ""
                join_expr = join_expr.this
            if isinstance(join_expr, exp.Table):
                self._extract_from_clause(join_expr, context)
            elif isinstance(join_expr, exp.Subquery):
                # LATERAL (SELECT ...) or plain subquery in JOIN
                inner_select = join_expr.this
                sub_alias = join_expr.alias or lateral_alias or ""
                if sub_alias:
                    self._add_variable(
                        name=sub_alias,
                        var_type=VariableType.SUBQUERY,
                        sql_expression=_try_sql(inner_select),
                        defined_in=f"JOIN:{context}",
                        context=context,
                    )
                if isinstance(inner_select, exp.Select):
                    self._extract_select(inner_select, context)
            # JOIN ON conditions
            on_expr = join.args.get("on")
            if on_expr:
                self._extract_condition_columns(on_expr, context)

        # Extract WHERE conditions
        where = select.args.get("where")
        if where:
            self._extract_condition_columns(where, context)

        # Extract HAVING
        having = select.args.get("having")
        if having:
            self._extract_condition_columns(having, context)

        # Extract SELECT expressions
        expressions = select.expressions or []
        for expr in expressions:
            # Get the actual expression to classify.
            # IMPORTANT: only unwrap Alias nodes. Other nodes (Sum, Column, Case,
            # Coalesce, etc.) ARE the expression — their .this is a child argument,
            # not a wrapper to discard.
            inner = expr
            if isinstance(expr, exp.Alias):
                inner = expr.this
            if inner is None:
                continue
            # Skip plain strings (literal values in INSERT ... SELECT)
            if isinstance(inner, str):
                self._add_variable(
                    name=inner,
                    var_type=VariableType.LITERAL,
                    sql_expression=inner,
                    defined_in=context,
                    context=context,
                    is_output=(not is_cte),
                )
                continue
            if not hasattr(inner, 'walk'):
                continue

            alias = expr.alias or ""
            sql_expr = _try_sql(inner)
            src_cols = _extract_source_columns(inner)
            src_tables = _extract_source_table_names(inner)
            var_types = _classify_select_expression(inner)

            # Auto-name for un-aliased expressions
            if not alias:
                # Use column name for bare columns, or truncated SQL for complex exprs
                if isinstance(inner, exp.Column):
                    tbl = inner.table or ""
                    col = inner.name or ""
                    alias = f"{tbl}.{col}" if tbl else col
                else:
                    # Auto-name from SQL: truncate to first 30 chars, replace special chars
                    raw = _try_sql(inner).strip()
                    alias = raw[:30].replace(" ", "_").replace("(", "").replace(")", "").replace(",", "_").replace("'", "")
                    if not alias:
                        alias = "expr"

            defined_in = context
            if is_cte:
                defined_in = f"CTE:{self._cte_context}" if self._cte_context else "CTE"

            for vt in var_types:
                # Preserve detailed type even inside CTEs.
                # CTE context is captured in defined_in / context fields.
                actual_type = vt
                if is_cte and vt == VariableType.EXPRESSION:
                    # "Bare" intermediate inside a CTE → CTE_COLUMN
                    actual_type = VariableType.CTE_COLUMN

                self._add_variable(
                    name=alias,
                    var_type=actual_type,
                    sql_expression=sql_expr,
                    defined_in=defined_in,
                    context=context,
                    source_columns=src_cols,
                    source_tables=src_tables,
                    is_output=(not is_cte),
                )

        # Extract GROUP BY
        group = select.args.get("group")
        if group:
            for expr in (group.expressions or []):
                inner = expr.unnest() if hasattr(expr, 'unnest') else expr
                cols = _extract_source_columns(inner)
                for c in cols:
                    self._add_variable(
                        name=c,
                        var_type=VariableType.COLUMN,
                        sql_expression=_try_sql(inner),
                        defined_in="GROUP BY",
                        context=context,
                        source_columns=[c],
                    )

        # Extract ORDER BY
        order = select.args.get("order")
        if order:
            for expr in (order.expressions or []):
                inner = expr.unnest() if hasattr(expr, 'unnest') else expr
                cols = _extract_source_columns(inner)
                for c in cols:
                    self._add_variable(
                        name=c,
                        var_type=VariableType.COLUMN,
                        sql_expression=_try_sql(inner),
                        defined_in="ORDER BY",
                        context=context,
                        source_columns=[c],
                    )

        # Handle CTEs recursively (only if not already processed by extract_from_statement)
        # For top-level statements, CTEs are processed in extract_from_statement.
        # For subqueries and nested SELECTs, we need to process them here.
        if not is_cte:  # is_cte means we're already inside CTE processing
            with_clause = select.args.get("with") or select.args.get("with_")
            if with_clause:
                self._extract_cte(with_clause)

    def _extract_from_clause(self, from_exp: exp.Expression, context: str):
        """Extract table references from FROM/JOIN clauses."""
        # Unwrap From node
        if isinstance(from_exp, exp.From):
            from_exp = from_exp.this

        if isinstance(from_exp, exp.Table):
            name = _clean_name(from_exp.name or "")
            alias = from_exp.alias_or_name or name

            # Check if this is a CTE reference or physical table
            if name in self._cte_aliases:
                # Reference to a CTE — already extracted
                pass
            else:
                # Physical database table
                self._add_variable(
                    name=name,
                    var_type=VariableType.TABLE,
                    sql_expression=name,
                    defined_in="FROM",
                    context=context,
                )
                if alias and alias != name:
                    self._add_variable(
                        name=f"{alias}",
                        var_type=VariableType.TABLE,
                        sql_expression=f"{name} AS {alias}",
                        defined_in="FROM",
                        context=context,
                        source_tables=[name],
                    )
        elif isinstance(from_exp, exp.Subquery):
            self._extract_select(from_exp.this, context)

    def _extract_condition_columns(self, node: exp.Expression, context: str):
        """Extract column references from WHERE/HAVING/JOIN ON conditions."""
        for child in node.walk(prune=lambda n: isinstance(n, (exp.Subquery,))):
            if isinstance(child, exp.Column):
                table = child.table or ""
                col_name = child.name or ""
                sql = _try_sql(child)
                full = f"{table}.{col_name}" if table else col_name
                self._add_variable(
                    name=full,
                    var_type=VariableType.COLUMN,
                    sql_expression=sql,
                    defined_in="condition",
                    context=context,
                    source_columns=[full],
                )

    def _extract_cte(self, with_clause):
        """Extract CTE definitions from a WITH clause."""
        cte_list = []
        if hasattr(with_clause, 'expressions'):
            cte_list = with_clause.expressions
        elif isinstance(with_clause, exp.CTE):
            cte_list = [with_clause]

        for cte_def in cte_list:
            if isinstance(cte_def, exp.CTE):
                alias = getattr(cte_def, 'alias_or_name', '') or str(cte_def.alias or '')
                self._cte_aliases.add(alias)
                self._cte_context = alias

                # Add CTE_TABLE variable
                self._add_variable(
                    name=alias,
                    var_type=VariableType.CTE,
                    sql_expression=_try_sql(cte_def),
                    defined_in=f"CTE:{alias}",
                    context="TOP",
                )

                # Extract inner SELECT as CTE columns
                inner = cte_def.this
                if isinstance(inner, exp.Select):
                    self._extract_select(inner, f"CTE:{alias}", is_cte=True)
                elif isinstance(inner, exp.Union):
                    self._extract_union(inner, f"CTE:{alias}", is_cte=True)
                elif isinstance(inner, exp.Intersect):
                    self._extract_intersect(inner, f"CTE:{alias}")
                elif isinstance(inner, exp.Except):
                    self._extract_except(inner, f"CTE:{alias}")

                self._cte_context = None

    def _extract_cte_as_statement(self, cte: exp.CTE, context: str):
        """Handle a CTE at the top level."""
        self._extract_cte(cte)
        # Also extract the main query following the CTE
        if hasattr(cte, 'this') and cte.this:
            self.extract_from_statement(cte.this, context)

    def _extract_union(self, union: exp.Union, context: str, is_cte: bool = False):
        """Extract from UNION / UNION ALL."""
        union_type = "UNION ALL" if getattr(union, 'distinct', True) is False else "UNION"

        # Extract both sides
        for i, side in enumerate([union.left, union.right] if hasattr(union, 'left') else [union.this, union.expression]):
            if side is None:
                continue
            branch_name = f"union_branch_{i + 1}"
            branch_var = self._add_variable(
                name=branch_name,
                var_type=VariableType.UNION_BRANCH,
                sql_expression=_try_sql(side),
                defined_in=union_type,
                context=context,
            )
            self.extract_from_statement(side, context)

    def _extract_intersect(self, intersect: exp.Intersect, context: str):
        """Extract from INTERSECT statements."""
        self._add_variable(
            name="intersect_result",
            var_type=VariableType.UNION_BRANCH,
            sql_expression=_try_sql(intersect),
            defined_in="INTERSECT",
            context=context,
        )
        for side in [intersect.this, intersect.expression]:
            if side is not None:
                self.extract_from_statement(side, context)

    def _extract_except(self, except_stmt: exp.Except, context: str):
        """Extract from EXCEPT statements."""
        self._add_variable(
            name="except_result",
            var_type=VariableType.UNION_BRANCH,
            sql_expression=_try_sql(except_stmt),
            defined_in="EXCEPT",
            context=context,
        )
        for side in [except_stmt.this, except_stmt.expression]:
            if side is not None:
                self.extract_from_statement(side, context)

    def _extract_merge(self, merge: exp.Merge, context: str):
        """Extract from MERGE INTO statements."""
        # Target table — sqlglot puts it in 'this' (the MERGE target is the 'this' of the statement)
        target = merge.args.get("target") or merge.args.get("this")
        if target and isinstance(target, exp.Table):
            target_name = _clean_name(target.name or "")
            target_alias = target.alias_or_name or target_name
            self._add_variable(
                name=target_name,
                var_type=VariableType.MERGE_TARGET,
                sql_expression=_try_sql(target),
                defined_in="MERGE",
                context=context,
            )
            # Also add the alias if present
            if target_alias != target_name:
                self._add_variable(
                    name=target_alias,
                    var_type=VariableType.MERGE_TARGET,
                    sql_expression=f"{target_name} AS {target_alias}",
                    defined_in="MERGE",
                    context=context,
                    source_tables=[target_name],
                )

        # Source table/subquery
        using = merge.args.get("using")
        if using:
            if isinstance(using, exp.Table):
                src_name = _clean_name(using.name or "")
                self._add_variable(
                    name=src_name,
                    var_type=VariableType.TABLE,
                    sql_expression=_try_sql(using),
                    defined_in="MERGE USING",
                    context=context,
                )
            elif isinstance(using, exp.Subquery):
                self._extract_select(using.this, f"MERGE USING:{context}")

        # MERGE ON condition
        on_expr = merge.args.get("on")
        if on_expr:
            self._extract_condition_columns(on_expr, context)

        # WHEN clauses
        expressions = merge.args.get("expressions") or []
        for when_clause in expressions:
            when_matched = getattr(when_clause, 'matched', True)
            action = "UPDATE" if getattr(when_clause, 'args', {}).get('kind') == 'update' else "INSERT"

            # SET values
            if hasattr(when_clause, 'this') and when_clause.this:
                inner = when_clause.this
                cols = _extract_source_columns(inner)
                for c in cols:
                    self._add_variable(
                        name=c,
                        var_type=VariableType.COLUMN,
                        sql_expression=_try_sql(inner),
                        defined_in=f"MERGE {'MATCHED' if when_matched else 'NOT MATCHED'} {action}",
                        context=context,
                        source_columns=[c],
                    )

    def _extract_insert(self, insert: exp.Insert, context: str):
        """Extract from INSERT INTO statements."""
        into = insert.args.get("into") or insert.args.get("this")
        # Schema wraps Table + column list in INSERT INTO table(col1, col2, ...)
        if isinstance(into, exp.Schema):
            into = into.this
        if isinstance(into, exp.Table):
            name = _clean_name(into.name or "")
            self._add_variable(
                name=name,
                var_type=VariableType.TABLE,
                sql_expression=_try_sql(into),
                defined_in="INSERT INTO",
                context=context,
            )

        # Extract the SELECT part
        expression = insert.args.get("expression")
        if expression and isinstance(expression, exp.Select):
            self._extract_select(expression, context)

    def _extract_create(self, create: exp.Create, context: str):
        """Extract from CREATE TABLE statements."""
        if create.args.get("kind", "").upper() == "TABLE":
            table_expr = create.args.get("this")
            if table_expr:
                name = _clean_name(table_expr.name or "")
                self._add_variable(
                    name=name,
                    var_type=VariableType.TABLE,
                    sql_expression=_try_sql(create),
                    defined_in="CREATE TABLE",
                    context=context,
                )

    def _extract_generic(self, statement: exp.Expression, context: str):
        """Generic extraction for unhandled statement types."""
        # Try to find tables and columns
        for node in statement.walk():
            if isinstance(node, exp.Table):
                name = _clean_name(node.name or "")
                if name and name not in self._cte_aliases:
                    self._add_variable(
                        name=name,
                        var_type=VariableType.TABLE,
                        sql_expression=_try_sql(node),
                        defined_in="statement",
                        context=context,
                    )
                    break  # One table per generic statement is enough
