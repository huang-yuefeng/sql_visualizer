import React from 'react';

/**
 * EdgeReasonPanel — R25/§8.8, rendered BELOW the SQL panel in L2.
 *
 * Shows the clicked edge's (a) flow kind, (b) anchor line, and (c) the
 * extraction-time reason string — `<kind> — <flow string>` — with the
 * current edge's own ‖…‖-wrapped segment emphasized (bold + edge color)
 * so the user sees exactly where the clicked edge sits in the flow.
 *
 * The reason string is built at L2 build time from the closure walk and
 * rendered as-is — never reconstructed at render.
 */
export default function EdgeReasonPanel({ edge }) {
  if (!edge) {
    return (
      <div className="edge-reason-panel edge-reason-empty" data-testid="edge-reason-panel">
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
  const segments = reason.split(/(‖[^‖]*‖)/g).filter(Boolean);

  return (
    <div className="edge-reason-panel" data-testid="edge-reason-panel">
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
