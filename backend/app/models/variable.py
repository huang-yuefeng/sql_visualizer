"""
Variable data models for SQL variable extraction and classification.

Node types are aligned with SQL data objects:
- Data Sources:    table, view, cte, subquery, virtual_table
- Column Refs:     column, cte_column
- DML Targets:     merge_target
- Set Operations:  union_branch
- Computed Values: aggregate, window, case, transform, expression
- Literals:        literal
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VariableType(str, Enum):
    """Classification of a SQL variable by its origin (aligned with SQL data objects).

    Categories group related types for frontend filtering and legend display.
    """

    # ── Data Sources (table-like objects: sources or targets of data flow) ──
    TABLE = "table"                   # Physical table: TABLE, TEMPORARY TABLE, FOREIGN DATA WRAPPER
    VIEW = "view"                     # View: VIEW, MATERIALIZED VIEW (virtual source only)
    CTE = "cte"                       # Common Table Expression: CTE (WITH ... AS)
    SUBQUERY = "subquery"             # Subquery: SUBQUERY (in FROM / JOIN)
    VIRTUAL_TABLE = "virtual_table"   # SELECT / JOIN output: a conceptual result set

    # ── Column References ────────────────────────────────────────────────────
    COLUMN = "column"                 # Column reference: table.column or bare column name
    CTE_COLUMN = "cte_column"         # Column defined inside a CTE

    # ── DML Targets ──────────────────────────────────────────────────────────
    MERGE_TARGET = "merge_target"     # MERGE: target table in MERGE INTO statement

    # ── Set Operations ───────────────────────────────────────────────────────
    UNION_BRANCH = "union_branch"     # UNION / INTERSECT / EXCEPT: one arm of a set operation

    # ── Computed Values ─────────────────────────────────────────────────────
    AGGREGATE = "aggregate"           # Aggregation: SUM, COUNT, AVG, MIN, MAX
    WINDOW = "window"                 # Window function: ROW_NUMBER, RANK, LAG, SUM() OVER()
    CASE = "case"                     # CASE WHEN expression result
    TRANSFORM = "transform"           # Function/transformation: COALESCE, CAST, CONCAT, etc.
    EXPRESSION = "expression"         # Generic computed expression alias (e.g. (a+b) AS total)

    # ── Literals ─────────────────────────────────────────────────────────────
    LITERAL = "literal"               # Constant / literal value

    @property
    def category(self) -> str:
        """Return the category this variable type belongs to."""
        return _TYPE_CATEGORIES.get(self, "Other")

    @property
    def display_name(self) -> str:
        """Human-readable display name for frontend labels."""
        return _TYPE_DISPLAY_NAMES.get(self, self.value)


# ── Category & Display Name Mappings ──────────────────────────────────────

_TYPE_CATEGORIES = {
    VariableType.TABLE: "Data Source",
    VariableType.VIEW: "Data Source",
    VariableType.CTE: "Data Source",
    VariableType.SUBQUERY: "Data Source",
    VariableType.VIRTUAL_TABLE: "Data Source",
    VariableType.COLUMN: "Column Reference",
    VariableType.CTE_COLUMN: "Column Reference",
    VariableType.MERGE_TARGET: "DML Target",
    VariableType.UNION_BRANCH: "Set Operation",
    VariableType.AGGREGATE: "Computed Value",
    VariableType.WINDOW: "Computed Value",
    VariableType.CASE: "Computed Value",
    VariableType.TRANSFORM: "Computed Value",
    VariableType.EXPRESSION: "Computed Value",
    VariableType.LITERAL: "Literal",
}

_TYPE_DISPLAY_NAMES = {
    VariableType.TABLE: "Table",
    VariableType.VIEW: "View",
    VariableType.CTE: "CTE",
    VariableType.SUBQUERY: "Subquery",
    VariableType.VIRTUAL_TABLE: "Output",
    VariableType.COLUMN: "Column",
    VariableType.CTE_COLUMN: "CTE Column",
    VariableType.MERGE_TARGET: "Merge Target",
    VariableType.UNION_BRANCH: "Union Branch",
    VariableType.AGGREGATE: "Aggregate",
    VariableType.WINDOW: "Window",
    VariableType.CASE: "Case",
    VariableType.TRANSFORM: "Transform",
    VariableType.EXPRESSION: "Expression",
    VariableType.LITERAL: "Literal",
}


class VariableDefinition(BaseModel):
    """Represents one variable extracted from a SQL script."""
    id: str                                                  # Unique ID (e.g. "script:cte.col")
    name: str                                                # Variable name (alias or column name)
    variable_type: VariableType
    sql_expression: str = ""                                 # SQL text defining this variable
    source_columns: list[str] = Field(default_factory=list)  # Physical columns this derives from
    source_variables: list[str] = Field(default_factory=list) # IDs of upstream variables
    source_tables: list[str] = Field(default_factory=list)   # Physical tables this traces to
    defined_in: str = ""                                     # "CTE:batch_summary" / "SELECT" / "MERGE"
    line_start: int = 0                                      # Starting line number in SQL
    line_end: int = 0                                        # Ending line number in SQL
    data_type: Optional[str] = None                          # Inferred type (DECIMAL, VARCHAR, etc.)
    context: str = "TOP"                                     # Nested context tracking
    is_output: bool = False                                  # True if this is a final SELECT output


class VariableDependency(BaseModel):
    """Represents a directed edge between two variables in the data flow graph."""
    source_id: str                           # Variable that produces data
    target_id: str                           # Variable that consumes data
    relationship: str                        # Edge type (SCHEMA, ALIAS, SELECT, JOIN, REF, etc.)
    operation: str = ""                      # Specific SQL operation (SUM, COALESCE, etc.)
    sql_context: str = ""                    # SQL fragment showing the relationship
