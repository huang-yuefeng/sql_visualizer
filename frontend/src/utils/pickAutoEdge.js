/**
 * pickAutoEdge — R11-1: picks the edge auto-selected when an L2 graph
 * loads, so the reason panel never sits on "Click an edge to see its
 * flow reason".
 *
 * Priority (all from the level2 response as-is — nothing re-derived):
 *   1. An edge whose highlight_line falls inside the searched table's
 *      compound-node def range (the seed zone; the node is marked
 *      is_target and carries line_start/line_end — line range absent on
 *      older payloads, which skips this step gracefully).
 *   2. The first chain edge (flow_kind === 'chain') — the backbone flow.
 *   3. The first edge in the graph.
 *
 * R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow and are
 * hidden by default in the L2 view — auto-selection prefers visible
 * (flow) edges; only a graph with nothing else falls back to structure
 * edges, so the reason panel never shows a hidden edge's reason.
 *
 * Returns the edge's data object, or null when there is nothing to show.
 */
export default function pickAutoEdge(result) {
  const graph = result && result.graph;
  if (!graph) return null;

  const edges = (graph.edges || [])
    .map(e => e && e.data)
    .filter(e => e && typeof e.id === 'string' && e.id.length > 0);
  if (edges.length === 0) return null;

  // R19.4: structure edges are hidden by default — pick from the visible
  // pool whenever it has anything.
  const isStructure = (e) => e.edge_type === 'SCHEMA' || e.relationship === 'SCHEMA';
  const flowEdges = edges.filter(e => !isStructure(e));
  const pool = flowEdges.length > 0 ? flowEdges : edges;

  // 1. Seed zone: the searched table's compound node (is_target) bounds
  //    the reference site; its def range may not exist yet on older
  //    payloads — that's a graceful skip to the next priority.
  const seedNode = (graph.nodes || [])
    .map(n => n && n.data)
    .find(n => n && n.is_target === true);
  if (seedNode) {
    const lo = seedNode.line_start;
    const hi = seedNode.line_end;
    if (Number.isInteger(lo) && lo >= 1 && Number.isInteger(hi) && hi >= lo) {
      const zoneEdge = pool.find(e =>
        Number.isInteger(e.highlight_line) && e.highlight_line >= lo && e.highlight_line <= hi);
      if (zoneEdge) return zoneEdge;
    }
  }

  // 2. First chain edge.
  const chainEdge = pool.find(e => e.flow_kind === 'chain');
  if (chainEdge) return chainEdge;

  // 3. First edge in the (visible) graph.
  return pool[0];
}
