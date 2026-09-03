import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { forwardRef, useImperativeHandle } from 'react';
import DataFlowApp from '../DataFlowApp';
import { buildFieldStory } from '../utils/fieldStory';
import { computeStringMatches } from '../utils/stringMatch';
import {
  resumeWorkspace, getWorkspaceTree, scanWorkspace, indexWorkspace,
  listViews, searchDataFlow, getLevel2Graph,
} from '../api/client';

/**
 * USER BUG (2026-09-01, deployed 3.3.194) — two scroll channels in the SQL
 * panel did not move:
 *
 *   1. a Field Story step click left the highlighted line where it was, and
 *   2. turning the string-match layer ON never landed on its first match.
 *
 * SqlPanel owns the pixels (scrollTop on the line list only, header pinned);
 * DataFlowApp owns the two channels that ASK it to scroll. This suite pins the
 * DataFlowApp half of both: a story step click always drives a scroll (even a
 * step whose line is already the highlighted one — birth-41 / written-41 share
 * a line), and activating the string-match layer always lands on its FIRST
 * match. The centered-top math itself is pinned in SqlPanel.test.jsx.
 */

const { scrollCalls } = vi.hoisted(() => ({ scrollCalls: [] }));

// SqlPanel stub: records every imperative scrollToLine (the story path) and
// mirrors the two declarative scroll props into the DOM (the engine channel
// and the string-match browse channel), so a test can read what the panel was
// asked to scroll to.
vi.mock('../components/SqlPanel', () => ({
  default: forwardRef(function SqlPanelStub(props, ref) {
    useImperativeHandle(ref, () => ({
      scrollToLine: (line) => { scrollCalls.push(line); },
    }));
    return (
      <div
        data-testid="sql-stub"
        data-highlight={props.sqlHighlightLine ?? ''}
        data-sm-active={props.stringMatchActiveLine ?? ''}
      />
    );
  }),
}));

vi.mock('../components/MyWorkspaces', () => ({ default: () => null }));
vi.mock('../components/FolderTree', () => ({ default: () => null }));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
vi.mock('../components/ViewBar', () => ({ default: () => null }));
vi.mock('../components/WorkspacePanel', () => ({ default: () => null }));
vi.mock('../components/FilterPanel', () => ({
  default: (p) => (
    <button
      type="button"
      data-testid="run-search"
      onClick={() => p.onSearch('east5_stzfxxb', 'p_dt', 'downstream')}
    >
      run-search
    </button>
  ),
}));
vi.mock('../components/DataFlowGraph', () => ({
  default: () => <div data-testid="graph-stub" />,
}));

vi.mock('../api/client', () => ({
  addViewChild: vi.fn(),
  closeWorkspace: vi.fn(async () => ({})),
  deleteView: vi.fn(),
  deleteViewChild: vi.fn(),
  getLevel2Graph: vi.fn(),
  getWorkspaceStatus: vi.fn(),
  getWorkspaceTree: vi.fn(),
  getWorkspaceIndex: vi.fn(),
  indexWorkspace: vi.fn(),
  listViews: vi.fn(),
  removeFromMyHistory: vi.fn(),
  resumeWorkspace: vi.fn(),
  saveLayout: vi.fn(),
  scanWorkspace: vi.fn(),
  searchDataFlow: vi.fn(),
  uploadWorkspace: vi.fn(),
}));

// ── The EAST5 p_dt closure (the user's exact scenario) ──────────────────
// Same shape as the fieldStory suite's canonical fixture: the story is
// birth@41, written@41, filtered@190 — TWO steps on the SAME line, which is
// exactly the click the value-change scroll effect used to swallow.
function east5Closure() {
  const nodes = [
    { data: { id: 'east5', type: 'source_table', label: 'east5_stzfxxb', line_start: 41 } },
    { data: { id: 'east5.p_dt', type: 'field', parent: 'east5', label: 'p_dt', line_start: 41 } },
    { data: { id: 'out41', type: 'virtual_table', label: '⟐ output@41', line_start: 41 } },
    { data: { id: 'rrcdm', type: 'target_table', label: 'rrcdm.dm_table', line_start: 179 } },
    { data: { id: 'out179', type: 'virtual_table', label: '⟐ output@179', line_start: 179 } },
  ];
  const edges = [
    { data: { id: 'e-ref-41', source: 'east5.p_dt', target: 'out41',
              edge_type: 'REF', flow_kind: 'read', highlight_line: 41 } },
    { data: { id: 'e-tf-41', source: 'east5.p_dt', target: 'out41',
              edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 41 } },
    { data: { id: 'e-write-41', source: 'out41', target: 'east5',
              edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 41 } },
    { data: { id: 'e-filter-190', source: 'east5.p_dt', target: 'east5',
              edge_type: 'FILTER', flow_kind: 'field flow', highlight_line: 190 } },
  ];
  return { nodes, edges };
}

