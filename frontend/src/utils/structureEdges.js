/**
 * Structure-edge helpers (R19.4/R19.6a).
 *
 * SCHEMA structure/containment edges are NOT data flow — the L2 graph
 * hides them by default behind a display toggle (client-side only: the
 * edges stay in the graph model, the payload is untouched, nothing
 * re-fetches). These helpers identify structure edges from the payload
 * and count them per graph so legends/badges can reflect the toggle.
 *
 * NOTE: the payload's `category` field is NOT a reliable SCHEMA marker —
 * the backend maps SCHEMA/ALIAS/SUBSET/TABLE_FLOW all to "structure"
 * (graph_service.CATEGORY_MAP). Only the edge TYPE says "SCHEMA".
 */
export function isStructureEdge(edgeData) {
  if (!edgeData || typeof edgeData !== 'object') return false;
  return edgeData.edge_type === 'SCHEMA' || edgeData.relationship === 'SCHEMA';
}

/** Count SCHEMA structure edges in a cytoscape-style graph payload. */
export function countStructureEdges(graph) {
  const edges = (graph && Array.isArray(graph.edges)) ? graph.edges : [];
  return edges.reduce((n, e) => n + (isStructureEdge(e && e.data) ? 1 : 0), 0);
}
