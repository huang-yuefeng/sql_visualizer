import React, { useEffect, useState, useCallback, useRef } from 'react';
import * as api from '../api/client';

/**
 * R31 "My workspaces" drawer — the current user's workspace index + quota
 * meter + open/remove actions.
 *
 * - quota (cap 10, A-M2): the history cap IS the creation cap — a creator
 *   can never hold more than this many of their own workspaces.
 * - remove-from-history is ROLE-DEPENDENT (A-M1/A-M2): creator → physical
 *   delete (warned before it runs); participant → link removal only. The
 *   backend decides; this panel just warns the creator.
 * - An open here loads the workspace into the debugger (via onOpen).
 */
export default function MyWorkspaces({ open, onOpen, onUpload }) {
  const [items, setItems] = useState([]);
  const [cap, setCap] = useState(10);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [zipping, setZipping] = useState(false);
  const [resumeId, setResumeId] = useState('');
  const folderRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const body = await api.getMyWorkspaces();
      setItems(body.workspaces || []);
      setCap(body.cap || 10);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { if (open) refresh(); }, [open, refresh]);

  const handleRemove = async (w) => {
    const isCreator = w.role === 'creator';
    const warning = isCreator
      ? `You created this workspace — removing it DELETES it and all its files for everyone. Continue?`
      : `Remove this workspace from your list? (The files stay — you just won't see it here anymore.)`;
    if (!window.confirm(warning)) return;
    setBusyId(w.ws_id);
    try {
      await api.removeFromMyHistory(w.ws_id);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const uploadZip = useCallback(async (file) => {
    setUploading(true);
    setError(null);
    try {
      await onUpload(file);
      await refresh();
    } catch (err) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  }, [onUpload, refresh]);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    await uploadZip(file);
  };

  // #286: same folder picker as the debugger (WorkspacePanel.handleFolder) —
  // select a folder, pack it to zip client-side (JSZip), then upload. The
  // R31 dashboard used to be zip-only; the debugger's "Select Folder" is
  // unreachable until a workspace is open, so a fresh user could never
  // upload a folder at all (chicken-and-egg).
  const handleFolder = async (e) => {
    const files = [...e.target.files];
    e.target.value = '';
    if (files.length === 0) return;
    setZipping(true);
    setError(null);
    try {
      const JSZip = (await import('jszip')).default;
      const zip = new JSZip();
      files.forEach(f => {
        const relPath = f.webkitRelativePath || f.name;
        zip.file(relPath, f);
      });
      const blob = await zip.generateAsync({ type: 'blob' });
      const name = files[0].webkitRelativePath?.split('/')[0] || 'workspace';
      await uploadZip(new File([blob], `${name}.zip`));
    } catch (err) {
      setError(err && err.message ? err.message : 'Folder packing failed');
    } finally {
      setZipping(false);
    }
  };

  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 13, color: 'var(--ink-900)' }}>
          My workspaces
          <span style={{ color: 'var(--ink-400)', fontWeight: 400, marginLeft: 6 }}>
            {items.length}/{cap}
          </span>
        </h3>
        <button onClick={refresh} title="Refresh"
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink-400)', fontSize: 12 }}>
          ↻
        </button>
      </div>

      {error && (
        <div style={{ padding: '6px 8px', borderRadius: 4, background: 'var(--danger-soft)',
          color: 'var(--danger)', fontSize: 12, marginBottom: 8 }}>
          {error}
        </div>
      )}

      {items.length === 0 && (
        <div style={{ color: 'var(--ink-400)', fontSize: 12, padding: '4px 0 8px' }}>
          No workspaces yet — upload a folder to start.
        </div>
      )}

      <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 220, overflowY: 'auto' }}>
        {items.map((w) => (
          <li key={w.ws_id} style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '5px 6px',
            borderRadius: 4, marginBottom: 2, background: 'var(--bg-surface)',
          }}>
            <button onClick={() => onOpen(w.ws_id)}
              title={`Open ${w.ws_id}`}
              style={{
                flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--ink-900)', fontSize: 12, padding: 0,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
              <span style={{ marginRight: 4 }}>{w.role === 'creator' ? '📦' : '🔗'}</span>
              {w.ws_id.slice(0, 8)}
            </button>
            <span style={{
              fontSize: 10, color: w.role === 'creator' ? 'var(--accent)' : 'var(--ink-400)',
              background: w.role === 'creator' ? 'var(--accent-soft)' : 'transparent',
              padding: '1px 5px', borderRadius: 8,
            }}>
              {w.role === 'creator' ? 'creator' : 'shared'}
            </span>
            <button
              onClick={() => handleRemove(w)}
              disabled={busyId === w.ws_id}
              title={w.role === 'creator' ? 'Delete workspace (physical)' : 'Remove from my list'}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', fontSize: 13,
                color: 'var(--danger)', padding: '0 2px', opacity: busyId === w.ws_id ? 0.4 : 1,
              }}>
              ✕
            </button>
          </li>
        ))}
      </ul>

      <label style={{
        display: 'block', marginTop: 8, textAlign: 'center', cursor: uploading || zipping ? 'default' : 'pointer',
        padding: '7px 0', borderRadius: 6, border: '1px dashed var(--border-strong)',
        color: 'var(--accent)', fontSize: 12, fontWeight: 600,
      }}>
        {zipping ? 'Packing folder…' : uploading ? 'Uploading…' : '📁 Select Folder'}
        <input type="file" webkitdirectory="" directory="" multiple
          ref={folderRef} onChange={handleFolder}
          style={{ display: 'none' }} disabled={uploading || zipping} />
      </label>
      <label style={{
        display: 'block', marginTop: 6, textAlign: 'center', cursor: uploading || zipping ? 'default' : 'pointer',
        padding: '7px 0', borderRadius: 6, border: '1px solid var(--border-strong)',
        color: 'var(--ink-600)', fontSize: 12, fontWeight: 600,
      }}>
        + Upload a folder (zip)
        <input type="file" accept=".zip" onChange={handleUpload} style={{ display: 'none' }} disabled={uploading || zipping} />
      </label>

      {/* R31 §5.5: workspace-id resume box — any logged-in user who knows the
          id can open a shared workspace (A-H4: ids are never listed, only
          exchanged). Opens even if not in this user's index. */}
      <form onSubmit={(e) => { e.preventDefault(); if (resumeId.trim()) onOpen(resumeId.trim()); }}
        style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input
          value={resumeId}
          onChange={(e) => setResumeId(e.target.value)}
          placeholder="Open by workspace id…"
          style={{
            flex: 1, padding: '7px 10px', border: '1px solid var(--border-strong)',
            borderRadius: 6, fontSize: 12, color: 'var(--ink-900)', background: 'var(--bg-app)',
          }}
        />
        <button type="submit" style={{
          padding: '7px 12px', border: 'none', borderRadius: 6, cursor: 'pointer',
          background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, fontWeight: 600,
        }}>
          Open
        </button>
      </form>
    </div>
  );
}