// The rendered script: `p_dt` on lines 3, 12, 41 and 190 — the first naive
// match (L3) is NOT the engine's anchor (L41), so the two channels are
// distinguishable in every assertion below.
const SQL_TEXT = [
  'SELECT 1;',                       // 1
  'FROM x',                          // 2
  'WHERE p_dt = 1',                  // 3  ← first string match
  '-- filler',                       // 4
  'SELECT 2;',                       // 5
  'SELECT 3;',                       // 6
  'SELECT 4;',                       // 7
  'SELECT 5;',                       // 8
  'SELECT 6;',                       // 9
  'SELECT 7;',                       // 10
  'SELECT 8;',                       // 11
  '  AND p_dt = 2',                  // 12 ← second string match
  ...Array.from({ length: 28 }, (_, i) => `-- pad ${i + 1}`), // 13..40
  'INSERT INTO east5_stzfxxb ... p_dt',                        // 41 ← engine anchor
  ...Array.from({ length: 148 }, (_, i) => `-- pad2 ${i + 1}`), // 42..189
  '  AND p_dt = 3',                  // 190 ← third string match
].join('\n');

function l2Payload() {
  const { nodes, edges } = east5Closure();
  const graph = { nodes, edges };
  return {
    graph,
    full_graph: graph,
    full_merged: graph,
    sql_text: SQL_TEXT,
    search_matched: true,
    flow_node_ids: ['east5.p_dt'],
    flow_edge_ids: edges.map(e => e.data.id),
    parse_errors: [],
  };
}

const SEARCH_VIEW = {
  view_id: 'v1',
  table: 'east5_stzfxxb',
  field: 'p_dt',
  script_ids: ['east5.sql'],
  l1_graph: { nodes: [], edges: [] },
  match_mode: 'no_flow',
  message: 'No reading flow for east5_stzfxxb.p_dt',
  direction: 'downstream',
};

async function mountToL2() {
  resumeWorkspace.mockResolvedValue({ state_version: 0, layouts: {}, creator_username: 'u@hsbc.com' });
  getWorkspaceTree.mockResolvedValue(null);
  scanWorkspace.mockResolvedValue({ type: 'folder', name: 'ws', children: [] });
  indexWorkspace.mockResolvedValue({
    table_index: { east5_stzfxxb: { fields: ['p_dt'] } },
    field_index: { p_dt: { tables: ['east5_stzfxxb'] } },
  });
  listViews.mockResolvedValue({ views: [] });
  render(<DataFlowApp openWorkspaceId="ws1" username="u@hsbc.com" />);
  await screen.findByTestId('run-search');
  searchDataFlow.mockResolvedValue(SEARCH_VIEW);
  await act(async () => { fireEvent.click(screen.getByTestId('run-search')); });
  getLevel2Graph.mockResolvedValue(l2Payload());
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Open east5.sql L2' }));
  });
  await screen.findByText(/Level 2 Detail/);
}

const storyLines = () => {
  const { nodes, edges } = east5Closure();
  const graph = { nodes, edges };
  const story = buildFieldStory({
    graph, fullGraph: graph, mergedGraph: graph,
    table: 'east5_stzfxxb', field: 'p_dt',
  });
  return story.steps.map(s => s.line);
};

const matchLines = () => computeStringMatches(SQL_TEXT, 'p_dt').map(m => m.line);

