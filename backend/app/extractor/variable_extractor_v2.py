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
    """Safe SQL rendering."""
    if expr is None:
        return ""
    try:
        return expr.sql(dialect="mysql")
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
        return VariableType.WINDOW_RESULT

    # Check for window inside (e.g. SUM(...) OVER (...))
    has_window = any(isinstance(n, exp.Window) for n in aliased_expr.walk() if n is not aliased_expr)
    if has_window:
        return VariableType.WINDOW_RESULT

    # Subquery
    if isinstance(aliased_expr, exp.Subquery):
        return VariableType.SUBQUERY_RESULT

    # Aggregate functions (Sum, Count, Avg, Min, Max, AggFunc)
    if isinstance(aliased_expr, exp.AggFunc):
        return VariableType.AGGREGATE
    if isinstance(aliased_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
        return VariableType.AGGREGATE

    # CASE expression
    if isinstance(aliased_expr, exp.Case):
        return VariableType.CASE_RESULT

    # Check if it's an aggregate by sql_name
    fname = _func_name(aliased_expr)
    if fname in _AGGREGATE_NAMES:
        return VariableType.AGGREGATE
    if fname in _WINDOW_ONLY_NAMES:
        return VariableType.WINDOW_RESULT

    # Known transformation functions
    if fname in _KNOWN_FUNCTIONS:
        return VariableType.FUNCTION_RESULT
    if isinstance(aliased_expr, (exp.Coalesce, exp.Cast, exp.Concat, exp.JSONExtract,
                                  exp.If, exp.Nullif, exp.Greatest, exp.Least,
                                  exp.DateAdd, exp.DateSub, exp.DateDiff)):
        return VariableType.FUNCTION_RESULT

    # Generic function (Func subclass but not a known aggregate)
    if isinstance(aliased_expr, exp.Func) and not isinstance(aliased_expr, exp.Column):
        return VariableType.FUNCTION_RESULT

    # Literal
    if isinstance(aliased_expr, exp.Literal):
        return VariableType.LITERAL

    # Bare column reference
    if isinstance(aliased_expr, exp.Column):
        return VariableType.TABLE_COLUMN

    # Default: computed expression
    return VariableType.INTERMEDIATE


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


def extract_variables_from_sql(sql_text: str, script_name: str) -> ExtractionResult:
    """Main entry point: extract all variables via role-based Identifier walking.

    Algorithm:
      1. Parse SQL with sqlglot
      2. Walk ALL Identifier nodes in the AST
      3. Classify each by parent node role (Column/Table/TableAlias/Alias)
      4. Handle CTE, MERGE, UNION/INTERSECT/EXCEPT as structural wrappers
      5. Auto-name un-aliased expressions
      6. Build dependency source info
    """
    result = ExtractionResult(script_name=script_name)

    try:
        parsed = sqlglot.parse(sql_text, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE)
    except Exception:
        return result

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
        if var_type == VariableType.DATABASE_TABLE:
            for existing in self.result.variables:
                if existing.variable_type == VariableType.CTE_TABLE and existing.name == name:
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
            self._add(alias, VariableType.CTE_TABLE,
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
        # Create a VIRTUAL_TABLE for this SELECT's output
        label = context.split(":")[-1] if ":" in context else "output"
        vt_name = f"⟐ {label}"
        self._add(vt_name, VariableType.VIRTUAL_TABLE,
                  sql_expr=_sql(select)[:200],
                  defined_in=context, context=context)

        # Main table (UPDATE/DELETE use 'this', SELECT uses 'from')
        main_table = select.args.get("this")
        if main_table and isinstance(main_table, exp.Table):
            self._register_table(main_table, context)

        # FROM clause — table names and aliases
        from_exp = select.args.get("from") or select.args.get("from_")
        if from_exp:
            self._walk_from(from_exp, context)

        # JOIN clauses
        for join in (select.args.get("joins") or []):
            self._walk_join(join, context)

        # WHERE / HAVING conditions — columns used
        for key in ("where", "having"):
            cond = select.args.get(key)
            if cond:
                self._walk_columns_in_expr(cond, context, defined_in=key.upper())

        # SELECT expressions
        raw_exprs = select.expressions or []
        # Unwrap Star-expanded columns from * if needed
        for expr in raw_exprs:
            self._walk_select_expression(expr, context, is_cte)

        # GROUP BY / ORDER BY — column references
        for key, label in [("group", "GROUP BY"), ("order", "ORDER BY")]:
            clause = select.args.get(key)
            if clause:
                for e in (clause.expressions if hasattr(clause, 'expressions') else [clause]):
                    self._walk_columns_in_expr(e, context, defined_in=label)

    # ── FROM / JOIN walkers ─────────────────────────────────────────

    def _walk_from(self, from_exp, context: str):
        """Extract table references from a FROM clause."""
        # Unwrap From wrapper
        if isinstance(from_exp, exp.From):
            from_exp = from_exp.this
        if isinstance(from_exp, exp.Table):
            self._register_table(from_exp, context)
        elif isinstance(from_exp, exp.Subquery):
            self._walk_select(from_exp.this, context, is_cte=False)

    def _walk_join(self, join, context: str):
        """Extract from a JOIN clause (including LATERAL)."""
        join_expr = join.this
        lateral_alias = None

        # Unwrap Lateral
        if isinstance(join_expr, exp.Lateral):
            lateral_alias = _clean(join_expr.alias_or_name or join_expr.alias or "")
            join_expr = join_expr.this

        if isinstance(join_expr, exp.Table):
            self._register_table(join_expr, context)
        elif isinstance(join_expr, exp.Subquery):
            # JOIN (SELECT ...) AS alias
            sub_alias = _clean(join_expr.alias or lateral_alias or "")
            if sub_alias:
                self._add(sub_alias, VariableType.SUBQUERY_RESULT,
                          sql_expr=_sql(join_expr.this),
                          defined_in=f"JOIN:{context}", context=context)
            if isinstance(join_expr.this, exp.Select):
                self._walk_select(join_expr.this, context, is_cte=False)
        elif lateral_alias and isinstance(join_expr, exp.Select):
            # LATERAL SELECT without Subquery wrapper
            self._add(lateral_alias, VariableType.SUBQUERY_RESULT,
                      sql_expr=_sql(join_expr),
                      defined_in=f"LATERAL:{context}", context=context)
            self._walk_select(join_expr, context, is_cte=False)

        # JOIN ON conditions
        on_expr = join.args.get("on")
        if on_expr:
            self._walk_columns_in_expr(on_expr, context, defined_in="JOIN ON")

    def _register_table(self, table: exp.Table, context: str):
        """Register a database table and its alias."""
        name = _clean(table.name or "")
        alias = _clean(table.alias_or_name or "")
        if not name:
            return

        self._add(name, VariableType.DATABASE_TABLE,
                  sql_expr=name, defined_in="FROM", context=context)

        if alias and alias != name:
            self._table_aliases[alias] = name
            self._add(alias, VariableType.DATABASE_TABLE,
                      sql_expr=f"{name} AS {alias}",
                      defined_in="FROM", context=context,
                      source_tables=[name])

    # ── Column walker ───────────────────────────────────────────────

    def _walk_columns_in_expr(self, expr, context: str, defined_in: str = ""):
        """Walk an expression tree: register columns AND nested table aliases."""
        if expr is None:
            return
        for node in expr.walk(prune=lambda n: isinstance(n, (exp.CTE,))):
            if isinstance(node, exp.Column):
                self._register_column(node, context, defined_in)
            # Walk INTO subqueries and EXISTS to register their FROM tables
            elif isinstance(node, exp.Subquery):
                self._walk_select_tables(node.this, f"{context}:subq")
            elif isinstance(node, exp.Exists):
                # EXISTS wraps a Select directly (not a Subquery)
                self._walk_select_tables(node.this, f"{context}:exists")

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
        full = f"{table}.{col_name}" if table else col_name
        self._add(full, VariableType.TABLE_COLUMN,
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

        # CTE context: only bare "intermediate" becomes cte_column
        if is_cte and var_type == VariableType.INTERMEDIATE:
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
                self._walk_select(using.this, f"MERGE USING:{context}", is_cte=False)

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
        """Walk an INSERT statement."""
        into = insert.args.get("into") or insert.args.get("this")
        if isinstance(into, exp.Schema):
            into = into.this
        if isinstance(into, exp.Table):
            self._register_table(into, context)
        expr = insert.args.get("expression")
        if expr and isinstance(expr, (exp.Select, exp.Union)):
            self.process_statement(expr, context)

    def _walk_create(self, create: exp.Create, context: str):
        """Walk a CREATE statement."""
        if str(create.args.get("kind", "")).upper() == "TABLE":
            table_expr = create.args.get("this")
            if table_expr and isinstance(table_expr, exp.Table):
                name = _clean(table_expr.name or "")
                self._add(name, VariableType.DATABASE_TABLE,
                          sql_expr=_sql(create), defined_in="CREATE TABLE", context=context)
