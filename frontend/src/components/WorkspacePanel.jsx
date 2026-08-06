import React, { useRef, useState } from 'react';

export default function WorkspacePanel({ wsId, loading, progress, onUpload, onDelete, onError }) {
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
      ) : (
        <div>
          <div className="ws-id" data-ws-id={wsId}>ID: {wsId}</div>
          {progress && (
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${(progress.current/progress.total)*100}%` }} />
              <span>{progress.current}/{progress.total} {progress.phase}</span>
            </div>
          )}
          {loading && !progress && <div className="spinner">Loading...</div>}
          <button className="btn btn-outline btn-sm" onClick={onDelete} style={{ marginTop: 8 }}>
            Delete Workspace
          </button>
        </div>
      )}
    </div>
  );
}
