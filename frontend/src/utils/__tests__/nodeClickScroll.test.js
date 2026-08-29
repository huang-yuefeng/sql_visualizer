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

// F-B2 (S4 finding 6, 2026-08-29): a clicked element whose payload line is
// 0/absent used to clear the previous highlight and light NOTHING — a silent
// no-op (23 such TVF-alias edges in one S4 view). A short neutral notice in
// the L2 graph area now says why and self-clears on the next valid click.
describe('F-B2 — zero-line clicks say so instead of failing silently', () => {
  it('the notice channel exists', () => {
    expect(appSrc).toMatch(/const \[sqlLineNotice, setSqlLineNotice\] = useState\(null\)/);
  });

  it('both handlers clear the notice on a valid line and set it on line 0/absent', () => {
    const edge = appSrc.match(/const handleEdgeClick = useCallback[\s\S]*?\}, \[\]\);/)?.[0] || '';
    const node = appSrc.match(/const handleNodeClick = useCallback[\s\S]*?\}, \[\]\);/)?.[0] || '';
    for (const handler of [edge, node]) {
      expect(handler).not.toBe('');
      expect(handler).toMatch(/setSqlHighlightLine\(ln\);\s*setSqlLineNotice\(null\)/);
      expect(handler).toMatch(/setSqlHighlightLine\(null\);\s*setSqlLineNotice\('this element has no SQL line'\)/);
    }
  });

  it('canvas tap clears the notice with the selection', () => {
    expect(appSrc.match(/const clearEdgeSelection = useCallback[\s\S]*?\}, \[\]\);/)?.[0])
      .toContain('setSqlLineNotice(null)');
  });

  it('renders the notice as a NEUTRAL bottom-slot banner in the L2 graph area', () => {
    expect(appSrc).toMatch(/className="no-match-banner banner-bottom banner-neutral"/);
    // bottom slot (never over the toolbar) + neutral (informational) styles
    const css = readSrc('../../styles/app.css');
    expect(css).toMatch(/\.no-match-banner\.banner-bottom\s*\{[^}]*bottom: 8px/s);
    expect(css).toMatch(/\.no-match-banner\.banner-neutral\s*\{/);
  });

  it('the notice stacks ABOVE the parse-errors banner when both render (SHOULD-FIX #4)', () => {
    // Both bottom-slot banners would sit at bottom:8px and paint over each
    // other; the LATER sibling in DataFlowApp.jsx is the notice, so the
    // sibling-offset rule must move IT, not the parse-errors block.
    const css = readSrc('../../styles/app.css');
    expect(css).toMatch(
      /\.no-match-banner\.banner-bottom\s*~\s*\.no-match-banner\.banner-bottom\s*\{[^}]*bottom:\s*56px/s);
    // DOM order contract: parse errors first, notice after — the `~`
    // combinator only reaches the LATER sibling.
    const l2 = appSrc.match(/className="inline-l2-graph"[\s\S]*?<DataFlowGraph/s)?.[0] || '';
    const parseErr = l2.indexOf('no-match-banner banner-bottom"');
    const notice = l2.indexOf('banner-bottom banner-neutral');
    expect(parseErr).toBeGreaterThan(-1);
    expect(notice).toBeGreaterThan(parseErr);
  });

  it('every L2 entry path drops a stale notice (applyL2Result)', () => {
    const apply = appSrc.match(/const applyL2Result = useCallback[\s\S]*?\}, \[\]\);/)?.[0] || '';
    expect(apply).toContain('setSqlLineNotice(null)');
  });
});

