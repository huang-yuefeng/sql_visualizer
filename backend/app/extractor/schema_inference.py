"""R18: Table schema inference from dependency graph edges.

Iteratively analyzes SCHEMA, DML, TABLE_FLOW, JOIN, ALIAS, SET_OP edges
to build a {table_name -> {column_names}} mapping.

Used by compute_field_lineage() for table-first seed lookup and field
validation — replacing fragile fuzzy label matching.
"""

from __future__ import annotations
from collections import defaultdict


def infer_table_schemas(variables: list, dependencies: list) -> dict[str, set[str]]:
    """Infer table schemas from dependency graph edges.

    Iterates edge passes until stabilization (max 20 iterations).

    Pass 1 (SCHEMA): table → column edge adds column to table's schema
    Pass 2 (DML):    column → target_table edge propagates column name
    Pass 3 (TABLE_FLOW): table → VT, VT inherits table's columns
    Pass 4 (JOIN):   source → VT, VT inherits source's columns
    Pass 5 (SET_OP): branch → parent, parent inherits branch's columns
    Pass 6 (ALIAS):  alias inherits original's columns
    Pass 7 (clean):  strip table. prefix from column names

    Returns:
        dict mapping canonical table/CTE/VT names to their column name sets.
    """
    # ── Build lookup maps ──
    var_by_id = {}
    var_by_label = {}
    for v in variables:
        vid = getattr(v, 'variable_id', getattr(v, 'id', ''))
        label = getattr(v, 'name', getattr(v, 'label', ''))
        canonical = _canonical(label)
        var_by_id[vid] = v
        if canonical:
            var_by_label.setdefault(canonical, v)

    # ── Helper: resolve canonical table name ──
    def resolve_name(node_id: str) -> str:
        v = var_by_id.get(node_id)
        if v is None:
            return ""
        label = getattr(v, 'name', getattr(v, 'label', ''))
        return _canonical(label)

    def resolve_id(node_id: str) -> str:
        """Resolve a node ID to its canonical name."""
        return resolve_name(node_id)

    # ── Initialize schemas ──
    # Use defaultdict for growing sets
    schemas: dict[str, set[str]] = defaultdict(set)

    # Edge type constants
    SCHEMA_EDGE = "SCHEMA"
    DML_EDGE = "DML"
    TABLE_FLOW_EDGE = "TABLE_FLOW"
    JOIN_EDGE = "JOIN"
    ALIAS_EDGE = "ALIAS"
    SET_OP_EDGE = "SET_OP"

    max_iterations = 20
    prev_sizes: dict[str, int] = {}

    for iteration in range(max_iterations):
        # Pass 1: SCHEMA edges — table → column
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != SCHEMA_EDGE:
                continue
            src_name = resolve_name(dep.source_id)
            tgt_name = resolve_name(dep.target_id)
            if src_name and tgt_name:
                schemas[src_name].add(tgt_name)

        # Pass 2: DML edges — column → target_table
        # The source is a column (or expression that references columns).
        # Propagate the column name to the target table.
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != DML_EDGE:
                continue
            src_name = resolve_name(dep.source_id)
            tgt_name = resolve_name(dep.target_id)
            if src_name and tgt_name:
                # src might be fully qualified (tbl.col); strip prefix
                col = _strip_table_prefix(src_name)
                schemas[tgt_name].add(col)

        # Pass 3: TABLE_FLOW — table → VT
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != TABLE_FLOW_EDGE:
                continue
            src_name = resolve_name(dep.source_id)
            tgt_name = resolve_name(dep.target_id)
            if src_name in schemas and tgt_name:
                schemas[tgt_name].update(schemas[src_name])

        # Pass 4: JOIN — source → VT
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != JOIN_EDGE:
                continue
            src_name = resolve_name(dep.source_id)
            tgt_name = resolve_name(dep.target_id)
            if src_name in schemas and tgt_name:
                schemas[tgt_name].update(schemas[src_name])

        # Pass 5: SET_OP — branch → parent
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != SET_OP_EDGE:
                continue
            src_name = resolve_name(dep.source_id)
            tgt_name = resolve_name(dep.target_id)
            if src_name in schemas and tgt_name:
                schemas[tgt_name].update(schemas[src_name])

        # Pass 6: ALIAS — alias inherits original's columns
        aliased: dict[str, str] = {}
        for dep in dependencies:
            rel = getattr(dep, 'relationship', getattr(dep, 'edge_type', ''))
            if rel != ALIAS_EDGE:
                continue
            original = resolve_name(dep.source_id)
            alias = resolve_name(dep.target_id)
            if original and alias:
                aliased[alias] = original

        for alias, original in aliased.items():
            if original in schemas:
                schemas[alias] = schemas[original].copy()

        # Pass 7: Clean column names — strip table prefix
        cleaned: dict[str, set[str]] = {}
        for tbl, cols in schemas.items():
            cleaned[tbl] = set()
            for col in cols:
                cleaned[tbl].add(_strip_table_prefix(col))

        schemas = cleaned

        # ── Stabilization check ──
        changed = False
        for tbl, cols in schemas.items():
            if len(cols) != prev_sizes.get(tbl, 0):
                changed = True
                break
        if not changed:
            break
        prev_sizes = {tbl: len(cols) for tbl, cols in schemas.items()}

    return dict(schemas)


def _canonical(label: str) -> str:
    """Return canonical table name, stripping quotes."""
    if not label:
        return ""
    label = label.strip()
    # Strip backticks, double quotes, square brackets
    if (label.startswith('"') and label.endswith('"')) or \
       (label.startswith('`') and label.endswith('`')) or \
       (label.startswith('[') and label.endswith(']')):
        label = label[1:-1]
    return label


def _strip_table_prefix(col_name: str) -> str:
    """Strip 'table.' prefix from column name, returning bare column."""
    if not col_name:
        return ""
    # Handle table.column
    if "." in col_name:
        return col_name.rsplit(".", 1)[-1]
    return col_name
