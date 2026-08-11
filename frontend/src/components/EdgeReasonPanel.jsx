import React from 'react';

/**
 * EdgeReasonPanel — R25/§8.8, rendered BELOW the SQL panel in L2.
 *
 * Shows the clicked edge's (a) flow kind, (b) anchor line, and (c) the
 * extraction-time reason string — `<kind> — <flow string>` — with the
 * current edge's own ‖…‖-wrapped segment emphasized (bold + edge color)
 * so the user sees exactly where the clicked edge sits in the flow.
 *
 * R20 (path-scoped reasons): the flow string is the FULL path from the
 * source to the target — `source@L… → … → ‖own segment‖ → … → target@L…`
 * — with exactly ONE ‖…‖-wrapped segment (the own segment) somewhere in
 * the middle. The split-based rendering below handles any position: the
 * own segment is emphasized, everything else stays plain. Fallback
 * reasons without a ‖…‖ segment render as one plain string, as before.
 *
 * The reason string is built at L2 build time from the closure walk and
 * rendered as-is — never reconstructed at render.
 *
 * R26 (2026-08-11): the R11-3 "Code evidence" block is removed — the
 * script panel already shows the full SQL with the clicked edge's anchor
 * line highlighted, so the single-line rows only duplicated that with
 * less context. The panel renders kind + anchor + reason only; a backend
 * `mech` payload (if any) is simply ignored.
 */
export default function EdgeReasonPanel({ edge, height }) {
  // Issue 1 (fix 2026-08-11): the panel has a CONSTANT height in every
  // state (empty / content) until the user drags — the height prop comes
  // from DataFlowApp's reasonPanelHeight state. A constant height means
  // an edge click never changes the panel's size, so the graph-canvas
  // ResizeObserver never fires and the L2 viewport never auto-refits on
  // click. Long content scrolls internally (overflow-y: auto on
  // .edge-reason-panel).
  const panelStyle = height !== undefined ? { height } : undefined;

  if (!edge) {
    return (
      <div className="edge-reason-panel edge-reason-empty" style={panelStyle} data-testid="edge-reason-panel"
        role="status" aria-live="polite">
        <span className="edge-reason-title">Flow Reason</span>
        <span className="edge-reason-hint">Click an edge to see its flow reason</span>
      </div>
    );
  }

  const kind = edge.flow_kind || '';
  const color = edge.color || '#5DADE2';
  const anchor = edge.highlight_line;
  const reason = edge.reason || '';

  // Split on ‖…‖-wrapped segments (the clicked edge's own flow segment).
  // Works for the legacy short flow string AND the R20 path-scoped form
  // (`source@L… → … → ‖own‖ → … → target@L…`): exactly one ‖…‖ segment
  // in the middle gets emphasized, the rest renders plain. A fallback
  // reason without any ‖…‖ (or with an unmatched ‖) stays one plain
  // string; multiple segments (backend anomaly) each get emphasized.
  const segments = reason.split(/(‖[^‖]*‖)/g).filter(Boolean);

  return (
    <div className="edge-reason-panel" style={panelStyle} data-testid="edge-reason-panel"
      role="status" aria-live="polite">
      <span className="edge-reason-title">Flow Reason</span>
      {kind && (
        <span className="edge-reason-kind" style={{ color, borderColor: color }}>
          {kind}
        </span>
      )}
      {Number.isInteger(anchor) && anchor >= 1 && (
        <span className="edge-reason-anchor">Anchor: L{anchor}</span>
      )}
      <div className="edge-reason-text">
        {segments.length > 0 ? segments.map((seg, i) =>
          /^‖.*‖$/.test(seg) ? (
            <strong key={i} className="edge-reason-segment" style={{ color }}>
              {seg.slice(1, -1)}
            </strong>
          ) : (
            <span key={i}>{seg}</span>
          )
        ) : (reason || '—')}
      </div>
    </div>
  );
}
