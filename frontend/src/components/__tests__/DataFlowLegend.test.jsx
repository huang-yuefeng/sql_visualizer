import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataFlowLegend from '../DataFlowLegend';
import { L2_TABLE_COLORS } from '../../utils/graphStyles';

// Convert a #RRGGBB token to the rgb(r, g, b) form jsdom reports for
// inline styles, so swatch assertions compare against L2_TABLE_COLORS.
function rgbOf(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function itemByLabel(container, label) {
  return [...container.querySelectorAll('.legend-item')].find(el => el.textContent.includes(label));
}

// (2026-08-13): the L2 legend lists ONLY the five table-node TYPES —
// display names from L2_TABLE_TYPE_NAMES, swatches from L2_TABLE_COLORS
// (the same palette the compound table styles use). The L2 node-role
// entries (Source node / Target node / Waypoint) and the "Field Marker"
// searched-field entry were REMOVED by user decision so the legend shows
// only the 5 table types.
describe('DataFlowLegend — L2 node-type legend', () => {
  it('renders only the five table-node type labels when level is L2', () => {
    const { container } = render(<DataFlowLegend level="L2" />);
    expect(screen.getByTestId('legend-l2-node-types')).toBeInTheDocument();
    // Exactly one legend title — the table-node types group.
    expect(screen.getByText('L2 Node Types')).toBeInTheDocument();
    expect(container.querySelectorAll('.legend-title')).toHaveLength(1);
    // The five table-node type labels.
    expect(screen.getByText('Source table')).toBeInTheDocument();
    expect(screen.getByText('Target table')).toBeInTheDocument();
    expect(screen.getByText('With table')).toBeInTheDocument();
    expect(screen.getByText('Anonymous table')).toBeInTheDocument();
    expect(screen.getByText('Alias table')).toBeInTheDocument();
  });

  it('does not render the removed L2 Node Roles or Field Marker groups', () => {
    render(<DataFlowLegend level="L2" />);
    // The removed group titles.
    expect(screen.queryByText('L2 Node Roles')).not.toBeInTheDocument();
    expect(screen.queryByText('Field Marker')).not.toBeInTheDocument();
    // The removed role / field-marker labels.
    expect(screen.queryByText('Source node')).not.toBeInTheDocument();
    expect(screen.queryByText('Target node')).not.toBeInTheDocument();
    expect(screen.queryByText('Waypoint')).not.toBeInTheDocument();
    expect(screen.queryByText('Searched field')).not.toBeInTheDocument();
  });

  it('no longer renders the flow-kind EDGE legend on L2', () => {
    render(<DataFlowLegend level="L2" />);
    // The R25 FlowKindLegend headline text must be gone.
    expect(screen.queryByText(/L2 Flow Kinds/)).not.toBeInTheDocument();
    expect(screen.queryByText(/every edge highlights/)).not.toBeInTheDocument();
    // And no flow-kind group chips (chain / field flow / write / …)
    expect(screen.queryByText('chain ✅')).not.toBeInTheDocument();
  });

  it('swatch colors match L2_TABLE_COLORS (solid borders)', () => {
    const { container } = render(<DataFlowLegend level="L2" />);

    // Five table-node type swatches — background/border from L2_TABLE_COLORS,
    // ALL rendered with a solid border (incl. With table and Alias table).
    const typeChecks = [
      ['Source table', L2_TABLE_COLORS.source],
      ['Target table', L2_TABLE_COLORS.target],
      ['With table', L2_TABLE_COLORS.withTable],
      ['Anonymous table', L2_TABLE_COLORS.anonymous],
      ['Alias table', L2_TABLE_COLORS.alias],
    ];
    typeChecks.forEach(([label, colors]) => {
      const item = itemByLabel(container, label);
      expect(item.querySelector('span:first-child').style.backgroundColor).toBe(rgbOf(colors.fill));
      expect(item.querySelector('span:first-child').style.borderColor).toBe(rgbOf(colors.border));
      expect(item.querySelector('span:first-child').style.borderStyle).toBe('solid');
    });
  });

  it('emphasizes all five type labels (bold)', () => {
    const { container } = render(<DataFlowLegend level="L2" />);
    ['Source table', 'Target table', 'With table', 'Anonymous table', 'Alias table'].forEach(label => {
      expect(itemByLabel(container, label).querySelector('span:last-child').style.fontWeight).toBe('700');
    });
  });

  it('keeps the structure-edge note reachable inside the L2 legend (footnote)', () => {
    const { container } = render(<DataFlowLegend level="L2" structureEdgesHidden structureEdgeCount={3} />);
    const note = container.querySelector('[data-testid="legend-structure-note"]');
    expect(note).not.toBeNull();
    expect(note.textContent).toContain('structure edges hidden (3)');
    // The note lives INSIDE the node-type legend.
    expect(container.querySelector('[data-testid="legend-l2-node-types"]').contains(note)).toBe(true);
  });

  it('hides the structure note when edges are visible or there are none', () => {
    const { container, rerender } = render(<DataFlowLegend level="L2" structureEdgesHidden={false} structureEdgeCount={3} />);
    expect(container.querySelector('[data-testid="legend-structure-note"]')).toBeNull();
    rerender(<DataFlowLegend level="L2" structureEdgesHidden structureEdgeCount={0} />);
    expect(container.querySelector('[data-testid="legend-structure-note"]')).toBeNull();
  });
});

// R28: the L1 branch is unchanged — it must still render the L1 table
// legend (Source/Intermediate/Output Table + Script).
describe('DataFlowLegend — L1 branch unchanged (R28)', () => {
  it('renders the L1 table legend, not the L2 node-type legend', () => {
    render(<DataFlowLegend level="L1" />);
    expect(screen.getByText('Source Table')).toBeInTheDocument();
    expect(screen.getByText('Intermediate Table')).toBeInTheDocument();
    expect(screen.getByText('Output Table')).toBeInTheDocument();
    expect(screen.getByText('Script')).toBeInTheDocument();
    expect(screen.queryByTestId('legend-l2-node-types')).not.toBeInTheDocument();
    expect(screen.queryByText('Source node')).not.toBeInTheDocument();
  });
});

// V2-N2 (2026-08-29): the Fit/Export controls used to float over the toolbar
// and covered the right half of the L2 view-mode <select>. DataFlowGraph now
// mounts them as the legend's `trailing` — an in-flow item of the legend's
// wrapping row, so the legend grows a row instead of overlapping the toolbar.
// (The no-overlap itself is geometry — asserted in the browser probe.)
describe('DataFlowLegend — trailing content flows INSIDE the legend row (V2-N2)', () => {
  const trailing = (
    <div className="graph-extra-controls">
      <button type="button" title="Fit (F)">🗺</button>
      <button type="button" title="Export PNG">📷</button>
    </div>
  );

  it('the L2 node-type legend renders trailing content inside its own box', () => {
    const { container } = render(<DataFlowLegend level="L2" structureEdgesHidden structureEdgeCount={2} trailing={trailing} />);
    const legend = container.querySelector('[data-testid="legend-l2-node-types"]');
    expect(legend).toBeInTheDocument();
    const controls = legend.querySelector('.graph-extra-controls');
    expect(controls).not.toBeNull();
    expect(controls.querySelector('[title="Fit (F)"]')).toBeInTheDocument();
    expect(controls.querySelector('[title="Export PNG"]')).toBeInTheDocument();
    // inside the legend row, i.e. a sibling of the legend items — never a
    // floating sibling of the legend container
    expect(controls.parentElement).toBe(legend);
  });

  it('the L1 legend renders the same trailing slot', () => {
    const { container } = render(<DataFlowLegend level="L1" trailing={trailing} />);
    const legend = container.querySelector('.dataflow-legend');
    expect(legend.querySelector('.graph-extra-controls')).not.toBeNull();
    expect(legend.lastElementChild.className).toBe('graph-extra-controls');
  });

  it('renders nothing extra when trailing is omitted', () => {
    const { container } = render(<DataFlowLegend level="L2" />);
    expect(container.querySelector('.graph-extra-controls')).toBeNull();
  });
});
