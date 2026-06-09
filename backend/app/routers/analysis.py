"""Analysis router — upload SQL and retrieve analysis results."""

from fastapi import APIRouter, HTTPException, Form

from app.models.api_models import AnalyzeResponse, ScriptSummary
from app.services.analysis_service import analyze_sql, get_script, list_scripts

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_sql_endpoint(
    sql_text: str = Form(..., description="SQL script content"),
    script_name: str = Form("unnamed.sql", description="Script filename"),
):
    """Upload SQL text and run the full extraction pipeline.

    Returns the analysis result including extracted variables,
    dependencies, and graph data.
    """
    if not sql_text or not sql_text.strip():
        raise HTTPException(status_code=400, detail="SQL text is required")

    try:
        result = analyze_sql(sql_text.strip(), script_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    return AnalyzeResponse(
        script_id=result["script_id"],
        script_name=result["script_name"],
        total_variables=result["total_variables"],
        total_dependencies=result["total_dependencies"],
        table_count=result.get("table_count", 0),
        cte_count=result.get("cte_count", 0),
    )


@router.get("/scripts", response_model=list[ScriptSummary])
async def list_scripts_endpoint():
    """List all previously analyzed scripts."""
    return list_scripts()


@router.get("/scripts/{script_id}")
async def get_script_endpoint(script_id: str):
    """Get the full analysis result for a script."""
    result = get_script(script_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Script '{script_id}' not found")
    return result
