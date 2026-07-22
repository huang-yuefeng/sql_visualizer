/**
 * Edge Bundling for L1 — per L1L2_DISPLAY_REDESIGN.md §4.5
 * 
 * When >3 edges connect the same source↔target pair, merge them
 * into one thick "bundled" edge. Hover reveals individual connections.
 * L2 edges are NOT bundled by default.
 */

const BUNDLE_THRESHOLD = 3;

/**
 * Apply edge bundling to a Cytoscape instance.
 * Only bundles L1 table↔script edges.
 * 
 * @param {object} cy - Cytoscape instance
 * @param {boolean} unbundle - If true, remove all bundles and restore original edges
 */
export function applyEdgeBundling(cy, unbundle = false) {
  if (!cy) return;

  // Remove existing bundled edges
  cy.remove('.bundled-edge');

  if (unbundle) {
    // Restore hidden original edges
    cy.edges().forEach(e => e.style('display', 'element'));
    return;
  }

  // Only bundle in L1: table↔script edges (not field↔field in L2)
  const l1Edges = cy.edges().filter(e => {
    const src = e.source();
    const tgt = e.target();
    if (!src.length || !tgt.length) return false;
    const srcType = src.data('type') || '';
    const tgtType = tgt.data('type') || '';
    // Bundle only if one side is a table and the other is a script
    return (srcType.endsWith('_table') && tgtType === 'script_node') ||
           (tgtType.endsWith('_table') && srcType === 'script_node');
  });

  // Group edges by source↔target pair (unordered)
  const groups = new Map();
  l1Edges.forEach(e => {
    const s = e.data('source');
    const t = e.data('target');
    const key = [s, t].sort().join('||');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  });

  // Bundle groups with > THRESHOLD edges
  groups.forEach((edges, key) => {
    if (edges.length <= BUNDLE_THRESHOLD) return;

    // Hide original edges
    edges.forEach(e => e.style('display', 'none'));

    // Collect summary info
    const edgeTypes = [...new Set(edges.map(e => e.data('edge_type') || 'table_script'))];
    const roles = [...new Set(edges.flatMap(e => e.data('roles') || []))];
    const [s, t] = key.split('||');

    // Create bundled edge
    cy.add({
      group: 'edges',
      data: {
        id: `bundle_${key}`,
        source: s,
        target: t,
        label: `${edges.length} edges`,
        edge_type: 'bundled',
        bundled_count: edges.length,
        bundled_types: edgeTypes,
        bundled_roles: roles,
        child_edge_ids: edges.map(e => e.id()),
      },
      classes: 'bundled-edge',
    });
  });
}

/**
 * Unbundle all edges, restoring originals.
 */
export function unbundleAll(cy) {
  applyEdgeBundling(cy, true);
}
