"""Variables router — query variables."""

from fastapi import APIRouter, HTTPException, Query

from app.services.analysis_service import get_script
from app.models.api_models import VariableDetailResponse

router = APIRouter()


@router.get("/scripts/{script_id}/variables")
async def list_variables(
    script_id: str,
    search: str = Query("", description="Filter variables by name"),
    type: str = Query("", description="Filter by variable type"),
):
    """List all variables for a script, with optional search and type filter."""
    analysis = get_script(script_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Script '{script_id}' not found")

    variables = analysis.get("variables", [])
    line_map = analysis.get("line_map", {})

    if search:
        sl = search.lower()
        variables = [v for v in variables if sl in v["name"].lower()]
    if type:
        variables = [v for v in variables if v.get("variable_type") == type]

    for v in variables:
        vid = v["id"]
        if vid in line_map:
            v["line_start"], v["line_end"] = line_map[vid]

    return {
        "script_id": script_id,
        "script_name": analysis.get("script_name", ""),
        "total": len(variables),
        "variables": variables,
    }


@router.get("/scripts/{script_id}/variables/{var_id}")
async def get_variable(script_id: str, var_id: str):
    """Get details for a single variable including upstream/downstream dependencies."""
    analysis = get_script(script_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Script '{script_id}' not found")

    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])
    line_map = analysis.get("line_map", {})

    target_var = next((v for v in variables if v["id"] == var_id), None)
    if not target_var:
        raise HTTPException(status_code=404, detail=f"Variable '{var_id}' not found")

    if var_id in line_map:
        target_var["line_start"], target_var["line_end"] = line_map[var_id]

    upstream = [d for d in dependencies if d["target_id"] == var_id]
    downstream = [d for d in dependencies if d["source_id"] == var_id]

    return VariableDetailResponse(
        variable=target_var,
        dependencies_upstream=upstream,
        dependencies_downstream=downstream,
    )
