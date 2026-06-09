"""API request and response schemas."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request to analyze SQL text."""
    sql_text: str
    script_name: str = "unnamed.sql"


class AnalyzeResponse(BaseModel):
    """Response after successful analysis."""
    script_id: str
    script_name: str
    total_variables: int
    total_dependencies: int
    table_count: int
    cte_count: int


class ScriptSummary(BaseModel):
    """Summary of an analyzed script."""
    script_id: str
    script_name: str
    total_variables: int
    total_dependencies: int
    analyzed_at: str = ""


class VariableListResponse(BaseModel):
    """List of variables with optional filtering."""
    script_id: str
    script_name: str
    total: int
    variables: list[dict]


class VariableDetailResponse(BaseModel):
    """Detailed response for a single variable."""
    variable: dict
    dependencies_upstream: list[dict]   # Variables this depends on
    dependencies_downstream: list[dict] # Variables that depend on this


class ExplainRequest(BaseModel):
    """Request Claude NL explanation for variables."""
    variable_ids: list[str] = Field(default_factory=list)  # Empty = explain all


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: str = ""
