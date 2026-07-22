import React from 'react';

/**
 * ViewBar — Horizontal tab strip for view management
 * 
 * Replaces ViewTree per L1L2_DISPLAY_REDESIGN.md §3.1.
 * Each search becomes a tab. Active tab ≡ active view.
 * L2 child views appear as subtabs within their parent.
 */
export default function ViewBar({ views, activeViewId, onSelect, onRemove, onRemoveChild }) {
  if (!views || views.length === 0) return null;

  return (
    <div className="view-bar">
      {/* [+ New Search] button (R11.5) */}
      <div className="view-bar-new" onClick={() => { const inp = document.querySelector('[aria-label="Type table name..."]'); if (inp) { inp.focus(); inp.select(); } }} title="New search">
        <span>+ New Search</span>
      </div>
      {views.map(v => {
        const isActive = v.view_id === activeViewId;
        const hasChildren = v.children && v.children.length > 0;
        const childActive = hasChildren && v.children.some(c => c.view_id === activeViewId);
        
        return (
          <div key={v.view_id} className="view-bar-group">
            <div
              className={`view-bar-tab ${isActive || childActive ? 'active' : ''}`}
              onClick={() => onSelect && onSelect(v.view_id)}
              title={`${v.table || ''}.${v.field || ''} (${v.script_ids?.length || v.script_count || 0} scripts)`}
            >
              <span className="view-bar-tab-icon">🔍</span>
              <span className="view-bar-tab-label">
                {v.table || '?'}.{v.field || '?'}
                <span className="view-bar-tab-count">({v.script_ids?.length || v.script_count || 0})</span>
              </span>
              <button
                className="view-bar-tab-close"
                onClick={(e) => { e.stopPropagation(); onRemove && onRemove(v.view_id); }}
                title="Remove view"
              >×</button>
            </div>
            
            {/* Child L2 tabs */}
            {hasChildren && (isActive || childActive) && (
              <div className="view-bar-children">
                {v.children.map(child => {
                  const childIsActive = child.view_id === activeViewId;
                  return (
                    <div
                      key={child.view_id}
                      className={`view-bar-subtab ${childIsActive ? 'active' : ''}`}
                      onClick={() => onSelect && onSelect(child.view_id)}
                      title={child.label || child.script_name || 'Script'}
                    >
                      <span className="view-bar-subtab-icon">📄</span>
                      <span className="view-bar-subtab-label">
                        {child.label || child.script_name || 'Script'}
                      </span>
                      <button
                        className="view-bar-subtab-close"
                        onClick={(e) => { e.stopPropagation(); onRemoveChild && onRemoveChild(v.view_id, child.view_id); }}
                        title="Close L2"
                      >×</button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
