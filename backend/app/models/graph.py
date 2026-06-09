"""Graph models for Cytoscape.js visualization output."""

from pydantic import BaseModel


class GraphNode(BaseModel):
    """A node in the data flow graph, compatible with Cytoscape.js."""
    data: dict  # Must contain 'id' and 'label'; type-specific styling keys


class GraphEdge(BaseModel):
    """A directed edge in the data flow graph, compatible with Cytoscape.js."""
    data: dict  # Must contain 'id', 'source', 'target', and 'label'


class DataFlowGraph(BaseModel):
    """Complete graph representation for a SQL script."""
    script_id: str
    script_name: str
    total_variables: int
    total_dependencies: int
    nodes: list[dict]
    edges: list[dict]
