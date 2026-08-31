import React, { useRef, useState } from 'react';

// ── P2 fast-open (v3.3.194): index staleness line ───────────────────
// "Indexed 5m ago" under the workspace id — passive info, so the user can
// SEE how fresh the served index is. Pure display over the payload's own
// timestamp (GET /index serves it inside the `indexed` status object today;
// P1 may move it to a flat `indexed_at` — DataFlowApp already accepts both).
// Unparseable/absent → null → the line is not rendered at all, never a
// guess. A future timestamp (clock skew) reads as "just now".
//
// There is NO manual re-index control by design (user ruling 2026-08-31):
// the automatic content-hash catch-up covers changed scripts (the catch-up
// bar is the only reindex UI) and corrupt/missing caches fall back to a full
// build on open.
export function formatIndexedAge(iso, now = Date.now()) {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return null;
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(then).toLocaleDateString();
}

// T8 (#295): `showUploads` defaults to true (standalone use). The debugger
// left panel now hosts the embedded "My workspaces" section (which owns the
// upload pickers), so DataFlowApp passes showUploads={false} — WorkspacePanel
// then renders ONLY the in-workspace ID/staleness/progress/Delete display and
// never a second pair of upload buttons.
export default function WorkspacePanel({
  wsId, loading, progress, onUpload, onDelete, onError, showUploads = true,
  indexedAt = null, isCreator = false,
}) {
  const zipRef = useRef(null);
  const folderRef = useRef(null);
  const [zipping, setZipping] = useState(false);

  const handleZip = (e) => {
    const file = e.target.files[0];
    if (file) onUpload(file);
  };

  const handleFolder = async (e) => {
    const files = [...e.target.files];
    if (files.length === 0) return;

    setZipping(true);
    try {
      const JSZip = (await import('jszip')).default;
      const zip = new JSZip();

      files.forEach(f => {
        const relPath = f.webkitRelativePath || f.name;
        zip.file(relPath, f);
      });

      const blob = await zip.generateAsync({ type: 'blob' });
      const name = files[0].webkitRelativePath?.split('/')[0] || 'workspace';
      onUpload(new File([blob], `${name}.zip`));
    } catch (err) {
      // surface via the app error banner (factual state, no advice)
      onError?.(err && err.message ? err.message : 'Folder packing failed');
    } finally {
      setZipping(false);
    }
  };

  return (
    <div className="workspace-panel">
      <h3>Workspace</h3>
      {!wsId ? (
        showUploads ? (
          <div>
            <label className="upload-btn">
              Select Folder
              <input type="file" webkitdirectory="" directory="" multiple
                ref={folderRef} onChange={handleFolder}
                style={{ display: 'none' }} disabled={loading || zipping} />
            </label>
            {' '}
            <label className="upload-btn upload-btn-secondary">
              Upload .zip
              <input type="file" accept=".zip" ref={zipRef} onChange={handleZip}
                style={{ display: 'none' }} disabled={loading} />
            </label>
            {zipping && <div className="spinner">Packing folder...</div>}
            {loading && !zipping && <div className="spinner">Uploading...</div>}
          </div>
        ) : null
      ) : (
        <div>
          <div className="ws-id" data-ws-id={wsId}>ID: {wsId}</div>
          {indexedAt && (
            <div className="ws-indexed-at" data-testid="indexed-at" title={String(indexedAt)}>
              Indexed {formatIndexedAge(indexedAt)}
            </div>
          )}
          {progress && (
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${progress.total > 0 ? (progress.current/progress.total)*100 : 0}%` }}
              />
              <span>{progress.current}/{progress.total} {progress.phase}</span>
            </div>
          )}
          {loading && !progress && <div className="spinner">Loading...</div>}
          {/* Labelled by role, because the SAME endpoint does a different
              thing: the creator's removal DELETES the workspace and its files
              for everyone; a participant's only drops HER link (the files
              stay). The old unconditional "Delete Workspace" mislabelled the
              participant case. */}
          <button
            className="btn btn-outline btn-sm"
            data-testid="workspace-remove-btn"
            onClick={onDelete}
            style={{ marginTop: 8 }}
            title={isCreator
              ? 'Delete this workspace and its files for everyone'
              : 'Remove this shared workspace from your list only — the files stay'}
          >
            {isCreator ? 'Delete Workspace' : 'Remove from my list'}
          </button>
        </div>
      )}
    </div>
  );
}
