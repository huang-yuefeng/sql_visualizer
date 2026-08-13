import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataFlowLegend from '../DataFlowLegend';
import { L2_ROLE_COLORS, SEARCHED_FIELD_COLOR } from '../../utils/graphStyles';

// Convert a #RRGGBB token to the rgb(r, g, b) form jsdom reports for
// inline styles, so swatch assertions compare against L2_ROLE_COLORS.
function rgbOf(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function itemByLabel(container, label) {
  return [...container.querySelectorAll('.legend-item')].find(el => el.textContent.includes(label));
}

// R28 (2026-08-11): the L2 legend is a NODE legend — Source node / Target
// node / Waypoint with swatches matching L2_NODE_ROLE_STYLES — replacing
// the flow-kind EDGE legend (R25 rule 5 already labels every edge at its
// midpoint with its flow kind; the old legend only duplicated the graph).
describe('DataFlowLegend — L2 node-role legend (R28)', () => {
  it('renders the node roles when level is L2 (incl. the searched field)', () => {
    render(<DataFlowLegend level="L2" />);
    expect(screen.getByTestId('legend-l2-node-roles')).toBeInTheDocument();
    expect(screen.getByText('L2 Node Roles')).toBeInTheDocument();
    expect(screen.getByText('Source node')).toBeInTheDocument();
    expect(screen.getByText('Target node')).toBeInTheDocument();
    expect(screen.getByText('Waypoint')).toBeInTheDocument();
    expect(screen.getByText('Searched field')).toBeInTheDocument();
  });

  it('no longer renders the flow-kind EDGE legend on L2', () => {
    render(<DataFlowLegend level="L2" />);
    // The R25 FlowKindLegend headline text must be gone.
    expect(screen.queryByText(/L2 Flow Kinds/)).not.toBeInTheDocument();
    expect(screen.queryByText(/every edge highlights/)).not.toBeInTheDocument();
    // And no flow-kind group chips (chain / field flow / write / …)
    expect(screen.queryByText('chain ✅')).not.toBeInTheDocument();
  });

  it('swatch colors match L2_ROLE_COLORS (the L2_NODE_ROLE_STYLES palette)', () => {
    const { container } = render(<DataFlowLegend level="L2" />);
    const source = itemByLabel(container, 'Source node');
    expect(source.querySelector('span:first-child').style.backgroundColor).toBe(rgbOf(L2_ROLE_COLORS.source.fill));
    expect(source.querySelector('span:first-child').style.borderColor).toBe(rgbOf(L2_ROLE_COLORS.source.border));

    const target = itemByLabel(container, 'Target node');
    expect(target.querySelector('span:first-child').style.backgroundColor).toBe(rgbOf(L2_ROLE_COLORS.target.fill));
    expect(target.querySelector('span:first-child').style.borderColor).toBe(rgbOf(L2_ROLE_COLORS.target.border));

    const waypoint = itemByLabel(container, 'Waypoint');
    expect(waypoint.querySelector('span:first-child').style.backgroundColor).toBe(rgbOf(L2_ROLE_COLORS.waypoint.fill));
    expect(waypoint.querySelector('span:first-child').style.borderColor).toBe(rgbOf(L2_ROLE_COLORS.waypoint.border));
    // Waypoints render a dashed border — the L2 node style is dashed too.
    expect(waypoint.querySelector('span:first-child').style.borderStyle).toBe('dashed');

    // The searched field swatch is solid gold (matching
    // node[type="field"][is_target]) and rendered as a circle (fields are
    // ellipses in the graph).
    const searched = itemByLabel(container, 'Searched field');
    expect(searched.querySelector('span:first-child').style.backgroundColor).toBe(rgbOf(SEARCHED_FIELD_COLOR));
    expect(searched.querySelector('span:first-child').style.borderColor).toBe(rgbOf(SEARCHED_FIELD_COLOR));
    expect(searched.querySelector('span:first-child').style.borderStyle).toBe('solid');
    expect(searched.querySelector('span:first-child').style.borderRadius).toBe('50%');
  });

  it('emphasizes source, target and searched-field labels (bold); waypoint stays plain', () => {
    const { container } = render(<DataFlowLegend level="L2" />);
    expect(itemByLabel(container, 'Source node').querySelector('span:last-child').style.fontWeight).toBe('700');
    expect(itemByLabel(container, 'Target node').querySelector('span:last-child').style.fontWeight).toBe('700');
    expect(itemByLabel(container, 'Searched field').querySelector('span:last-child').style.fontWeight).toBe('700');
    expect(itemByLabel(container, 'Waypoint').querySelector('span:last-child').style.fontWeight).toBe('');
  });

  it('keeps the structure-edge note reachable inside the L2 legend (footnote)', () => {
    const { container } = render(<DataFlowLegend level="L2" structureEdgesHidden structureEdgeCount={3} />);
    const note = container.querySelector('[data-testid="legend-structure-note"]');
    expect(note).not.toBeNull();
    expect(note.textContent).toContain('structure edges hidden (3)');
    // The note lives INSIDE the node-role legend.
    expect(container.querySelector('[data-testid="legend-l2-node-roles"]').contains(note)).toBe(true);
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
  it('renders the L1 table legend, not the L2 node-role legend', () => {
    render(<DataFlowLegend level="L1" />);
    expect(screen.getByText('Source Table')).toBeInTheDocument();
    expect(screen.getByText('Intermediate Table')).toBeInTheDocument();
    expect(screen.getByText('Output Table')).toBeInTheDocument();
    expect(screen.getByText('Script')).toBeInTheDocument();
    expect(screen.queryByTestId('legend-l2-node-roles')).not.toBeInTheDocument();
    expect(screen.queryByText('Source node')).not.toBeInTheDocument();
  });
});
