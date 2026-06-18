"""
Variable Extractor v2 — Role-Based Identifier Extraction
=========================================================

Instead of checking for every possible SQL syntax structure (CASE, COALESCE,
Window, Subquery, etc.), this extractor walks the AST and classifies EVERY
Identifier node based on its **structural role** in the AST tree.

Principle: In SQL, every meaningful name is an Identifier AST node.
Its role is determined by its *parent* node type:

    Identifier inside Column     → TABLE_COLUMN
    Identifier inside Table      → DATABASE_TABLE
    Identifier inside TableAlias → DATABASE_TABLE (alias)
    Identifier inside Alias      → depends on the aliased expression type

This approach automatically handles ANY SQL construct that sqlglot can parse
— no new code needed when new SQL features are encountered.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from app.models.variable import VariableDefinition, VariableType


# ── Aggregate / Window function name sets ───────────────────────────────

_AGGREGATE_NAMES = {
    "sum", "count", "avg", "min", "max", "group_concat",
    "stddev", "variance", "stddev_pop", "stddev_samp",
    "var_pop", "var_samp", "bit_and", "bit_or", "bit_xor",
}

_WINDOW_ONLY_NAMES = {
    "row_number", "rownumber", "rank", "dense_rank", "denserank",
    "percent_rank", "percentrank", "cume_dist", "cumedist",
    "ntile", "lag", "lead", "first_value", "firstvalue",
    "last_value", "lastvalue", "nth_value", "nthvalue",
}

_KNOWN_FUNCTIONS = {
    "coalesce", "cast", "concat", "json_extract", "if", "nullif",
    "greatest", "least", "date_add", "date_sub", "datediff",
    "timestampdiff", "period_diff", "date_trunc", "date_format",
    "extract", "abs", "round", "ceil", "floor", "substring_index",
    "st_x", "st_y",
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_id(script_name: str, name: str, suffix: int = 0) -> str:
    base = f"{script_name}:{name}"
    if suffix:
        base = f"{base}_{suffix}"
    return hashlib.md5(base.encode()).hexdigest()[:16]


def _clean(name: str) -> str:
    """Strip quotes and backticks."""
    name = (name or "").strip()
    if len(name) >= 2 and name[0] in ('"', "'", '`') and name[0] == name[-1]:
        name = name[1:-1]
    return name


def _sql(expr) -> str:
    """Safe SQL rendering with pretty-print for readability."""
    if expr is None:
        return ""
    try:
        return expr.sql(dialect="mysql", pretty=True)
    except Exception:
        return ""


def _func_name(expr: exp.Expression) -> str:
    """Get the canonical function name from an expression node."""
    if isinstance(expr, exp.Anonymous):
        return (expr.name or "").lower()
    try:
        return (expr.sql_name() or "").lower()
    except Exception:
        return ""


# ── Classification: what is being aliased? ─────────────────────────────

def _classify_aliased_expression(aliased_expr: exp.Expression) -> VariableType:
    """Given the expression inside an Alias node, return its VariableType.

    This replaces the old _classify_select_expression — instead of checking
    for every possible expression subclass, we look at the structural
    properties of the expression AST node.
    """
    # Window functions
    if isinstance(aliased_expr, exp.Window):
        return VariableType.WINDOW

    # Check for window inside (e.g. SUM(...) OVER (...))
    has_window = any(isinstance(n, exp.Window) for n in aliased_expr.walk() if n is not aliased_expr)
    if has_window:
        return VariableType.WINDOW

    # Subquery
    if isinstance(aliased_expr, exp.Subquery):
        return VariableType.SUBQUERY

    # Aggregate functions (Sum, Count, Avg, Min, Max, AggFunc)
    if isinstance(aliased_expr, exp.AggFunc):
        return VariableType.AGGREGATE
    if isinstance(aliased_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
        return VariableType.AGGREGATE

    # CASE expression
    if isinstance(aliased_expr, exp.Case):
        return VariableType.CASE

    # Check if it's an aggregate by sql_name
    fname = _func_name(aliased_expr)
    if fname in _AGGREGATE_NAMES:
        return VariableType.AGGREGATE
    if fname in _WINDOW_ONLY_NAMES:
        return VariableType.WINDOW

    # Known transformation functions
    if fname in _KNOWN_FUNCTIONS:
        return VariableType.TRANSFORM
    if isinstance(aliased_expr, (exp.Coalesce, exp.Cast, exp.Concat, exp.JSONExtract,
                                  exp.If, exp.Nullif, exp.Greatest, exp.Least,
                                  exp.DateAdd, exp.DateSub, exp.DateDiff)):
        return VariableType.TRANSFORM

    # Generic function (Func subclass but not a known aggregate)
    if isinstance(aliased_expr, exp.Func) and not isinstance(aliased_expr, exp.Column):
        return VariableType.TRANSFORM

    # Literal
    if isinstance(aliased_expr, exp.Literal):
        return VariableType.LITERAL

    # Bare column reference
    if isinstance(aliased_expr, exp.Column):
        return VariableType.COLUMN

    # Default: computed expression
    return VariableType.EXPRESSION


# ── Source column extraction ────────────────────────────────────────────

def _extract_source_columns(expr: exp.Expression) -> list[str]:
    """Walk an expression tree and extract all table.column references.

    Walks INTO subqueries to find their column references (e.g., scalar
    subquery in SELECT depends on columns inside the subquery).
    Only CTEs are pruned (their columns belong to a different scope).
    """
    cols = []
    if expr is None or not hasattr(expr, 'walk'):
        return cols
    try:
        for node in expr.walk(prune=lambda n: isinstance(n, (exp.CTE,))):
            if isinstance(node, exp.Column):
                table = _clean(node.table or "")
                col_name = _clean(node.name or "")
                if table:
                    cols.append(f"{table}.{col_name}")
                elif col_name:
                    cols.append(col_name)
    except Exception:
        pass
    return list(set(cols))


def _extract_table_names(expr: exp.Expression) -> list[str]:
    """Walk an expression tree and extract all table references."""
    tables = set()
    if expr is None or not hasattr(expr, 'walk'):
        return []
    for node in expr.walk():
        if isinstance(node, exp.Table):
            name = _clean(node.name or "")
            if name:
                tables.add(name)
    return list(tables)


# ── Main Extractor ──────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    script_name: str
    variables: list[VariableDefinition] = field(default_factory=list)
    template_replacements: list[str] = field(default_factory=list)


def _detect_dialect(sql_text: str) -> str:
    """Detect SQL dialect by scoring distinctive markers.

    Returns the best sqlglot dialect name (hive, mysql, postgres, etc.).
    """
    import re
    upper = sql_text.upper()
    scores = {}

    # Hive family (MaxCompute/ODPS/Spark/Hive/Databricks)
    if re.search(r'(?i)INSERT\s+OVERWRITE\s+TABLE', sql_text): scores['hive'] = scores.get('hive', 0) + 10
    if re.search(r'(?i)SET\s+odps\.', sql_text): scores['hive'] = scores.get('hive', 0) + 10
    if re.search(r'(?i)PARTITION\s*\(', sql_text): scores['hive'] = scores.get('hive', 0) + 5
    if re.search(r'(?i)TBLPROPERTIES|STORED\s+AS\s+(ORC|PARQUET|TEXTFILE|AVRO)', sql_text): scores['hive'] = scores.get('hive', 0) + 5
    if re.search(r'(?i)LATERAL\s+VIEW\s+EXPLODE', sql_text): scores['hive'] = scores.get('hive', 0) + 5

    # Oracle
    if re.search(r'(?i)DECODE\s*\(', sql_text): scores['oracle'] = scores.get('oracle', 0) + 3
    if re.search(r'(?i)NVL\s*\(', sql_text): scores['oracle'] = scores.get('oracle', 0) + 3
    if re.search(r'(?i)CONNECT\s+BY', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10
    if re.search(r'(?i)DBMS_|UTL_', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10
    if re.search(r'(?i)ROWNUM\b', sql_text): scores['oracle'] = scores.get('oracle', 0) + 5
    if re.search(r'(?i)FROM\s+DUAL\b', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10

    # PostgreSQL
    if re.search(r'(?i)ILIKE\b', sql_text): scores['postgres'] = scores.get('postgres', 0) + 5
    if '::' in sql_text and not '::=' in sql_text: scores['postgres'] = scores.get('postgres', 0) + 5
    if re.search(r'(?i)RETURNING\b', sql_text): scores['postgres'] = scores.get('postgres', 0) + 3

    # BigQuery
    if re.search(r'(?i)`[a-z]+\.[a-z]+\.[a-z]+`', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 10
    if re.search(r'(?i)STRUCT\s*<', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 5
    if re.search(r'(?i)ARRAY\s*<', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 3

    # TSQL (SQL Server)
    if re.search(r'(?i)\bTOP\s+\d+', sql_text): scores['tsql'] = scores.get('tsql', 0) + 5
    if re.search(r'(?i)\[[a-zA-Z_][a-zA-Z0-9_]*\]\.[a-zA-Z_][a-zA-Z0-9_]*\]', sql_text): scores['tsql'] = scores.get('tsql', 0) + 3
    if re.search(r'(?i)WITH\s*\(\s*NOLOCK\s*\)', sql_text): scores['tsql'] = scores.get('tsql', 0) + 10

    # Snowflake
    if re.search(r'(?i)QUALIFY\b', sql_text): scores['snowflake'] = scores.get('snowflake', 0) + 10
    if re.search(r'(?i)COPY\s+INTO', sql_text): scores['snowflake'] = scores.get('snowflake', 0) + 5

    # MySQL
    if re.search(r'(?i)LIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*;?\s*$', sql_text, re.MULTILINE): scores['mysql'] = scores.get('mysql', 0) + 2
    if re.search(r'(?i)ENGINE\s*=', sql_text): scores['mysql'] = scores.get('mysql', 0) + 10
    if re.search(r'(?i)AUTO_INCREMENT', sql_text): scores['mysql'] = scores.get('mysql', 0) + 10

    if not scores:
        return 'mysql'

    # Hive also gets Oracle points (MaxCompute has both)
    if 'hive' in scores:
        scores['hive'] += scores.pop('oracle', 0) * 0.5

    best = max(scores, key=scores.get)
    return best


def _preprocess_sql(sql_text: str) -> str:
    """Strip SET statements and other non-SQL configuration lines.
    Also handles MaxCompute/ODPS/Hive-specific syntax.
    """
    import re
    lines = sql_text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip SET statements (MaxCompute/ODPS configuration)
        if re.match(r'(?i)^set\s+', stripped):
            continue
        # Skip pure comments
        if stripped.startswith('--'):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def extract_variables_from_sql(sql_text: str, script_name: str) -> ExtractionResult:
    """Main entry point: extract all variables via role-based Identifier walking.

    Algorithm:
      1. Strip SET/config statements
      2. Try parsing with hive dialect (covers MaxCompute/ODPS/Spark)
      3. Fall back to mysql if hive produces nothing
      4. Walk ALL Identifier nodes in the AST
      5. Classify each by parent node role
    """
    result = ExtractionResult(script_name=script_name)

    # Strip SET statements, comment lines
    clean_sql = _preprocess_sql(sql_text)

    # Detect dialect and parse
    dialect_used = _detect_dialect(clean_sql)
    parsed = None
    try:
        parsed = sqlglot.parse(clean_sql, dialect=dialect_used, error_level=sqlglot.ErrorLevel.IGNORE)
    except Exception:
        pass

    # Fallback: try hive (covers MaxCompute/ODPS), then mysql
    if not parsed or not any(s is not None for s in parsed):
        for fallback in ['hive', 'mysql']:
            if fallback == dialect_used:
                continue
            try:
                parsed = sqlglot.parse(clean_sql, dialect=fallback, error_level=sqlglot.ErrorLevel.IGNORE)
                if parsed and any(s is not None for s in parsed):
                    dialect_used = fallback
                    break
            except Exception:
                continue

    if not parsed:
        try:
            parsed = sqlglot.parse(clean_sql, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception:
            return result

    result.template_replacements = [f"dialect: {dialect_used}"]
    if '${' in sql_text:
        result.template_replacements.append("template vars present — may affect parsing")

    extractor = _RoleBasedExtractor(result, script_name, sql_text)
    for statement in parsed:
        if statement is not None:
            extractor.process_statement(statement, "TOP")

    return result


class _RoleBasedExtractor:
    """Walks the AST, classifies every Identifier by its structural role."""

    def __init__(self, result: ExtractionResult, script_name: str, sql_text: str):
        self.result = result
        self.script_name = script_name
        self.sql_text = sql_text
        self._counter: dict[str, int] = {}
        self._cte_names: set[str] = set()
        self._table_aliases: dict[str, str] = {}  # alias → real table name
        self._seen: set[tuple[str, str]] = set()   # (name, type) dedup
        self._subq_counter: int = 0  # unique subquery IDs

    def _next_id(self, key: str) -> str:
        self._counter[key] = self._counter.get(key, 0) + 1
        return _make_id(self.script_name, key, self._counter[key])

    def _add(self, name: str, var_type: VariableType, sql_expr: str = "",
             defined_in: str = "", context: str = "TOP",
             source_cols: list[str] | None = None,
             source_tables: list[str] | None = None,
             is_output: bool = False) -> VariableDefinition | None:
        """Add a variable, deduplicating globally by (name, type) — one node per unique variable."""
        name = _clean(name)
        if not name:
            return None

        # CTE tables referenced in FROM clauses also appear as DATABASE_TABLE.
        # Merge them: if a CTE_TABLE with the same name exists, skip the DB version.
        if var_type == VariableType.TABLE:
            for existing in self.result.variables:
                if existing.variable_type == VariableType.CTE and existing.name == name:
                    return None  # already exists as CTE_TABLE

        key = (name, var_type.value)  # global unique — same column = one node
        if key in self._seen:
            return None
        self._seen.add(key)

        vid = self._next_id(f"{context}:{name}")
        var = VariableDefinition(
            id=vid, name=name, variable_type=var_type,
            sql_expression=sql_expr,
            source_columns=source_cols or [],
            source_tables=source_tables or [],
            defined_in=defined_in, context=context,
            is_output=is_output,
        )
        self.result.variables.append(var)
        return var

    # ── Top-level dispatch ──────────────────────────────────────────

    def process_statement(self, stmt: exp.Expression, context: str):
        """Process a top-level statement, dispatching to walkers."""
        # Process any WITH clause first (can appear on any statement type)
        with_clause = stmt.args.get("with") or stmt.args.get("with_")
        if with_clause:
            self._walk_cte_definitions(with_clause)

        # sqlglot wraps queries with complex table names in a With node
        if isinstance(stmt, exp.With):
            self._walk_cte_definitions(stmt)
            inner = stmt.this
            if inner:
                self.process_statement(inner, context)
            return

        if isinstance(stmt, exp.Select):
            self._walk_select(stmt, context, is_cte=False)
        elif isinstance(stmt, exp.Union):
            self._walk_setop(stmt, "UNION", context)
        elif isinstance(stmt, exp.Intersect):
            self._walk_setop(stmt, "INTERSECT", context)
        elif isinstance(stmt, exp.Except):
            self._walk_setop(stmt, "EXCEPT", context)
        elif isinstance(stmt, exp.Merge):
            self._walk_merge(stmt, context)
        elif isinstance(stmt, exp.Insert):
            self._walk_insert(stmt, context)
        elif isinstance(stmt, exp.Create):
            self._walk_create(stmt, context)
        else:
            self._walk_select(stmt, context, is_cte=False)  # try generic SELECT walk

    # ── CTE definitions ─────────────────────────────────────────────

    def _walk_cte_definitions(self, with_clause):
        """Extract CTE table names from a WITH clause."""
        cte_list = []
        if hasattr(with_clause, 'expressions'):
            cte_list = with_clause.expressions
        elif isinstance(with_clause, exp.CTE):
            cte_list = [with_clause]

        for cte_def in cte_list:
            if not isinstance(cte_def, exp.CTE):
                continue
            alias = _clean(getattr(cte_def, 'alias_or_name', '') or '')
            if not alias:
                continue
            self._cte_names.add(alias)

            # CTE table variable
            self._add(alias, VariableType.CTE,
                      sql_expr=_sql(cte_def),
                      defined_in=f"CTE:{alias}", context="TOP")

            # Walk the inner query to extract columns
            inner = cte_def.this
            if isinstance(inner, exp.Select):
                self._walk_select(inner, f"CTE:{alias}", is_cte=True)
            elif isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(inner, type(inner).__name__.upper(), f"CTE:{alias}")

    # ── SELECT walker (the core) ────────────────────────────────────

    def _walk_select(self, select: exp.Select, context: str, is_cte: bool = False):
        """Walk a SELECT/UPDATE/DELETE and classify every Identifier found."""
        # Create a VIRTUAL_TABLE for this SELECT's output.
        # Exception: inside a CTE, the CTE node itself serves as the output
        # container — no separate VT needed. The CTE IS the named result set.
        if not is_cte:
            label = context.split(":")[-1] if ":" in context else "output"
            vt_name = f"⟐ {label}"
            self._add(vt_name, VariableType.VIRTUAL_TABLE,
                      sql_expr=_sql(select),
                      defined_in=context, context=context)

        # Detect statement type for DML marking
        stmt_type = type(select).__name__.upper()
        dml_mark = ""
        if stmt_type in ("UPDATE", "DELETE"):
            dml_mark = stmt_type

        # Main table (UPDATE/DELETE use 'this', SELECT uses 'from')
        main_table = select.args.get("this")
        if main_table and isinstance(main_table, exp.Table):
            self._register_table(main_table, context, dml=dml_mark)

        # FROM clause — table names and aliases
        from_exp = select.args.get("from") or select.args.get("from_")
        if from_exp:
            self._walk_from(from_exp, context)

        # JOIN clauses
        for join in (select.args.get("joins") or []):
            self._walk_join(join, context)

        # USING clause (DELETE ... USING / MERGE USING)
        using_tables = select.args.get("using") or []
        if isinstance(using_tables, exp.Expression):
            using_tables = [using_tables]
        for ut in using_tables:
            if isinstance(ut, exp.Table):
                self._register_table(ut, context)
            elif isinstance(ut, exp.Subquery):
                sub_alias = _clean(ut.alias or "")
                if sub_alias:
                    self._add(sub_alias, VariableType.SUBQUERY,
                              sql_expr=_sql(ut.this),
                              defined_in="USING", context=context)
                if isinstance(ut.this, exp.Select):
                    self._walk_select(ut.this, context, is_cte=False)

        # SELECT expressions — process FIRST so aggregates are registered
        # before HAVING/ORDER BY references are encountered
        raw_exprs = select.expressions or []
        for expr in raw_exprs:
            self._walk_select_expression(expr, context, is_cte)

        # WHERE / HAVING conditions — after SELECT so bare refs dedup against aggregates
        for key in ("where", "having"):
            cond = select.args.get(key)
            if cond:
                self._walk_columns_in_expr(cond, context, defined_in=key.upper())

        # GROUP BY / ORDER BY — column references
        for key, label in [("group", "GROUP BY"), ("order", "ORDER BY")]:
            clause = select.args.get(key)
            if clause:
                for e in (clause.expressions if hasattr(clause, 'expressions') else [clause]):
                    self._walk_columns_in_expr(e, context, defined_in=label)

        # SELECT INTO — creates a new table from the SELECT result
        into = select.args.get("into")
        if into:
            into_table = into.this if isinstance(into, exp.Into) else into
            if isinstance(into_table, exp.Table):
                into_name = _clean(into_table.name or "")
                if into_name:
                    self._add(into_name, VariableType.TABLE,
                              sql_expr=f"SELECT INTO {into_name}",
                              defined_in="SELECT INTO", context=context)

    # ── FROM / JOIN walkers ─────────────────────────────────────────

    def _walk_from(self, from_exp, context: str):
        """Extract table references from a FROM clause."""
        # Unwrap From wrapper
        if isinstance(from_exp, exp.From):
            from_exp = from_exp.this
        if isinstance(from_exp, exp.Table):
            self._register_table(from_exp, context)
        elif isinstance(from_exp, exp.Subquery):
            # FROM (SELECT ...) AS alias — register alias as subquery type
            sub_alias = _clean(from_exp.alias or "")
            sub_ctx = f"{context}:subq:{sub_alias}" if sub_alias else f"{context}:subq"
            if sub_alias:
                self._add(sub_alias, VariableType.SUBQUERY,
                          sql_expr=_sql(from_exp.this),
                          defined_in=f"FROM:{context}", context=sub_ctx)
            if isinstance(from_exp.this, exp.Select):
                self._walk_select(from_exp.this, sub_ctx, is_cte=False)
            elif isinstance(from_exp.this, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(from_exp.this, type(from_exp.this).__name__.upper(), sub_ctx)

    def _walk_join(self, join, context: str):
        """Extract from a JOIN clause (including LATERAL)."""
        join_expr = join.this
        lateral_alias = None

        # Unwrap Lateral
        if isinstance(join_expr, exp.Lateral):
            lateral_alias = _clean(join_expr.alias_or_name or join_expr.alias or "")
            join_expr = join_expr.this

        if isinstance(join_expr, exp.Table):
            # Register JOIN tables with "JOIN" prefix in defined_in
            self._register_table(join_expr, context, join_table=True)
        elif isinstance(join_expr, exp.Subquery):
            # JOIN (SELECT ...) AS alias
            sub_alias = _clean(join_expr.alias or lateral_alias or "")
            sub_ctx = f"{context}:join:{sub_alias}" if sub_alias else f"{context}:join_subq"
            if sub_alias:
                self._add(sub_alias, VariableType.SUBQUERY,
                          sql_expr=_sql(join_expr.this),
                          defined_in=f"JOIN:{context}", context=sub_ctx)
            if isinstance(join_expr.this, exp.Select):
                self._walk_select(join_expr.this, sub_ctx, is_cte=False)
        elif lateral_alias and isinstance(join_expr, exp.Select):
            # LATERAL SELECT without Subquery wrapper
            self._add(lateral_alias, VariableType.SUBQUERY,
                      sql_expr=_sql(join_expr),
                      defined_in=f"LATERAL:{context}", context=context)
            self._walk_select(join_expr, context, is_cte=False)

        # JOIN ON conditions
        on_expr = join.args.get("on")
        if on_expr:
            self._walk_columns_in_expr(on_expr, context, defined_in="JOIN ON")

    def _register_table(self, table: exp.Table, context: str, join_table: bool = False, dml: str = ""):
        """Register a database table and its alias."""
        name = _clean(table.name or "")
        alias = _clean(table.alias_or_name or "")
        if not name:
            return
        if dml:
            defined_in = dml  # "UPDATE" or "DELETE"
        elif join_table:
            defined_in = "JOIN"
        else:
            defined_in = "FROM"

        self._add(name, VariableType.TABLE,
                  sql_expr=name, defined_in=defined_in, context=context)

        if alias and alias != name:
            self._table_aliases[alias] = name
            self._add(alias, VariableType.TABLE,
                      sql_expr=f"{name} AS {alias}",
                      defined_in=defined_in, context=context,
                      source_tables=[name])

    # ── Column walker ───────────────────────────────────────────────

    def _walk_columns_in_expr(self, expr, context: str, defined_in: str = ""):
        """Walk an expression tree: register columns AND nested table aliases."""
        if expr is None:
            return
        for node in expr.walk(prune=lambda n: isinstance(n, (exp.CTE,))):
            if isinstance(node, exp.Column):
                self._register_column(node, context, defined_in)
            # Walk INTO subqueries — fully process inner SELECT
            elif isinstance(node, exp.Subquery):
                if isinstance(node.this, exp.Select):
                    self._subq_counter += 1
                    self._walk_select(node.this, f"{context}:subq{self._subq_counter}", is_cte=False)
            elif isinstance(node, exp.Exists):
                # EXISTS wraps a Select directly (not a Subquery)
                if isinstance(node.this, exp.Select):
                    self._subq_counter += 1
                    self._walk_select(node.this, f"{context}:exists{self._subq_counter}", is_cte=False)

    def _walk_select_tables(self, select_node, context: str):
        """Extract table references from a Select node inside subquery/EXISTS."""
        if not isinstance(select_node, exp.Select):
            return
        frm = select_node.args.get("from") or select_node.args.get("from_")
        if frm:
            self._walk_from(frm, context)
        for join in (select_node.args.get("joins") or []):
            self._walk_join(join, context)

    def _register_column(self, col: exp.Column, context: str, defined_in: str = ""):
        """Register a single column reference."""
        table = _clean(col.table or "")
        col_name = _clean(col.name or "")
        if not col_name:
            return
        # For bare column names (no table prefix): skip if a defined variable
        # with the same name already exists (aggregate, window, case, function,
        # intermediate). This prevents HAVING/ORDER BY references from creating
        # duplicate nodes. The REFERENCES edge handles the semantic connection.
        if not table:
            for existing in self.result.variables:
                if existing.name == col_name and existing.variable_type in (
                    VariableType.AGGREGATE, VariableType.WINDOW,
                    VariableType.CASE, VariableType.TRANSFORM,
                    VariableType.EXPRESSION, VariableType.CTE_COLUMN):
                    return  # already defined — don't create duplicate
        full = f"{table}.{col_name}" if table else col_name
        self._add(full, VariableType.COLUMN,
                  sql_expr=_sql(col),
                  defined_in=defined_in or "condition", context=context)

    # ── SELECT expression walker ────────────────────────────────────

    def _walk_select_expression(self, expr, context: str, is_cte: bool = False):
        """Walk one SELECT expression (may or may not have an alias)."""
        if expr is None:
            return

        # Unwrap Alias to get the actual expression
        alias = ""
        inner = expr
        if isinstance(expr, exp.Alias):
            alias = _clean(expr.alias or "")
            inner = expr.this

        # Skip None / non-walkable
        if inner is None or not hasattr(inner, 'walk'):
            return

        # Auto-name: use alias if present, otherwise derive from expression
        if not alias:
            if isinstance(inner, exp.Column):
                # Bare column reference: table.column or just column
                tbl = _clean(inner.table or "")
                col = _clean(inner.name or "")
                alias = f"{tbl}.{col}" if tbl else col
            elif isinstance(inner, exp.Literal):
                alias = _sql(inner)[:30]
            else:
                raw = _sql(inner)[:30].replace(" ", "_").replace("(", "").replace(")", "")
                alias = raw or "expr"

        sql_expr = _sql(inner)
        src_cols = _extract_source_columns(inner)
        src_tables = _extract_table_names(inner)
        var_type = _classify_aliased_expression(inner)

        # CTE context: only bare "expression" becomes cte_column
        if is_cte and var_type == VariableType.EXPRESSION:
            var_type = VariableType.CTE_COLUMN

        defined_in = context

        self._add(alias, var_type,
                  sql_expr=sql_expr,
                  defined_in=defined_in, context=context,
                  source_cols=src_cols, source_tables=src_tables,
                  is_output=(not is_cte))

        # Register columns inside the expression — needed for BELONGS_TO edges
        self._walk_columns_in_expr(inner, context, defined_in="SELECT expr")

    # ── Set operations (UNION / INTERSECT / EXCEPT) ─────────────────

    def _walk_setop(self, setop, op_type: str, context: str):
        """Walk UNION ALL, INTERSECT, EXCEPT — process all branches."""
        self._add(f"{op_type.lower()}_result", VariableType.UNION_BRANCH,
                  sql_expr=_sql(setop),
                  defined_in=op_type, context=context)

        sides = []
        if hasattr(setop, 'left') and hasattr(setop, 'right'):
            sides = [setop.left, setop.right]
        else:
            if setop.this is not None:
                sides.append(setop.this)
            if hasattr(setop, 'expression') and setop.expression is not None:
                sides.append(setop.expression)

        for side in sides:
            if side is not None:
                self.process_statement(side, context)

    # ── MERGE walker ────────────────────────────────────────────────

    def _walk_merge(self, merge: exp.Merge, context: str):
        """Walk a MERGE statement."""
        target = merge.args.get("target") or merge.args.get("this")
        if target and isinstance(target, exp.Table):
            name = _clean(target.name or "")
            alias = _clean(target.alias_or_name or "")
            self._add(name, VariableType.MERGE_TARGET,
                      sql_expr=_sql(target), defined_in="MERGE", context=context)
            if alias and alias != name:
                self._add(alias, VariableType.MERGE_TARGET,
                          sql_expr=f"{name} AS {alias}", defined_in="MERGE",
                          context=context, source_tables=[name])

        # Source (USING)
        using = merge.args.get("using")
        if using:
            if isinstance(using, exp.Table):
                self._register_table(using, context)
            elif isinstance(using, exp.Subquery):
                # Walk in SAME context so DML phase finds source columns
                sub_alias = _clean(using.alias or "")
                if sub_alias:
                    self._add(sub_alias, VariableType.SUBQUERY,
                              sql_expr=_sql(using.this),
                              defined_in="MERGE USING", context=context)
                self._walk_select(using.this, context, is_cte=False)

        # ON condition
        on_expr = merge.args.get("on")
        if on_expr:
            self._walk_columns_in_expr(on_expr, context, defined_in="MERGE ON")

        # WHEN clauses
        for when in (merge.args.get("whens") or []):
            if hasattr(when, 'this') and when.this:
                self._walk_columns_in_expr(when.this, context, defined_in="MERGE WHEN")

    # ── INSERT / CREATE walkers ─────────────────────────────────────

    def _walk_insert(self, insert: exp.Insert, context: str):
        """Walk an INSERT statement (INSERT INTO ... SELECT/VALUES)."""
        into = insert.args.get("into") or insert.args.get("this")
        if isinstance(into, exp.Schema):
            into = into.this
        if isinstance(into, exp.Table):
            # Register target with INSERT marking (not default "FROM")
            name = _clean(into.name or "")
            alias = _clean(into.alias_or_name or "")
            if name:
                self._add(name, VariableType.TABLE,
                          sql_expr=name, defined_in="INSERT", context=context)
                if alias and alias != name:
                    self._add(alias, VariableType.TABLE,
                              sql_expr=f"{name} AS {alias}",
                              defined_in="INSERT", context=context,
                              source_tables=[name])
        # Walk the source SELECT (INSERT INTO ... SELECT)
        expr = insert.args.get("expression")
        if expr and isinstance(expr, (exp.Select, exp.Union)):
            self.process_statement(expr, context)
        else:
            # VALUES-based INSERT — create a minimal VT anchor so the target
            # table isn't isolated (the DML phase can connect VT → target)
            self._add("⟐ insert", VariableType.VIRTUAL_TABLE,
                      sql_expr="INSERT VALUES", defined_in="INSERT", context=context)
            # Also extract target columns if present in Schema
            if isinstance(into, exp.Schema):
                for col_expr in (into.expressions or []):
                    if isinstance(col_expr, exp.Column):
                        col_name = _clean(col_expr.name or "")
                        if col_name:
                            self._add(col_name, VariableType.COLUMN,
                                      sql_expr=_sql(col_expr),
                                      defined_in="INSERT", context=context)

    def _walk_create(self, create: exp.Create, context: str):
        """Walk a CREATE statement (TABLE, VIEW, MATERIALIZED VIEW, CTAS)."""
        kind = str(create.args.get("kind", "")).upper()
        table_expr = create.args.get("this")
        name = _clean(table_expr.name or "") if table_expr and isinstance(table_expr, exp.Table) else ""

        if kind == "VIEW":
            # CREATE VIEW / CREATE MATERIALIZED VIEW
            if name:
                self._add(name, VariableType.VIEW,
                          sql_expr=_sql(create), defined_in="CREATE VIEW", context=context)
            # Walk the inner SELECT defining the view
            inner = create.args.get("expression")
            if inner and isinstance(inner, exp.Select):
                self._walk_select(inner, f"VIEW:{name}" if name else context, is_cte=False)
            elif inner and isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(inner, type(inner).__name__.upper(),
                                 f"VIEW:{name}" if name else context)

        elif kind == "TABLE":
            if name:
                self._add(name, VariableType.TABLE,
                          sql_expr=_sql(create), defined_in="CREATE TABLE", context=context)
            # CTAS: CREATE TABLE ... AS SELECT — walk the inner SELECT
            inner = create.args.get("expression")
            if inner and isinstance(inner, exp.Select):
                self._walk_select(inner, f"CTAS:{name}" if name else context, is_cte=False)
            elif inner and isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(inner, type(inner).__name__.upper(),
                                 f"CTAS:{name}" if name else context)