const stepChip = (n) => screen.getByTitle(new RegExp(`^Step ${n}:`));
const smActive = () => screen.getByTestId('sql-stub').dataset.smActive;
const highlight = () => screen.getByTestId('sql-stub').dataset.highlight;
const toggle = () => screen.getByRole('button', { name: 'Toggle string-match layer' });
const nextMatch = () => screen.getByRole('button', { name: 'Next string match' });
const prevMatch = () => screen.getByRole('button', { name: 'Previous string match' });

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  scrollCalls.length = 0;
});

describe('Field Story step click scrolls the SQL panel (user bug 1)', () => {
  it('drives one scroll per step click, including a step on an ALREADY highlighted line', async () => {
    await mountToL2();
    const lines = storyLines();
    expect(lines.length).toBeGreaterThanOrEqual(3);
    expect(lines[0]).toBe(lines[1]); // the repeated-line case: birth@41 / written@41

    for (let i = 0; i < lines.length; i += 1) {
      await act(async () => { fireEvent.click(stepChip(i + 1)); });
      // every click asks the panel to scroll, even when the line is unchanged
      expect(scrollCalls).toHaveLength(i + 1);
      expect(scrollCalls[i]).toBe(lines[i]);
      // the engine channel still carries the same line (amber anchor)
      expect(highlight()).toBe(String(lines[i]));
    }
    expect(scrollCalls).toEqual(lines);
  });

  it('re-scrolls a repeated line after the panel was scrolled elsewhere', async () => {
    await mountToL2();
    const lines = storyLines();
    await act(async () => { fireEvent.click(stepChip(1)); });
    expect(scrollCalls).toEqual([lines[0]]);

    // step 2 sits on the SAME line: the click still asks for the scroll
    await act(async () => { fireEvent.click(stepChip(2)); });
    expect(scrollCalls).toEqual([lines[0], lines[1]]);
    expect(scrollCalls[1]).toBe(scrollCalls[0]);
  });
});

describe('String-match layer activation scrolls to the FIRST match (user bug 2)', () => {
  it('landing the layer ON selects the first match line', async () => {
    await mountToL2();
    const matches = matchLines();
    expect(matches.length).toBeGreaterThanOrEqual(3);

    // browse inactive while the layer sits in its default ON state
    expect(smActive()).toBe('');

    // OFF → ON: the FIRST match becomes the active line
    await act(async () => { fireEvent.click(toggle()); });
    expect(smActive()).toBe('');
    await act(async () => { fireEvent.click(toggle()); });
    expect(smActive()).toBe(String(matches[0]));
  });

  it('re-lands on the first match on EVERY activation, never on the browsed one', async () => {
    await mountToL2();
    const matches = matchLines();

    await act(async () => { fireEvent.click(toggle()); });
    await act(async () => { fireEvent.click(toggle()); });
    expect(smActive()).toBe(String(matches[0]));

    // browse forward, hide, show again → back to the FIRST match
    await act(async () => { fireEvent.click(nextMatch()); });
    expect(smActive()).toBe(String(matches[1]));
    await act(async () => { fireEvent.click(toggle()); });
    expect(smActive()).toBe('');
    await act(async () => { fireEvent.click(toggle()); });
    expect(smActive()).toBe(String(matches[0]));
  });

  it('the browse buttons move the active line one match at a time (wraparound)', async () => {
    await mountToL2();
    const matches = matchLines();
    await act(async () => { fireEvent.click(toggle()); });
    await act(async () => { fireEvent.click(toggle()); });

    await act(async () => { fireEvent.click(nextMatch()); });
    expect(smActive()).toBe(String(matches[1]));
    await act(async () => { fireEvent.click(nextMatch()); });
    expect(smActive()).toBe(String(matches[2]));
    await act(async () => { fireEvent.click(prevMatch()); });
    expect(smActive()).toBe(String(matches[1]));
  });

  it('the engine anchor is never written by the string-match channels', async () => {
    await mountToL2();
    const matches = matchLines();
    await act(async () => { fireEvent.click(stepChip(1)); });
    const engineLine = highlight();
    expect(engineLine).toBe(String(storyLines()[0]));

    await act(async () => { fireEvent.click(toggle()); });
    await act(async () => { fireEvent.click(toggle()); });
    await act(async () => { fireEvent.click(nextMatch()); });
    // the browse channel moved; the R37 channel did not follow it
    expect(smActive()).toBe(String(matches[1]));
    expect(highlight()).toBe(engineLine);
  });
});
