import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

// R37 — node click scrolls the SQL panel to the node's definition line.
// Source-contract checks (the channel is React state + cytoscape wiring; a
// mounted render adds nothing these text contracts miss — same reasoning as
// hoverEnlarge.test.js).
const readSrc = rel => readFileSync(new URL(rel, import.meta.url), 'utf8');
const appSrc = readSrc('../../DataFlowApp.jsx');
const graphSrc = readSrc('../../components/DataFlowGraph.jsx');
const hookSrc = readSrc('../../hooks/useCytoscapeGraph.js');

describe('R37 — L2 node click scrolls SQL to the definition line', () => {
  it('hook registers the node tap pass-through', () => {
    expect(hookSrc).toMatch(/onNodeTap\)?\s+cy\.on\('tap', 'node'/);
  });

  it('DataFlowGraph gates node taps to L2 and forwards node data', () => {
    expect(graphSrc).toMatch(/onNodeTap:\s*\(e\)\s*=>\s*\{[^}]*level === 'L2'[^}]*onNodeClick\?\.\(e\.target\.data\(\)\)/s);
  });

  it('DataFlowApp handler guards: integer line_start >= 1, else no-op', () => {
    const handler = appSrc.match(/const handleNodeClick = useCallback[\s\S]*?\}, \[\]\);/)?.[0] || '';
    expect(handler).toContain('nodeData.line_start');
    expect(handler).toMatch(/Number\.isInteger\(ln\) && ln >= 1/);
    expect(handler).toContain('setSelectedEdge(null)');
  });

  it('shares the ONE sqlHighlightLine channel with edge clicks (last wins)', () => {
    expect(appSrc).toMatch(/const \[sqlHighlightLine, setSqlHighlightLine\] = useState\(null\)/);
    // derived-value removal — the channel is stateful now
    expect(appSrc).not.toMatch(/const sqlHighlightLine =/);
    // edge handler writes it; clears keep it in sync
    expect(appSrc.match(/const handleEdgeClick = useCallback[\s\S]*?\}, \[\]\);/)?.[0])
      .toContain('setSqlHighlightLine');
    expect(appSrc.match(/const clearEdgeSelection = useCallback[\s\S]*?\}, \[\]\);/)?.[0])
      .toContain('setSqlHighlightLine(null)');
  });

  it('L2 graph instance receives onNodeClick; L1 does not', () => {
    const l2 = appSrc.match(/<DataFlowGraph[^>]*level="L2"[^>]*>\/?/s)?.[0] || '';
    expect(l2).toContain('onNodeClick={handleNodeClick}');
  });
});
