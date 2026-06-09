"""Graph router — retrieve graph data for Cytoscape.js visualization."""

from fastapi import APIRouter, HTTPException, UploadFile, Query

from app.services.analysis_service import get_script
from app.services.graph_service import build_graph_data
from app.services.sql_snippet_service import build_snippet_data
from app.services.io_graph_service import parse_output_csv, find_paths, build_io_graph_data

router = APIRouter()


@router.get("/scripts/{script_id}/graph")
async def get_graph(script_id: str, snippets: bool = Query(False)):
    """Get graph data (nodes + edges). Set snippets=true for per-edge SQL segments."""
    analysis = get_script(script_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Script '{script_id}' not found")
    result = build_graph_data(analysis)
    if snippets:
        result["snippets"] = build_snippet_data(analysis)
    return result


@router.post("/scripts/{script_id}/io_graph")
async def get_io_graph(script_id: str, csv_file: UploadFile):
    """Build input-output graph from a CSV defining output columns."""
    analysis = get_script(script_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Script '{script_id}' not found")
    try:
        text = (await csv_file.read()).decode("utf-8")
        outputs = parse_output_csv(text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {e}")
    if not outputs:
        raise HTTPException(status_code=400, detail="No valid output columns found in CSV")
    paths = find_paths(analysis, outputs)
    return build_io_graph_data(analysis, paths)
