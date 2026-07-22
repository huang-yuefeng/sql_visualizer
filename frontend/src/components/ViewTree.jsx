import React from 'react';

export default function ViewTree({ views, activeViewId, onViewClick, onDeleteView }) {
  if (!views || views.length === 0) return null;

  return (
    <div className="view-tree">
      <h3>Views</h3>
      {views.map(v => (
        <div key={v.view_id} className="view-entry">
          <div
            className={`view-header ${activeViewId === v.view_id ? 'active' : ''}`}
            onClick={() => onViewClick(v.view_id)}
          >
            <span>{v.table}.{v.field}</span>
            <span className="view-scripts">({(v.script_ids || []).length} scripts)</span>
            <button className="btn-delete" onClick={(e) => { e.stopPropagation(); onDeleteView(v.view_id); }}>
              x
            </button>
          </div>
          {(v.children || []).length > 0 && (
            <div className="view-children">
              {(v.children || []).map(c => (
                <div key={c.view_id}
                  className={`view-child ${activeViewId === c.view_id ? 'active' : ''}`}
                  onClick={() => onViewClick(c.view_id)}
                >
                  {"📄"} {c.script_name}
                  <button className="btn-delete" onClick={(e) => { e.stopPropagation(); onDeleteView(c.view_id); }}>
                    x
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
