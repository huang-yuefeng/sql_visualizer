"""Variable data models for SQL variable extraction and classification."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VariableType(str, Enum):
    """Classification of a SQL variable by origin."""
    DATABASE_TABLE = "database_table"       # Physical DB table (e.g. gps_transactions)
    TABLE_COLUMN = "table_column"           # Physical column (e.g. gps_transactions.amount)
    CTE_TABLE = "cte_table"                 # CTE alias (e.g. batch_summary)
    CTE_COLUMN = "cte_column"               # Column defined inside a CTE
    INTERMEDIATE = "intermediate"           # Aliased computed expression in SELECT
    WINDOW_RESULT = "window_result"         # Window function output (ROW_NUMBER, LAG, etc.)
    AGGREGATE = "aggregate"                 # Aggregation result (SUM, COUNT, AVG, etc.)
    CASE_RESULT = "case_result"             # CASE WHEN expression result
    FUNCTION_RESULT = "function_result"     # Function output (COALESCE, CAST, etc.)
    LITERAL = "literal"                     # Constant / literal value
    SUBQUERY_RESULT = "subquery_result"     # Scalar subquery result
    MERGE_TARGET = "merge_target"           # Target table in MERGE statement
    UNION_BRANCH = "union_branch"           # One side of a UNION / UNION ALL
    VIRTUAL_TABLE = "virtual_table"         # Output of a SELECT/JOIN (not stored)


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
    relationship: str                        # DIRECT_REFERENCE / AGGREGATION / TRANSFORMATION / WINDOW / CASE_BRANCH
    operation: str = ""                      # Specific SQL operation (SUM, COALESCE, etc.)
    sql_context: str = ""                    # SQL fragment showing the relationship
