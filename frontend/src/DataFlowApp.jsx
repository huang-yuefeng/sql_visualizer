
import WorkspacePanel from './components/WorkspacePanel';
import MyWorkspaces from './components/MyWorkspaces';
import FolderTree from './components/FolderTree';
import FilterPanel from './components/FilterPanel';
import { recoverViewSearch } from './utils/recoverViewSearch';
import ViewBar from './components/ViewBar';
import DataFlowGraph from './components/DataFlowGraph';
import FieldStoryBar from './components/FieldStoryBar';
import SqlPanel from './components/SqlPanel';
import LogPanel from './components/LogPanel';
import ResolutionReport from './components/ResolutionReport';
import * as api from './api/client';
import pickAutoEdge from './utils/pickAutoEdge';
import { buildFieldStory } from './utils/fieldStory';
import { resolveFlowOnly } from './utils/flowVisibility';
import {
  computeStringMatches, classifyMatches, flowLineSet,
} from './utils/stringMatch';
import { resumeLayoutKey } from './utils/layoutPersistence';
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useResizable } from './utils/useResizable';
import './styles/resizable.css';

// R40.13: the layer's "hidden" payload — no bands at all (AC2). One shared
// instance, so a hidden render never allocates.
const EMPTY_MATCH_SET = new Set();

// P4 (2026-08-31): the catch-up poller's cadence and its TRANSIENT-failure
// budget. 1.5s ticks × 20 ≈ 30s of failing polls before the hold gives up on
// the honest "did not complete" exit — long enough to ride out a network
// blip, short enough that a dead backend never withholds search for good.
const CATCHUP_POLL_INTERVAL = 1500;
const CATCHUP_POLL_TICKS = 20;

export default function DataFlowApp({
  openWorkspaceId = null,
  onOpenWorkspace = null,
  onCloseWorkspace = null,
  username = null,
}) {
  const [wsId, setWsId] = useState(null);
  const [fileTree, setFileTree] = useState(null);
  const [selectedScripts, setSelectedScripts] = useState([]);
  const [tableIndex, setTableIndex] = useState({});
  const [fieldIndex, setFieldIndex] = useState({});
  const [fullTableIndex, setFullTableIndex] = useState({});
  const [fullFieldIndex, setFullFieldIndex] = useState({});
  const [indexed, setIndexed] = useState(false);
  const [views, setViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const parentViewIdRef = useRef(null);
  const [graphLevel, setGraphLevel] = useState('L1');
  // R42 (2026-08-28): per-level layout state. L2 OPENS in the ELK pipeline
  // layout (layered, ELK_DIRECTION='RIGHT' — left-to-right for landscape
  // screens); L1 keeps its snake default. Splitting the state means flipping
  // the L2 default can never move L1, and each toolbar's Snake/Pipeline
  // toggle drives only its own graph. Fields are unaffected by construction:
  // layout algorithms position tables only, field chips follow
  // table.pos + frozen offsets (layoutCore.applyLayout — the single site).
  const [l1LayoutMode, setL1LayoutMode] = useState('snake'); // 'snake' | 'pipeline'
  const [l2LayoutMode, setL2LayoutMode] = useState('pipeline'); // R42: L2 initial = left-to-right
  // R38 ruling (2026-08-27): the direction toggle is removed — downstream is
  // the ONLY direction (reading flow: "where does this field's value go").
  // Constant, not state. Persisted view rows may still carry
  // direction:'upstream' from R29-era searches; those values are deliberately
  // IGNORED — one direction everywhere (see the two getLevel2Graph call sites).
  const direction = 'downstream';
  const [l1Graph, setL1Graph] = useState(null);
  const [l2Graph, setL2Graph] = useState(null);
  const [sqlText, setSqlText] = useState('');
  const [currentScriptName, setCurrentScriptName] = useState('');
  const [selectedEdge, setSelectedEdge] = useState(null);
  // R37: THE single SQL-highlight channel — edge AND node clicks write it,
  // last click wins. `selectedEdge` stays edge-only, so a node click clears
  // it instead of leaving a mismatched edge highlighted.
  const [sqlHighlightLine, setSqlHighlightLine] = useState(null);
  // F-B2 (S4 finding 6): a clicked element whose payload line is 0/absent
  // used to fail silently (previous highlight cleared, nothing lit — 23 such
  // TVF-alias edges in one view). A short neutral notice in the L2 graph
  // area says why; it self-clears on the next valid click, on a canvas tap,
  // and on every L2 entry path (applyL2Result) / drop to L1.
  const [sqlLineNotice, setSqlLineNotice] = useState(null);
  const [l2Result, setL2Result] = useState(null);
  // L2 view toggle (#331, four modes): 'flow' (closure — the default on a
  // matched search), 'full' (entire script graph), 'flow-merged' and
  // 'full-merged' (line-merged views — a distinct node+edge set, not a
  // client-side filter). null = disabled (no search seed or the search did
  // not match — always show the full graph).
  const [l2ViewMode, setL2ViewMode] = useState(null);
  // L2 not-in-flow: the view's search field is not referenced in this
  // script — backend returns the FULL unfiltered script graph plus
  // search_matched:false + a message. Absence of search_matched = matched.
  const [l2NotInFlow, setL2NotInFlow] = useState(false);
  const [l2NotInFlowMessage, setL2NotInFlowMessage] = useState(null);
  // A3: statement-level parse errors from the level2 response
  // ({stmt_idx, detail}[]; [] when the script parses clean).
  const [l2ParseErrors, setL2ParseErrors] = useState([]);
  // ── Field Story step-through bar ──────────────────────────────────
  // storyActiveIndex: null = inactive (the bar still renders when steps
  // exist, but nothing on the graph is lit); a number = that step's
  // edges/nodes are lit and everything else dimmed (storyFocus below →
  // DataFlowGraph). storyAutoplay drives FieldStoryBar's 3s interval.
  // Both reset on EVERY L2 entry path (applyL2Result) — a fresh script
  // never inherits the previous story's focus or clock.
  const [storyActiveIndex, setStoryActiveIndex] = useState(null);
  const [storyAutoplay, setStoryAutoplay] = useState(false);
  // ── R40.13: the naive string-match diff layer (frontend-only) ──────
  // stringMatchCursor is the SEPARATE browse channel: 0-based index into the
  // ascending match list, null = inactive (no active line, no extra scroll —
  // the bands alone are the post-search state, so browsing never fights the
  // engine's own post-search scroll). It NEVER writes the R37
  // `sqlHighlightLine` channel. stringMatchVisible is the show/hide toggle
  // (default ON after every search, per design point 2) — session component
  // state, never persisted.
  const [stringMatchCursor, setStringMatchCursor] = useState(null);
  const [stringMatchVisible, setStringMatchVisible] = useState(true);
  // Search recovery (2026-08-27): when a PERSISTED view is opened from the
  // tree (old workspace → L1/L2), the search panel would stay empty and the
  // graph has no visible trace of which table.field it belongs to. The
  // recoverViewSearch lookup resolves the target from the views.json rows
  // (L2 rows carry it via their parent search row); the nonce makes every
  // tree navigation re-fire the panel injection even for identical targets.
  const [searchRecover, setSearchRecover] = useState(null);
  const recoverNonceRef = useRef(0);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [activeL1Table, setActiveL1Table] = useState(null);
  const [showLog, setShowLog] = useState(true);
  // R20: index-time orphan resolution report (folder_index_service payload)
  const [resolutionStats, setResolutionStats] = useState(null);
  const [orphanFieldSamples, setOrphanFieldSamples] = useState(null);
  // R20/M11: schema_candidates_summary {total, unique_owner, r6_collision}
  const [schemaCandidates, setSchemaCandidates] = useState(null);
  // A1: schema_evidence {present, tables, columns} (index response)
  const [schemaEvidence, setSchemaEvidence] = useState(null);

  // ── P2 fast-open (v3.3.194): index staleness + catching-up window ──
  // indexedAt is the index's own timestamp when the backend serves one (P1
  // may add/move the field) — absent → nothing rendered, never a guess.
  const [indexedAt, setIndexedAt] = useState(null);
  // Role, from the resume row. Purely a LABELLING gate: destructive-looking
  // controls must say what they actually do for THIS user (a participant's
  // "delete" only drops her own link, and view deletion is creator-only
  // server-side, #272). No write is gated here — the backend decides.
  const [isCreator, setIsCreator] = useState(false);
  // ── P1 catching-up window ──────────────────────────────────────────
  // While an incremental re-index is in flight the search scope (the index)
  // is missing the fresh content, so a search could return a FALSE
  // no_matches: search is withheld behind the honest progress bar and a
  // one-line status explains the wait. null = not catching up (the common
  // case). `canFix` says whether THIS user can rebuild (creator auto-trigger)
  // or is waiting on someone else's / cannot rebuild at all.
  const [catchUp, setCatchUp] = useState(null);
  // A participant (or anyone) opening a workspace whose index is STALE but
  // not being rebuilt: informational only, never a block — they cannot fix
  // it, and the creator's open is what refreshes it.
  const [staleHint, setStaleHint] = useState(false);

  // ── R31: layout persistence + concurrent-edit notice (A-M4/A-M5) ──
  // state_version drives the CAS save; resumeLayouts holds the shared
  // `{"l1": {node:[x,y]}, "l2:{script}": {...}}` map re-applied on render.
  const [stateVersion, setStateVersion] = useState(0);
  const [resumeLayouts, setResumeLayouts] = useState({});
  const [toast, setToast] = useState(null); // "state changed by X — refreshed"
  const wsIdRef = useRef(null);
  wsIdRef.current = wsId; // latest wsId for the unmount cleanup
  const stateVersionRef = useRef(0);
  // Coalesced pending saves keyed by (level, script) — L1 and L2 drags are
  // independent: an L2 drag arriving while an L1 save is already pending
  // must not clobber (and silently drop) the L1 save.
  const pendingLayoutRef = useRef(new Map()); // key -> {level, script, positions, version}
  const layoutTimerRef = useRef(null);
  const openedRef = useRef(null);          // guards the open-existing effect
  // The open tree's SQL files — the catch-up re-fire's POST /index body.
  // The backend ignores the list (#257: it always rebuilds the WHOLE
  // workspace index); it is sent for symmetry with the other call sites.
  const openScriptsRef = useRef([]);
  openScriptsRef.current = selectedScripts;

  const setVersion = useCallback((v) => {
    stateVersionRef.current = v;
    setStateVersion(v);
  }, []);

  // Save the coalesced positions at most once per second (design §4 Q4 /
  // §10.18): drags accumulate into pendingLayoutRef, one PUT per debounce
  // window. On a 409 the server's fresh state is loaded and the pending edit
  // is re-applied on top of it (A-M4) with a "refreshed" notice.
  const flushLayoutSave = useCallback(async () => {
    if (layoutTimerRef.current) {
      clearTimeout(layoutTimerRef.current);
      layoutTimerRef.current = null;
    }
    if (!wsIdRef.current) return;
    const pending = pendingLayoutRef.current;
    if (!pending.size) return;
    // Snapshot + clear BEFORE the awaits: a drag that lands mid-save
    // re-coalesces into a fresh entry (and arms its own timer), so it is
    // never lost — each (level, script) key saves independently.
    const entries = [...pending.values()];
    pending.clear();
    for (const { level, script, positions, version } of entries) {
      try {
        const res = await api.saveLayout(wsIdRef.current, level, script, positions, version);
        if (res.status === 409) {
          const body = await res.json().catch(() => null);
          const fresh = body?.detail?.fresh;
          if (fresh && fresh.state_version != null) {
            setVersion(fresh.state_version);
            if (fresh.layouts) setResumeLayouts(fresh.layouts);
            // E-M9 (#284): overlay the just-dragged positions on the fresh
            // state too — they are being re-applied on top of it (A-M4), so a
            // re-open must reflect them, not the open-time snapshot.
            setResumeLayouts(prev => ({ ...prev, [resumeLayoutKey(level, script)]: positions }));
            setToast('State changed by another user - refreshed');
            // Re-apply the pending edit on top of the fresh state (A-M4).
            pendingLayoutRef.current.set(
              resumeLayoutKey(level, script),
              { level, script, positions, version: fresh.state_version },
            );
            if (!layoutTimerRef.current) {
              layoutTimerRef.current = setTimeout(() => {
                layoutTimerRef.current = null;
                flushLayoutSave();
              }, 1000);
            }
          }
        } else if (res.ok) {
          const body = await res.json().catch(() => null);
          if (body && body.state_version != null) setVersion(body.state_version);
          // E-M9 (#284): the server CONFIRMED these positions — fold them into
          // resumeLayouts so a later re-open/re-search re-applies the LATEST
          // drag, never the open-time snapshot (which would undo the drag).
          setResumeLayouts(prev => ({ ...prev, [resumeLayoutKey(level, script)]: positions }));
        }
        // other non-OK: silent failure (design: silent-fail handling)
      } catch { /* silent */ }
    }
  }, [setVersion]);

  const scheduleLayoutSave = useCallback((level, script, positions) => {
    if (!wsIdRef.current) return;
    // Key by (level, script): repeated drags of the SAME key coalesce into
    // the latest positions, while a DIFFERENT key (e.g. an L1 drag while an
    // L2 save is pending) gets its own slot — never clobbered by the other.
    pendingLayoutRef.current.set(
      resumeLayoutKey(level, script),
      { level, script, positions, version: stateVersionRef.current },
    );
    if (layoutTimerRef.current) return; // a save is already pending — coalesce
    layoutTimerRef.current = setTimeout(() => {
      layoutTimerRef.current = null;
      flushLayoutSave();
    }, 1000);
  }, [flushLayoutSave]);

  // M-E1 (R42): the L2 layout-persistence key is split by view family —
  // merged views (flow-merged / full-merged) persist under
  // `l2:merged:{script}`, detailed views keep `l2:{script}`. The merged and
  // detailed graphs are DISTINCT node+edge sets (l2m_* vs l2e_* ids);
  // sharing one key made a drag in one view pin the other's table positions
  // on re-open. The prefix composes through resumeLayoutKey unchanged
  // (`l2:merged:X`); the backend treats the script value as a free-form key
  // (save_layout builds `f"l2:{script}"` verbatim), so no schema change.
  // BOTH the save path (handlePositionsChange) and the read path
  // (savedPositions below) derive from THIS value so they can never drift.
  const l2LayoutScriptKey = (l2ViewMode === 'flow-merged' || l2ViewMode === 'full-merged') && currentScriptName
    ? `merged:${currentScriptName}`
    : currentScriptName;

  // Drag-end positions → debounced autosave for the CURRENT level+script.
  // #309: the level is passed EXPLICITLY per graph. The shared callback must
  // not derive it from the GLOBAL graphLevel — while an L2 is open (graphLevel
  // === 'L2') the L1 graph stays mounted + draggable side-by-side, so an L1
  // drag would otherwise be written under the L2 key and corrupt the layout.
  const handlePositionsChange = useCallback((level, positions) => {
    scheduleLayoutSave(
      level,
      level === 'l2' ? l2LayoutScriptKey : null,
      positions,
    );
  }, [l2LayoutScriptKey, scheduleLayoutSave]);

  // Final save on close: when the keyed DataFlowApp unmounts (close
  // workspace / switch workspace / logout), flush the coalesced layout save
  // and end the visit (design §4 Q4: "final write on close").
  useEffect(() => {
    return () => {
      if (!wsIdRef.current) return;
      flushLayoutSave();
      api.closeWorkspace(wsIdRef.current).catch(() => {});
    };
  }, [flushLayoutSave]);

  // ── Resizable panel state ─────────────────────────────────────────
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [l2PanelHeight, setL2PanelHeight] = useState(420);
  const [l2PanelWidth, setL2PanelWidth] = useState(420);
  const [sqlPanelHeight, setSqlPanelHeight] = useState(250);

  const leftResize = useResizable({
    direction: 'horizontal', value: leftPanelWidth, defaultValue: 260, min: 0, max: 9999,
    onResize: (v) => { setLeftPanelWidth(v); document.documentElement.style.setProperty('--left-width', v + 'px'); },
  });
  const l2Resize = useResizable({
    direction: 'horizontal', value: l2PanelWidth, defaultValue: 420, min: 0, max: 9999, invert: true,
    onResize: (v) => { setL2PanelWidth(v); document.documentElement.style.setProperty('--l2-width', v + 'px'); },
  });
  const sqlResize = useResizable({
    direction: 'vertical', value: sqlPanelHeight, defaultValue: 250, min: 0, max: 9999, invert: true,
    onResize: (v) => { setSqlPanelHeight(v); document.documentElement.style.setProperty('--sql-height', v + 'px'); },
  });
  const activeView = views.find(v => v.view_id === activeViewId)
    || views.flatMap(v => v.children || []).find(c => c.view_id === activeViewId);

  // ── Apply a level2 response: graph + result + not-in-flow banner state.
  // Every L2 entry path goes through here so the banner can never go stale.
  const applyL2Result = useCallback((result) => {
    setL2Graph(result.graph);
    setL2Result(result);
    // L2 view toggle: default to 'flow-merged' (the line-merged closure,
    // one SQL line ≈ one edge) whenever the response carries the field-flow
    // closure (matched search); null (disabled) when there is no search seed
    // or the search did not match.
    setL2ViewMode(resolveFlowOnly(result) === true ? 'flow-merged' : null);
    // R25: every L2 entry path lands on a fresh graph — no stale edge
    // selection from a previous script.
    // R11-1: auto-select a sensible edge (seed-zone > chain > first) so
    // the SQL panel opens with an anchor line already highlighted.
    const autoEdge = pickAutoEdge(result);
    setSelectedEdge(autoEdge);
    // R37: the highlight line is now stateful — seed it from the auto edge
    // exactly as the old derived value did.
    {
      const ln = autoEdge && autoEdge.highlight_line;
      setSqlHighlightLine(Number.isInteger(ln) && ln >= 1 ? ln : null);
    }
    // Contract: search_matched === false → the search field is not in this
    // script (graph is the full unfiltered one); field absent from the
    // response means the search target matched (or none exists).
    const notInFlow = result.search_matched === false;
    setL2NotInFlow(notInFlow);
    setL2NotInFlowMessage(notInFlow ? (result.message || null) : null);
    // A3: parse_errors is a top-level array ({stmt_idx, detail}) — [] when none.
    setL2ParseErrors(result.parse_errors || []);
    // Field Story: every L2 entry path lands here — start each story
    // inactive (no stale dimming from the previous script) and paused.
    setStoryActiveIndex(null);
    setStoryAutoplay(false);
    // R40.13: the diff layer is ON after every search with no user action,
    // and the browse cursor starts inactive (the identity-reset effect below
    // is the general rule; this is the same contract applied at the same
    // site as the story reset so neither can go stale).
    setStringMatchCursor(null);
    setStringMatchVisible(true);
    // F-B2: a fresh script never inherits the previous one's no-SQL-line
    // notice.
    setSqlLineNotice(null);
  }, []);

  // ── R31: full reset of debugger state (no workspace lifecycle calls —
  //     the keyed DataFlowApp remount already ends the previous visit) ──
  const resetWorkspaceState = useCallback(() => {
    setWsId(null); setFileTree(null); setSelectedScripts([]);
    setTableIndex({}); setFieldIndex({}); setFullTableIndex({}); setFullFieldIndex({});
    setIndexed(false); setViews([]); setActiveViewId(null); setL1Graph(null);
    setL2Graph(null); setL2Result(null); setL2ViewMode(null); setSqlText(''); setCurrentScriptName('');
    setError(null); setActiveL1Table(null); setSelectedEdge(null); setSqlHighlightLine(null);
    setResolutionStats(null); setOrphanFieldSamples(null);
    setSchemaCandidates(null); setSchemaEvidence(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null); setL2ParseErrors([]);
    setProgress(null); setVersion(0); setResumeLayouts({});
    setShowLog(true);
    setStoryActiveIndex(null); setStoryAutoplay(false);
    setSqlLineNotice(null);
    setStringMatchCursor(null); setStringMatchVisible(true);
    setIndexedAt(null);
    setIsCreator(false);
    setCatchUp(null);
    setStaleHint(false);
    pendingSearchRef.current = null;
  }, [setVersion]);

  // ── One site for "this is the index we serve" ────────────────────────
  // The upload-create path (POST /index response), the open-existing read
  // (GET /index) and the explicit re-index all land here, so the three can
  // never drift apart on which fields they apply. The staleness read is
  // defensive on purpose: P1 owns the payload and may add/move `indexed_at`
  // (today it rides inside the `indexed` status object), so both spellings
  // are accepted and neither is required.
  const applyIndexResult = useCallback((idxResult) => {
    const r = idxResult || {};
    setTableIndex(r.table_index || {});
    setFieldIndex(r.field_index || {});
    setFullTableIndex(r.table_index || {});
    setFullFieldIndex(r.field_index || {});
    setResolutionStats(r.resolution_stats || null);
    setOrphanFieldSamples(r.orphan_field_samples || null);
    setSchemaCandidates(r.schema_candidates_summary || null);
    setSchemaEvidence(r.schema_evidence || null);
    const at = r.freshness?.indexed_at ?? r.index_change?.indexed_at
      ?? r.indexed_at ?? r.indexed?.indexed_at ?? null;
    setIndexedAt(typeof at === 'string' && at ? at : null);
    // P4 (2026-08-31): `indexed` is what mounts the search panel, so it is a
    // CLAIM ABOUT THE PAYLOAD, not a marker that "an index response arrived".
    // A corrupt/missing index cache reads as {} server-side; blindly flipping
    // the flag here would open search on a guaranteed no_matches. Real = the
    // payload carries a non-empty table_index, or an `indexed` status that
    // itself says indexed.
    setIndexed(hasServedIndex(r));
  }, []);

  // ── Upload (create) & Analyze ─────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    resetWorkspaceState();
    setLoading(true);
    try {
      // R31/A-M6: upload CREATES a new workspace (server UUID4 ws_id,
      // stamped creator, added to "my workspaces"). The previous workspace
      // is NOT deleted — the user manages their list on the dashboard
      // (remove-from-my-history is role-dependent, A-M2).
      const result = await api.uploadWorkspace(file);
      setWsId(result.workspace_id);
      setFileTree(result.file_tree);

      // Auto-select all SQL files
      const scripts = collectSqlFiles(result.file_tree);
      setSelectedScripts(scripts);

      // Auto-index (fire-and-forget with polling)
      setProgress({ current: 0, total: scripts.length, phase: 'analyzing' });
      const idxResult = await api.indexWorkspace(result.workspace_id, scripts);
      applyIndexResult(idxResult);
      setProgress(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [resetWorkspaceState, applyIndexResult]);

  // ── R31: open an existing workspace (dashboard Open / shared ?ws= link) ──
  // resume → GET /tree → GET /index. state_version + saved layouts come from
  // resume so the CAS save and saved-position re-application start from the
  // shared state.
  //
  // P2 fast-open (v3.3.194): BOTH roles now take the SAME read-only path —
  // the creator's automatic POST /scan + POST /index on open is GONE. That
  // was a full re-parse of every script on every open (the log panel scrolled
  // parse/profile for minutes on a 100-script workspace) for state the
  // backend already persists (G3 GET /tree + GET /index, since v3.3.192).
  // There is no manual re-index control anywhere (user ruling 2026-08-31):
  // changed scripts are caught up automatically in the background (the
  // catch-up branch below), so a plain open is silent — no parse/profile
  // lines, no spinner, no 403 risk.
  //
  // The remaining build paths are the two "nothing to read" cases, and only
  // the creator may run them (both writes are creator-only, #272/#380):
  //  - no stored tree (GET /tree 409s) = never indexed — a fresh upload keeps
  //    working end-to-end; a participant gets the reason instead of a raw 403;
  //  - a stored tree whose index caches are gone (GET /index says
  //    indexed:false with empty indexes).
  const handleOpenExisting = useCallback(async (targetWsId) => {
    resetWorkspaceState();
    setLoading(true);
    try {
      const resume = await api.resumeWorkspace(targetWsId);
      setVersion(resume.state_version || 0);
      setResumeLayouts(resume.layouts || {});
      setWsId(targetWsId);
      const creator = !!username && resume.creator_username === username;
      setIsCreator(creator);

      let tree = await api.getWorkspaceTree(targetWsId);
      let idxResult = null;
      if (!tree) {
        if (!creator) {
          throw new Error(
            'This workspace has no file index yet - its creator must open it once to build one.');
        }
        // Never-indexed: build it once, honestly labelled (a real scan +
        // index IS running — this is the only spinner the open path shows).
        tree = await api.scanWorkspace(targetWsId);
        const scripts = collectSqlFiles(tree);
        setProgress({ current: 0, total: scripts.length, phase: 'analyzing' });
        idxResult = await api.indexWorkspace(targetWsId, scripts);
      }
      setFileTree(tree);
      setSelectedScripts(collectSqlFiles(tree));

      // ── P1 auto-trigger (c): a STALE index must never serve search ────
      // If the served index is stale (scripts changed, or the extractor
      // version moved on) the incremental rebuild has NOT run yet — there is
      // no catching_up flag to wait for, so waiting would open search straight
      // onto the stale index (the false-no_matches window). The creator fires
      // POST /index NOW and holds search until it lands; the in-flight call
      // flips the backend's catching_up state, whose 409 gate protects every
      // other reader. A participant cannot write (#272/#380): informational
      // hint, no block. Staleness is read from /resume's index_change first,
      // then from the served index's own freshness object.
      const needsRebuild = (f) => f.present && (f.stale || (f.changed ?? 0) > 0);
      const rebuild = async (info, scripts) => {
        setCatchUp({ changed: info.changed, canFix: true });
        setProgress({ current: 0, total: info.changed ?? scripts.length, phase: 'catching up' });
        try {
          const built = await api.indexWorkspace(targetWsId, scripts);
          applyIndexResult(built);
          setStaleHint(false);
          setCatchUp(null);
          setProgress(null);
          return built;
        } catch (reindexError) {
          // Never leave the workspace unusable because a refresh failed:
          // serve the (still stale) index and say why. If the backend IS
          // still rebuilding, the read below re-arms the hold.
          setError(`Index refresh failed - showing the previous index. ${reindexError.message}`);
          setCatchUp(null);
          setProgress(null);
          return null;
        }
      };

      let autoTriggered = false;
      const fromResume = readFreshness(resume.index_change);
      if (needsRebuild(fromResume)) {
        if (creator) {
          idxResult = await rebuild(fromResume, collectSqlFiles(tree));
          autoTriggered = true;
        } else {
          setStaleHint(true);
        }
      }

      if (!idxResult) {
        idxResult = await api.getWorkspaceIndex(targetWsId);
        // A tree without an index means the index caches were wiped while the
        // tree file survived (or an index was cancelled): for a creator that
        // is the same never-indexed case as a missing tree — build once
        // rather than open an empty debugger. A participant still sees the
        // empty index (they cannot write).
        const status = idxResult?.indexed;
        const indexedNow = !status || (typeof status === 'boolean'
          ? status
          : status.indexed !== false);
        if (!indexedNow && creator
          && Object.keys(idxResult?.table_index || {}).length === 0) {
          const scripts = collectSqlFiles(tree);
          setProgress({ current: 0, total: scripts.length, phase: 'analyzing' });
          idxResult = await api.indexWorkspace(targetWsId, scripts);
          autoTriggered = true;
        }
        // The same trigger, detected on the index payload itself (a /resume
        // without index_change, or freshness only GET /index carries) — but
        // NEVER while a rebuild is already in flight: that one is doing the
        // work, and a second POST would just queue another full pass.
        if (!autoTriggered && !readCatchUp(idxResult).catchingUp) {
          const served = readFreshness(idxResult);
          if (needsRebuild(served)) {
            if (creator) {
              const rebuilt = await rebuild(served, collectSqlFiles(tree));
              if (rebuilt) idxResult = rebuilt;
              autoTriggered = true;
            } else {
              setStaleHint(true);
            }
          }
        }
      }
      applyIndexResult(idxResult);
      setProgress(null);
      // ── P1 catching-up window ────────────────────────────────────────
      // The served index may report a rebuild IN FLIGHT (this user's auto
      // trigger, another reader's, or a participant who opened mid-pass):
      // until it lands the index is missing the fresh content, so search
      // could answer a FALSE no_matches. Withhold search behind the honest
      // bar and explain the wait. No flag → no bar, no hold.
      const cue = readCatchUp(idxResult);
      if (cue.catchingUp) {
        setCatchUp({ changed: cue.changed, canFix: creator });
        setProgress({ current: 0, total: cue.changed ?? 0, phase: 'catching up' });
      }
      // #292: populate the persisted view tree (search views + their L2
      // children) from views.json so the left-panel ViewBar shows them.
      // R23 clean start: NO auto-activation — the user clicks a view to load
      // it. A view-list failure is non-critical (the tree just starts empty).
      try {
        const viewsRes = await api.listViews(targetWsId);
        setViews(Array.isArray(viewsRes?.views) ? viewsRes.views : []);
      } catch (e) { /* non-critical — views populate on the next search */ }
    } catch (e) {
      // Open failed (e.g. deleted/unknown id) — surface it and stay on the
      // empty debugger; the dashboard is one "Close" away.
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [resetWorkspaceState, setVersion, username, applyIndexResult]);

  // ── P1 catching-up poller: hand search back only when the index is whole ──
  // While an incremental re-index runs, GET /index is re-read until the
  // payload stops reporting `catching_up` — and, for a user who can rebuild,
  // until `freshness.stale` has flipped too (their own POST is what flips
  // it). On completion the served index is applied through the SAME path the
  // build path uses — one refresh site — and search is handed back. A
  // participant who is still stale once nothing is in flight gets the hint
  // instead of a lockout (they cannot rebuild).
  //
  // P4 (2026-08-31) — the poller must never be an infinite hold. Three ways
  // out besides the clean one, all honest:
  //   • the workspace GONE mid-hold (deleted in another tab → 404) — no poll
  //     brings it back: reset to the no-workspace state and say so;
  //   • the session EXPIRED (401) — the shared 401 interceptor (E-M1) is
  //     already handing the shell to login: exit the hold quietly;
  //   • a TRANSIENT failure (dropped connection, 5xx) — retried, but BOUNDED
  //     (CATCHUP_POLL_TICKS ticks ≈ 30s), then the hold exits on the previous
  //     index with the failed-refresh message. Waiting forever would withhold
  //     search for good and surface nothing.
  // And the stale-stays-true hole: if nothing is in flight any more but the
  // index STILL reads stale, a further file landed on disk DURING the window
  // — the run that was being waited for is over, so waiting longer waits for
  // nothing. The (idempotent, cheap: 0.5s on a zero diff) incremental
  // rebuild is re-fired ONCE per open; if it is stale again after that, the
  // hold exits with "re-open to catch up fully" and search back ON, instead
  // of polling until the tab closes.
  const catchUpRef = useRef(null);
  catchUpRef.current = catchUp;
  // A search that hit the catching-up 409 gate, replayed when the hold clears.
  const pendingSearchRef = useRef(null);
  // The re-fire is capped at ONE per OPEN, not per hold — a ref, so a re-render
  // (or a second hold armed inside the same visit) cannot reset the cap.
  const catchUpRefireRef = useRef(false);
  useEffect(() => {
    if (!wsId || !catchUp) return undefined;
    let alive = true;
    let failures = 0;      // consecutive transient poll failures
    let lastStale = false; // staleness as of the last read that succeeded
    let refire = catchUpRefireRef.current;
    const timer = setInterval(async () => {
      // ── terminal exits ────────────────────────────────────────────
      const exitGone = () => {
        stop();
        // Reset to the no-workspace state, with the reason ON SCREEN: this was
        // nobody's action in THIS tab, so it has to say what happened. The
        // shell is deliberately NOT asked to unmount the app (onClose) — the
        // message would die with the component. The open guard is cleared
        // instead, so the same id can be re-opened from the list (it will
        // simply report the same 404 through the open path).
        openedRef.current = null;
        resetWorkspaceState();
        setError('This workspace is no longer available — it was deleted while it was open.');
      };
      const exitUnauthorized = () => {
        // The interceptor already fired the shell's session-expired handler
        // (the login form is taking over) — no banner on top of it.
        stop();
        setCatchUp(null);
        setProgress(null);
      };
      const exitOnPreviousIndex = (message) => {
        stop();
        setError(message);
        setStaleHint(lastStale);
        setCatchUp(null);
        setProgress(null);
      };
      const stop = () => { alive = false; clearInterval(timer); };

      // ── the ONE re-fire (P4: stale with nothing in flight) ─────────
      const refireIndex = async () => {
        setProgress({ current: 0, total: catchUp.changed ?? 0, phase: 'catching up' });
        try {
          const built = await api.indexWorkspace(wsId, openScriptsRef.current || []);
          if (!alive) return;
          const after = readFreshness(built);
          applyIndexResult(built);
          if (readCatchUp(built).catchingUp || after.stale) {
            // One re-fire per open — no loop: the honest exit says what a
            // re-open would finish, and search is handed back.
            exitOnPreviousIndex(
              'Changes remain after the refresh — re-open this workspace to catch up fully.');
            return;
          }
          setStaleHint(false);
          setCatchUp(null);
          setProgress(null);
        } catch (e) {
          if (!alive) return;
          const kind = classifyIndexPollError(e);
          if (kind === POLL_GONE) { exitGone(); return; }
          if (kind === POLL_UNAUTHORIZED) { exitUnauthorized(); return; }
          exitOnPreviousIndex(
            `Index refresh failed - showing the previous index. ${e.message}`);
        }
      };

      let idx;
      try {
        idx = await api.getWorkspaceIndex(wsId);
      } catch (e) {
        if (!alive) return;
        const kind = classifyIndexPollError(e);
        if (kind === POLL_GONE) { exitGone(); return; }
        if (kind === POLL_UNAUTHORIZED) { exitUnauthorized(); return; }
        failures += 1;
        if (failures > CATCHUP_POLL_TICKS) {
          exitOnPreviousIndex(
            `Index refresh did not complete - showing the previous index. ${e.message}`);
        }
        return; // transient — retry on the next tick
      }
      if (!alive) return;
      const cue = readCatchUp(idx);
      const now = readFreshness(idx);
      failures = 0;
      lastStale = now.present && now.stale;
      if (cue.catchingUp || (catchUp.canFix && now.stale)) { // still catching up
        if (!cue.catchingUp && !refire) { // stale with NOTHING in flight
          refire = true;
          catchUpRefireRef.current = true;
          refireIndex();
        }
        return;
      }
      applyIndexResult(idx);
      setStaleHint(!catchUp.canFix && now.stale);
      setCatchUp(null);
      setProgress(null);
    }, CATCHUP_POLL_INTERVAL);
    return () => { alive = false; clearInterval(timer); };
  }, [wsId, catchUp, applyIndexResult, resetWorkspaceState]);

  // ── R31: open-existing entry — runs once when the workspace id arrives
  //     (dashboard Open or a shared ?ws= link). Guarded by openedRef so it
  //     never re-runs on unrelated re-renders.
  useEffect(() => {
    if (openWorkspaceId && openedRef.current !== openWorkspaceId) {
      openedRef.current = openWorkspaceId;
      handleOpenExisting(openWorkspaceId);
    }
  }, [openWorkspaceId, handleOpenExisting]);

  // ── Poll indexing progress ───────────────────────────────────────
  const progressTimerRef = useRef(null);
  useEffect(() => {
    if (!wsId || !progress) return;
    progressTimerRef.current = setInterval(async () => {
      try {
        const status = await api.getWorkspaceStatus(wsId);
        if (status.progress) {
          setProgress(status.progress);
          if (status.progress.phase === 'done') {
            clearInterval(progressTimerRef.current);
            // P1 catching-up: the incremental re-index can report 'done'
            // before the GET /index poller above confirms it — THAT poller
            // clears the bar (and refreshes the index), so search is never
            // handed back against a half-written index.
            if (!catchUpRef.current) setTimeout(() => setProgress(null), 1500);
          }
        }
      } catch (e) { /* ignore poll errors */ }
    }, 3000);
    return () => clearInterval(progressTimerRef.current);
  }, [wsId, progress?.phase]);

  // ── R23: clean start on load — never auto-restore a workspace/view.
  // The R3 mount-time restore was removed; this one-time purge drops its
  // localStorage key so saved state from older sessions can't resurface.
  useEffect(() => {
    try { localStorage.removeItem('df_last_search_view'); } catch { /* ignore */ }
  }, []);

  // ── Search ────────────────────────────────────────────────────────
  const handleSearch = useCallback(async (table, field, direction) => {
    if (!wsId) return;
    setL1Graph(null); setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setLoading(true); setError(null);
    try {
      const result = await api.searchDataFlow(wsId, table, field, direction);
      const newView = {
        view_id: result.view_id,
        type: 'search',
        table, field,
        script_ids: result.script_ids,
        l1_graph_cache: result.l1_graph,
        children: [],
        created_at: new Date().toISOString(),
        match_mode: result.match_mode,
        message: result.message,
        // R29: the view tree keeps its direction so L2 follows it automatically
        direction,
      };
      setViews(prev => [...prev, newView]);
      setActiveViewId(result.view_id);
      parentViewIdRef.current = result.view_id;
      setL1Graph(result.l1_graph);
      setGraphLevel('L1');
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
      setSqlText('');
      setActiveL1Table(null);
      setSelectedEdge(null); setSqlHighlightLine(null);
    } catch (e) {
      // MSC-1: a search can get TWO different 409s and only one of them is a
      // reason to wait. P1's index-catch-up gate ("Index is being updated for
      // this workspace — retry in a moment") means the scope is mid-rebuild:
      // hold search behind the honest bar and replay THIS search once the
      // index is whole (never surface it). The R31 heavy gate ("system busy —
      // please wait") means another user's heavy op holds the SERVER: no
      // /index poll will ever clear it, a hold would lock search up for
      // nothing, and a silent replay would spin until the server frees. That
      // one is surfaced as the transient condition it is — the user retries.
      if (isIndexCatchUp409(e)) {
        pendingSearchRef.current = { table, field, direction };
        setCatchUp({ changed: null, canFix: false });
        setProgress({ current: 0, total: 0, phase: 'catching up' });
        setLoading(false);
        return;
      }
      if (e?.status === 409) {
        setError(BUSY_409_MESSAGE);
        return;
      }
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  // A search that hit the catching-up gate is replayed once the hold clears —
  // exactly once, and only while the same workspace is still open.
  useEffect(() => {
    const pending = pendingSearchRef.current;
    if (catchUp || !pending) return;
    pendingSearchRef.current = null;
    if (!wsId) return;
    handleSearch(pending.table, pending.field, pending.direction);
  }, [catchUp, wsId, handleSearch]);

  // ── Open L2 (double-click on L1 script node) ──────────────────────
  const handleOpenL2 = useCallback(async (scriptId, scriptName) => {
    if (!wsId || !activeViewId) return;
    setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setLoading(true);
    try {
      // R3 finding 1: `parentViewIdRef` is the fast path, but it is nulled by
      // every tree navigation to an L2 child — an entry opened from the
      // not-in-flow strip while that child is active used to fall through to
      // the CHILD id, so POST .../children addressed a script row as a parent
      // (404, swallowed) and the new child view was orphaned. Resolve the
      // search view from the tree instead: a child row names its parent, a
      // top-level row is its own parent.
      const viewIdForApi = parentViewIdRef.current
        || (activeView ? (activeView.parent_view_id || activeView.view_id) : activeViewId);
      // R29: L2 is the zoom-in of L1 — fetch in the parent view's direction
      const searchView = views.find(v => v.view_id === viewIdForApi);
      const result = await api.getLevel2Graph(wsId, viewIdForApi, scriptName, true, /* R38: persisted direction ignored */ direction);
      applyL2Result(result);
      setSqlText(result.sql_text || '');
      setCurrentScriptName(scriptName);
      setGraphLevel('L2');

      // Add child entry to view tree AND persist to backend
      const childId = `${viewIdForApi}_${scriptId}`;
      const childEntry = {
        view_id: childId,
        type: 'script',
        parent_view_id: viewIdForApi,
        script_id: scriptId,
        script_name: scriptName,
        created_at: new Date().toISOString(),
      };
      setViews(prev => prev.map(v => {
        if (v.view_id === viewIdForApi) {
          if (v.children?.some(c => c.view_id === childId)) return v;
          return {
            ...v,
            children: [...(v.children || []), childEntry],
          };
        }
        return v;
      }));
      // Persist child to backend so it survives refresh and API lookups
      try {
        await api.addViewChild(wsId, viewIdForApi, childEntry);
      } catch (e) { /* non-critical: child exists in React state */ }
      setActiveViewId(childId);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId, activeViewId, views]);

  // ── #400: the no-flow dead end ────────────────────────────────────
  // A `no_flow` search DOES match scripts (`view.script_ids`) but its L1
  // graph is EMPTY — no script node to double-click — so the matched
  // script's L2 was reachable only by hand-crafting the child view through
  // the API. The banner therefore carries one "Open <script> full graph"
  // affordance per matched script, calling the SAME path the L1
  // double-click uses (`handleOpenL2` → GET /level2 → POST .../children):
  // same fetch, same state updates, same child-view dedup. `no_matches`
  // always persists `script_ids: []`, so only a no-flow view renders
  // buttons — an in-flow search has no banner at all.
  const noFlowScripts = useMemo(() => {
    if (!activeView) return [];
    if (activeView.match_mode !== 'no_flow' && activeView.match_mode !== 'no_matches') return [];
    return Array.isArray(activeView.script_ids)
      ? activeView.script_ids.filter(Boolean)
      : [];
  }, [activeView]);

  // `script_ids` are workspace rel_paths — exactly what GET /level2's
  // `script=` resolves (shared `resolve_script`), so the rel_path stands in
  // for the L1 script node's cached-analysis id as the child-view id suffix.
  const handleOpenNoFlowScript = useCallback((scriptName) => {
    return handleOpenL2(scriptName, scriptName);
  }, [handleOpenL2]);

  // ── V2-N4 (2026-08-29): matched-but-not-in-flow scripts on an L1 view ──
  // `matched != in flow`: an exact-match search's `script_ids` are the scripts
  // that QUERY the searched field, while the L1 graph renders only the
  // directional flow's script nodes — P2.P_DT matched 4 scripts and its L1
  // rendered 2, with no UI path to the other two (the no_flow banner's
  // "Open … full graph" affordance is a no_flow-only render). The strip below
  // names those scripts and reuses the SAME affordance + open path.
  const l1SearchView = useMemo(() => {
    if (!activeView) return null;
    if (activeView.type === 'search') return activeView;
    // An L2 child is the active view while its parent L1 stays on screen —
    // the strip describes the parent search view's L1.
    const parent = views.find(v => v.view_id === activeView.parent_view_id);
    return parent && parent.type === 'search' ? parent : null;
  }, [activeView, views]);

  // R3 finding 1 (3a): the strip diffs against the PARENT SEARCH VIEW's own
  // graph — `l1_graph_cache` is the exact L1 that view rendered — never the
  // global `l1Graph`, which belongs to WHATEVER view was rendered last (while
  // an L2 child is active the left-panel L1 stays mounted, but `l1Graph` can
  // hold another search's graph after navigating the tree). Rows carry the
  // cache; the live graph is only the fallback for a row without one.
  const l1SearchGraph = useMemo(
    () => (l1SearchView && l1SearchView.l1_graph_cache) || l1Graph,
    [l1SearchView, l1Graph],
  );

  const inFlowScriptNames = useMemo(() => {
    const names = new Set();
    if (l1SearchGraph && Array.isArray(l1SearchGraph.nodes)) {
      for (const n of l1SearchGraph.nodes) {
        const d = (n && n.data) || n || {};
        if (d.type !== 'script_node') continue;
        const nm = d.script_name || d.label;
        if (nm) names.add(nm);
      }
    }
    return names;
  }, [l1SearchGraph]);

  const outOfFlowScripts = useMemo(() => {
    // no_flow / no_matches own the #400 banner above — never this strip.
    if (!l1SearchView || !l1SearchGraph) return [];
    if (l1SearchView.match_mode === 'no_flow' || l1SearchView.match_mode === 'no_matches') return [];
    const ids = Array.isArray(l1SearchView.script_ids)
      ? l1SearchView.script_ids.filter(Boolean)
      : [];
    if (ids.length === 0 || inFlowScriptNames.size === 0) return [];
    // script_ids are workspace rel_paths and an L1 script node carries the
    // same rel_path in `script_name` — one exact string comparison, no
    // basename fallback (R3 finding 3b: a basename hit can only HIDE a script
    // that really is missing from the rendered flow).
    return ids.filter(s => !inFlowScriptNames.has(s));
  }, [l1SearchView, l1SearchGraph, inFlowScriptNames]);

  // ── View Tree navigation ──────────────────────────────────────────
  const handleViewTreeClick = useCallback(async (viewId) => {
    setActiveViewId(viewId);
    setError(null);

    // Find the entry
    let entry = views.find(v => v.view_id === viewId);
    let isL2 = false;
    if (!entry) {
      for (const v of views) {
        const child = (v.children || []).find(c => c.view_id === viewId);
        if (child) { entry = child; isL2 = true; break; }
      }
    }

    if (!entry) return;

    // Search recovery: whichever view was opened, surface its searched
    // table.field back into the search panel (L2 rows resolve through their
    // parent search row). No-op when the tree carries no target — the panel
    // is never cleared or guessed at.
    const rec = recoverViewSearch(views, viewId);
    if (rec) {
      recoverNonceRef.current += 1;
      setSearchRecover({ ...rec, nonce: recoverNonceRef.current });
    }

    if (isL2 && entry.type === 'script') {
      // Navigate to L2 — the L2 fetch is driven by entry.parent_view_id,
      // so a stale parentViewIdRef (left pointing at the last-searched
      // view) must not survive into a later L1 double-click (CR6).
      parentViewIdRef.current = null;
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
      try {
        const parentView = views.find(v => v.view_id === entry.parent_view_id);
        const result = await api.getLevel2Graph(wsId, entry.parent_view_id, entry.script_name, true, /* R38: persisted direction ignored */ direction);
        applyL2Result(result);
        setSqlText(result.sql_text || '');
        setCurrentScriptName(entry.script_name);
        setGraphLevel('L2');
        setShowLog(true);
        setActiveL1Table(null);
      } catch (e) {
        setError(e.message);
      }
    } else {
      // Navigate to L1 — this view becomes the context for a subsequent
      // L2 open (double-click): keep parentViewIdRef in sync so handleOpenL2
      // resolves the right parent view + direction (CR6).
      parentViewIdRef.current = viewId;
      setL1Graph(entry.l1_graph_cache || { nodes: [], edges: [] });
      setGraphLevel('L1');
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
      setL2NotInFlow(false); setL2NotInFlowMessage(null);
      setL2ParseErrors([]);
      setSqlText('');
      setActiveL1Table(null);
      setSelectedEdge(null); setSqlHighlightLine(null);
    }
  }, [views, wsId]);

  // ── Remove from my history (R31 A-M1/A-M2) ────────────────────────
  // ONE role-dependent action — the backend decides: creator → physical
  // delete (server-global audit log written before removal), participant →
  // link removal only. The role-aware warning lives in the MyWorkspaces
  // panel; this in-app control shows a generic warning and returns to the
  // dashboard (the workspace is out of this user's list either way).
  const handleDeleteWorkspace = useCallback(async () => {
    if (!wsId) return;
    if (!window.confirm(
      'Remove this workspace from your history? If you created it, this DELETES the workspace and its files for everyone.'
    )) return;
    try {
      await api.removeFromMyHistory(wsId);
    } catch (e) {
      setError(e.message);
      return;
    }
    resetWorkspaceState();
    onCloseWorkspace?.();
  }, [wsId, resetWorkspaceState, onCloseWorkspace]);

  // ── T8 (#295): embedded "My workspaces" section (left panel) ──────
  // Upload creates a NEW workspace server-side, then opens it — the open
  // effect (handleOpenExisting) reads the persisted tree + index once on
  // remount (the upload itself already built the index). We deliberately do
  // NOT call handleUpload's inline index path here (it would double-index
  // after the keyed remount).
  const handleSectionUpload = useCallback(async (file) => {
    const result = await api.uploadWorkspace(file);
    onOpenWorkspace?.(result.workspace_id);
    return result;
  }, [onOpenWorkspace]);

  // Remove-from-history (role-dependent, the backend decides: creator →
  // physical delete, participant → link removal). If it was the OPEN
  // workspace, drop back to the empty debugger.
  const handleSectionRemove = useCallback(async (w) => {
    try {
      await api.removeFromMyHistory(w.ws_id);
      if (w.ws_id === wsId) {
        resetWorkspaceState();
        onCloseWorkspace?.();
      }
    } catch (e) {
      setError(e.message);
      throw e; // let the embedded list surface the error line
    }
  }, [wsId, resetWorkspaceState, onCloseWorkspace]);

  // ── L1 Table lens click ─────────────────────────────────────────
  const handleTableClick = useCallback((tableName) => {
    setActiveL1Table(prev => prev === tableName ? null : tableName);
  }, []);

  const handleClearTableFilter = useCallback(() => {
    setActiveL1Table(null);
  }, []);

  // ── Edge click → SQL highlight (R25/§8.8) ──────────────────────────
  // The per-edge payload (highlight_line / flow_kind / reason) is the
  // single source of truth: the SQL panel lights exactly the anchor line.
  // The old response-level `highlights` and per-edge `sql_range` /
  // `sql_ranges` fields are gone from the API — nothing to pick from.
  const handleEdgeClick = useCallback((edgeData) => {
    // A7 focus exclusivity: a manual edge click while the story plays
    // EXITS the story — one focus mode at a time, and the R37
    // last-click-wins channel stops fighting the autoplay ticker.
    setStoryActiveIndex(null);
    setStoryAutoplay(false);
    setSelectedEdge(edgeData);
    const ln = edgeData && edgeData.highlight_line;
    if (Number.isInteger(ln) && ln >= 1) {
      setSqlHighlightLine(ln);
      setSqlLineNotice(null);
    } else {
      // F-B2 (S4 finding 6): line 0/absent used to clear the previous
      // highlight and light nothing — silent. Say so instead (the notice
      // clears itself on the next valid click).
      setSqlHighlightLine(null);
      setSqlLineNotice('this element has no SQL line');
    }
  }, []);

  // R37: L2 node click → scroll the SQL panel to the node's definition
  // line. Line semantics = server contract: ⟐ output VT → its own creation
  // line (top-level: the statement's own first token — never the WITH line
  // that merely names the CTE; nested subquery/EXISTS VT: the body's first
  // output line), physical table → first occurrence (R22 keeper), alias/
  // CTE → its FROM/JOIN line. Guards: integer ≥ 1 else the no-SQL-line
  // notice (TVF alias `f` anchors L0 until M-T1 — never guess); first line
  // only (single-line-highlight convention, v3.3.145); the tapped element's
  // OWN payload is read, never a label lookup (merged nodes keep their own
  // line_start). Node click clears a stale edge selection so a mismatched
  // edge can't stay highlighted beside a node's line.
  const handleNodeClick = useCallback((nodeData) => {
    // A7: symmetric with edge clicks — see handleEdgeClick.
    setStoryActiveIndex(null);
    setStoryAutoplay(false);
    setSelectedEdge(null);
    const ln = nodeData && nodeData.line_start;
    if (Number.isInteger(ln) && ln >= 1) {
      setSqlHighlightLine(ln);
      setSqlLineNotice(null);
    } else {
      setSqlHighlightLine(null);
      setSqlLineNotice('this element has no SQL line');
    }
  }, []);

  const clearEdgeSelection = useCallback(() => {
    setSelectedEdge(null);
    setSqlHighlightLine(null);
    setSqlLineNotice(null);
  }, []);

  // ── Clear edge selection ────────────────────────────────────────────
  // ── Delete view ───────────────────────────────────────────────────
  // E-M7 (#282): deleting the ACTIVE L2 child view (or its parent) must drop
  // the graph back to L1 — no stale L2 graph/header/SQL/toggle with no live
  // view. `clearL1` also clears the L1 nav (used when the deleted view WAS
  // the active L1 view); when only an L2 child is gone, the L1 nav stays.
  const dropToL1 = useCallback(({ clearL1 = false } = {}) => {
    if (clearL1) setL1Graph(null);
    setGraphLevel('L1');
    setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setSqlText(''); setCurrentScriptName('');
    setSelectedEdge(null); setSqlHighlightLine(null);
    setSqlLineNotice(null);
    setActiveViewId(null);
  }, []);

  const handleDeleteView = useCallback(async (viewId) => {
    if (!wsId) return;
    try { await api.deleteView(wsId, viewId); } catch (e) { /* ignore */ }
    // The ref must not keep pointing at a deleted view — handleOpenL2
    // prefers it over activeViewId, so a stale ref would address the API
    // with a dead view id (wrong parent chain / back navigation).
    if (parentViewIdRef.current === viewId) parentViewIdRef.current = null;
    // E-M7: capture what the ACTIVE view was BEFORE the setViews below —
    //   activeViewId === viewId            → the active view was deleted;
    //   activeViewId is a child of viewId  → the active L2's PARENT was
    //   deleted. Either way the active view no longer exists → drop to L1.
    const activeWasDeleted =
      activeViewId === viewId
      || (activeViewId && views.some(v =>
        v.view_id === viewId && (v.children || []).some(c => c.view_id === activeViewId)
      ));
    const activeViewIsAChild = activeViewId === viewId && views.some(v =>
      (v.children || []).some(c => c.view_id === viewId)
    );
    setViews(prev => {
      let newViews = prev.filter(v => v.view_id !== viewId);
      newViews = newViews.map(v => ({
        ...v,
        children: (v.children || []).filter(c => c.view_id !== viewId),
      }));
      return newViews;
    });
    if (activeWasDeleted) {
      // A deleted L2 child (or its deleted parent) → drop back to L1 and
      // keep the L1 nav; a deleted active L1 view → clear the L1 nav too.
      dropToL1({ clearL1: !activeViewIsAChild });
    }
  }, [wsId, activeViewId, views, dropToL1]);

  // Top panel always shows L1 as navigation graph (per requirement §3)
  const graphData = l1Graph;

  // ── #331: 4-way L2 view toggle ─────────────────────────────────────
  // Each pair — detailed ('flow'/'full') and merged ('flow-merged'/
  // 'full-merged') — renders from ONE payload and toggles visibility
  // client-side, so the flow-only member's node positions stay
  // byte-identical to its full member (requirement: flow-only(merged) ↔
  // full(merged) must not re-layout). The detailed pair uses full_graph
  // (every edge); the merged pair uses full_merged (one SQL line ≈ one
  // edge), a node SUPERSET of the flow closure — the flow-only member hides
  // the non-closure elements client-side (flowNodeIds + flow-merged edge
  // ids) rather than swapping to the smaller flow_only_merged payload.
  const isL2Merged = l2ViewMode === 'flow-merged' || l2ViewMode === 'full-merged';
  const l2GraphData = useMemo(() => {
    const full = (l2Result && l2Result.full_graph) || l2Graph;
    if (!l2Result) return l2Graph;
    if (isL2Merged) {
      const merged = l2Result.full_merged;
      // Defensive: only render a merged view when it actually carries nodes
      // (an empty/absent merged payload falls back to the full graph).
      if (merged && Array.isArray(merged.nodes) && merged.nodes.length > 0) {
        // R32 self-loop captions: re-derive, from payloads already in hand,
        // which merged self-loops are absorbed FILTER field edges and name
        // them (`⟂ p_dt (filtered @L190)`). Pure client-side projection —
        // the payload returned by the API is untouched; only THIS memo's
        // result is a shallow copy whose `edges` array carries an extra
        // `filterLabel` on matching self-loops (the styling rule
        // FILTER_SELFLOOP_STYLES renders it — graphStyles.js). Untouched
        // edges keep their object references, so nothing else can drift.
        const captions = selfLoopFilterLabels(
          merged.nodes,
          (l2Result.graph && l2Result.graph.edges) || [],
        );
        if (captions.size === 0) return merged;
        return {
          ...merged,
          edges: (merged.edges || []).map(ed => {
            const d = ed && ed.data;
            // Only self-loops can be promoted field edges; anything else
            // (and any edge with no caption for its line) passes through.
            if (!d || d.source !== d.target) return ed;
            const names = captions.get(`${d.highlight_line}|${d.source}`);
            if (!names) return ed;
            return {
              ...ed,
              data: { ...d, filterLabel: `⟂ ${names} (filtered @L${d.highlight_line})` },
            };
          }),
        };
      }
    }
    return full;
  }, [l2Result, isL2Merged, l2Graph]);

  // The flow-only members filter by edge id; the id set differs per pair —
  // unmerged (flow_edge_ids) for 'flow', line-merged for 'flow-merged'.
  const flowEdgeIds = useMemo(() => {
    if (isL2Merged) {
      return (l2Result?.flow_only_merged?.edges || [])
        .map(e => e?.data?.id).filter(Boolean);
    }
    return l2Result?.flow_edge_ids;
  }, [isL2Merged, l2Result]);

  // ── Field Story (step-through bar) ────────────────────────────────
  // Target resolution mirrors the breadcrumb: an L2 child row carries no
  // table/field of its own — its PARENT search row does. No target (or a
  // row without both halves) → no story, never a guess.
  const storyTarget = useMemo(() => {
    if (!activeView) return null;
    const parentView = activeView.parent_view_id
      ? views.find(v => v.view_id === activeView.parent_view_id)
      : null;
    const displayView = parentView || activeView;
    if (!displayView.table || !displayView.field) return null;
    return { table: displayView.table, field: displayView.field };
  }, [activeView, views]);

  // Steps come from the builder (utils/fieldStory) over the detailed L2
  // closure. Null whenever an input is missing, the builder throws, or it
  // returns no steps array — the bar renders only when steps exist.
  const fieldStory = useMemo(() => {
    if (!l2Result || !storyTarget) return null;
    try {
      const story = buildFieldStory({
        graph: l2Result.graph,
        fullGraph: l2Result.full_graph,
        // A1: the merged payload whose l2m_* ids the default view renders.
        mergedGraph: l2Result.full_merged,
        table: storyTarget.table,
        field: storyTarget.field,
      });
      return story && Array.isArray(story.steps) ? story : null;
    } catch { /* no story rather than a broken debugger */ return null; }
  }, [l2Result, storyTarget]);

  // The L2 graph's focus: the active step's edge/node ids. null covers
  // inactive (storyActiveIndex === null), L1, and out-of-range indices.
  const storyFocus = useMemo(() => {
    if (graphLevel !== 'L2' || storyActiveIndex == null || !fieldStory) return null;
    const step = fieldStory.steps[storyActiveIndex];
    if (!step) return null;
    // A6: merged and detailed views render DISJOINT edge-id namespaces —
    // pick the list that exists in the view actually on screen, and
    // re-derive on every view flip (deps include isL2Merged/l2Result).
    const edgeIds = (isL2Merged
      ? (step.mergedEdgeIds || [])
      : (step.edgeIds || []));
    // A5: never dim the story's anchor — the seed chip, its owning table
    // box, and that box's chips (the visible anchor in merged views,
    // where the chip itself is hidden when edge-less).
    const exempt = new Set();
    const nodes = (l2Result && l2Result.graph && l2Result.graph.nodes) || [];
    if (fieldStory.seedNodeId) {
      exempt.add(fieldStory.seedNodeId);
      let parentId = null;
      for (const n of nodes) {
        const d = n && n.data ? n.data : n;
        if (d && d.id === fieldStory.seedNodeId) { parentId = d.parent; break; }
      }
      if (parentId) {
        exempt.add(parentId);
        for (const n of nodes) {
          const d = n && n.data ? n.data : n;
          if (d && d.parent === parentId && d.id) exempt.add(d.id);
        }
      }
    }
    return { active: true, edgeIds, nodeIds: step.nodeIds || [], exemptNodeIds: Array.from(exempt) };
  }, [graphLevel, storyActiveIndex, fieldStory, isL2Merged, l2Result]);

  // R11-3: the imperative scroll handle the story path uses below. The panel
  // also scrolls declaratively when `sqlHighlightLine` CHANGES; the explicit
  // call covers the case a value-change effect cannot see.
  const sqlPanelRef = useRef(null);

  // Shared applicator: index + the R37 single SQL-highlight channel —
  // stepping the story scrolls the SQL panel exactly like an edge/node
  // click does (integer ≥ 1 guard, same as every other writer). R3 finding
  // 4: a step whose line IS valid also clears a stale "no SQL line" notice —
  // the notice self-clears on every other valid writer of the channel, and a
  // story step is one of them.
  const applyStoryStep = useCallback((i) => {
    const step = fieldStory && fieldStory.steps[i];
    if (!step) return;
    setStoryActiveIndex(i);
    const ln = step.line;
    if (Number.isInteger(ln) && ln >= 1) {
      setSqlHighlightLine(ln);
      setSqlLineNotice(null);
      // EVERY step click re-centers the line, including a step whose line is
      // already the highlighted one — adjacent steps often share a line
      // (east5 p_dt: birth-41 then written-41), and the panel's declarative
      // scroll is a value-CHANGE effect, so on a repeated line it would
      // no-op and the click would move nothing. Same target either way; the
      // declarative scroll that follows is a no-op re-statement of it.
      sqlPanelRef.current?.scrollToLine(ln);
    } else {
      // Story steps are INV-2 gated (only valid highlight_lines build a
      // step) — this branch is defensive and never sets a notice of its own.
      setSqlHighlightLine(null);
    }
  }, [fieldStory]);

  // Chip click — manual inspection intent: jump AND stop the clock (the
  // autoplay interval advances via onNext/onPrev, which never touch it,
  // so stopping here cannot fight the ticker).
  const handleStoryStep = useCallback((i) => {
    setStoryAutoplay(false);
    applyStoryStep(i);
  }, [applyStoryStep]);

  // ◀ — no-op before the first step (button is disabled there too).
  const handleStoryPrev = useCallback(() => {
    if (storyActiveIndex == null || storyActiveIndex <= 0) return;
    applyStoryStep(storyActiveIndex - 1);
  }, [storyActiveIndex, applyStoryStep]);

  // ▶ — from inactive (null) it STARTS the story at step 0; otherwise it
  // advances, clamped at the last step (autoplay stops there, no wrap).
  const handleStoryNext = useCallback(() => {
    const steps = fieldStory?.steps || [];
    if (!steps.length) return;
    const nextIdx = storyActiveIndex == null ? 0
      : Math.min(steps.length - 1, storyActiveIndex + 1);
    applyStoryStep(nextIdx);
  }, [storyActiveIndex, fieldStory, applyStoryStep]);

  // ✕ — dismiss the focus only: null index clears the graph dimming via
  // storyFocus; the bar itself stays mounted while steps exist.
  const handleStoryDismiss = useCallback(() => {
    setStoryActiveIndex(null);
  }, []);

  const handleStoryToggleAutoplay = useCallback(() => {
    setStoryAutoplay(v => !v);
  }, []);

  // ── R40.13: the naive string-match diff layer ──────────────────────
  // The searched field's canonical name. An L2 child row carries no
  // table/field of its own — its PARENT search row does (same resolution as
  // storyTarget above), and that echoed name is canonical post-R2.11. No
  // target ⇒ no active search ⇒ the layer is hidden (design point 7).
  const stringMatchField = storyTarget ? storyTarget.field : null;

  // The naive matches themselves: a dumb case-insensitive boundary scan of
  // the WHOLE rendered script. Guarded on graphLevel (the SQL panel only
  // mounts in L2), a non-empty canonical field name and non-empty sqlText —
  // any of them unmet ⇒ [] ⇒ no bands.
  const stringMatches = useMemo(
    () => (graphLevel === 'L2' ? computeStringMatches(sqlText, stringMatchField) : []),
    [graphLevel, sqlText, stringMatchField],
  );

  // The ENGINE's claim: the flow closure's highlight set, read from the
  // DETAILED `l2Result.graph` namespace (never the merged projection), so the
  // coloring is identical across the flow-only / full / merged toggle.
  // Absent/empty flow sets ⇒ empty baseline ⇒ every match reads not-in-flow —
  // the truthful reading for a not-in-flow script.
  const stringMatchFlowLines = useMemo(() => flowLineSet(l2Result), [l2Result]);

  // The green/red split — disjoint Sets, ascending.
  const stringMatchSets = useMemo(
    () => classifyMatches(stringMatches, stringMatchFlowLines),
    [stringMatches, stringMatchFlowLines],
  );

  // The bar's counter. Non-null whenever an L2 search is active (INCLUDING
  // total: 0 — a 0-match search still renders the bar and the counter);
  // null = no active search, so the whole cluster stays unrendered.
  const stringMatchSummary = useMemo(() => {
    if (graphLevel !== 'L2' || !stringMatchField || !sqlText) return null;
    return {
      total: stringMatches.length,
      inFlow: stringMatchSets.covered.size,
      notInFlow: stringMatchSets.missed.size,
    };
  }, [graphLevel, stringMatchField, sqlText, stringMatches, stringMatchSets]);

  // Cursor (0-based) → the SQL line it points at. Invalid/out-of-range
  // positions read as inactive rather than guessing a line.
  const stringMatchActiveLine = useMemo(() => {
    if (stringMatchCursor == null) return null;
    const m = stringMatches[stringMatchCursor];
    return m && Number.isInteger(m.line) && m.line >= 1 ? m.line : null;
  }, [stringMatchCursor, stringMatches]);

  // What the SQL panel actually receives: hidden ⇒ no bands and no active
  // outline, while the counter above stays visible (AC2). The shared empty
  // set keeps the hidden render stable.
  const layerCovered = stringMatchVisible ? stringMatchSets.covered : EMPTY_MATCH_SET;
  const layerMissed = stringMatchVisible ? stringMatchSets.missed : EMPTY_MATCH_SET;
  const layerActiveLine = stringMatchVisible ? stringMatchActiveLine : null;

  // Reset the cursor whenever the match set's identity changes —
  // (scriptName, fieldName, sqlText): a new search, a script change or a
  // payload change always starts browsing inactive (AC4).
  useEffect(() => {
    setStringMatchCursor(null);
  }, [currentScriptName, stringMatchField, sqlText]);

  // …and clamp instead of guessing if the cursor is out of range after a
  // payload change that kept the identity (a re-fetch with fewer matches).
  useEffect(() => {
    if (stringMatchCursor == null) return;
    const n = stringMatches.length;
    if (n === 0) setStringMatchCursor(null);
    else if (stringMatchCursor >= n) setStringMatchCursor(n - 1);
    else if (stringMatchCursor < 0) setStringMatchCursor(null);
  }, [stringMatchCursor, stringMatches]);

  // The SEPARATE browse channel's single write site. The bar owns the ring
  // arithmetic (it renders the `3/17` readout and knows N) and hands over the
  // wrapped index; DataFlowApp only bounds-checks and stores it. Nothing here
  // touches `sqlHighlightLine` or `selectedEdge` — browsing never moves the
  // engine's amber line.
  const handleStringMatchStep = useCallback((i) => {
    if (!Number.isInteger(i) || i < 0) return;
    setStringMatchCursor(i);
  }, []);
  const handleStringMatchPrev = handleStringMatchStep;
  const handleStringMatchNext = handleStringMatchStep;

  const handleToggleStringMatch = useCallback(() => {
    // Turning the layer ON lands on the FIRST match (user requirement,
    // 2026-09-01): the naive bands are a comparison aid with no anchor of
    // their own, so activation picks the top of the match list and the
    // panel's browse channel scrolls that line to the middle. Resetting the
    // cursor HERE — on every activation, not only when it was idle — is what
    // makes repeated toggles re-land on the first match every time.
    if (!stringMatchVisible && stringMatches.length > 0) setStringMatchCursor(0);
    // Turning it OFF only hides the bands + the outline; the cursor keeps its
    // value (the ◀/▶ readout above stays put) and is re-set on the next ON.
    setStringMatchVisible(v => !v);
  }, [stringMatchVisible, stringMatches]);

  // Breadcrumb navigation
  const breadcrumb = [];
  if (activeView) {
    // Walk up to parent view for table/field if this is a child entry
    const parentView = activeView.parent_view_id
      ? views.find(v => v.view_id === activeView.parent_view_id)
      : null;
    const displayView = parentView || activeView;
    breadcrumb.push({
      label: `${displayView.table || ''}.${displayView.field || ''}`,
      icon: '🔍',
      onClick: activeView.view_id ? () => handleViewTreeClick(activeView.view_id) : undefined,
      link: graphLevel === 'L2',
      title: 'Back to L1 view',
    });
  }
  if (graphLevel === 'L2' && currentScriptName) {
    breadcrumb.push({
      label: currentScriptName.split('/').pop(),
      icon: '📄',
      link: false,
      title: 'Current script',
    });
  }

  // Keyboard shortcuts (R12.5)
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
        setGraphLevel("L1");
        setSelectedEdge(null); setSqlHighlightLine(null);
        // A8: the L2 panel unmounts on Escape — kill the story clock or
        // its interval keeps writing a highlight nothing renders.
        setStoryActiveIndex(null); setStoryAutoplay(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="dataflow-layout">
      {/* Error banner */}
      {error && (
        <div className="error-banner" onClick={() => setError(null)}>
          {error} <span style={{ float: 'right', cursor: 'pointer' }}>x</span>
        </div>
      )}

      {/* R31 concurrent-edit notice (A-M4) — shown on a layout 409: the
          server state changed by another user, our pending edit was re-applied
          on top of the fresh state. */}
      {toast && (
        <div className="concurrent-toast" onClick={() => setToast(null)} title="Dismiss">
          {toast} <span style={{ float: 'right', cursor: 'pointer', marginLeft: 8 }}>x</span>
        </div>
      )}

      {/* Wrapper for panels + graph (flex row) */}
      <div className="dataflow-main">
      {/* Left panel */}
      <div className="panel-left">
        {/* T8 (#295): "My workspaces" ALWAYS lives at the top of the
            debugger's left panel — list (role badges + quota + remove),
            📁 Select Folder, + Upload a folder (zip), and the open-by-id
            box. Each keyed remount refetches the list. Uploads create then
            open (handleOpenExisting reads the persisted tree + index — no
            rebuild); the WorkspacePanel below owns the explicit creator-only
            re-index control and no longer duplicates the upload pickers. */}
        <MyWorkspaces
          open
          onOpen={onOpenWorkspace}
          onUpload={handleSectionUpload}
          onRemove={handleSectionRemove}
        />
        <WorkspacePanel
          wsId={wsId} loading={loading} progress={progress}
          onUpload={handleUpload} onDelete={handleDeleteWorkspace}
          onError={setError}
          showUploads={false}
          indexedAt={indexedAt}
          isCreator={isCreator}
        />
        {fileTree && (
          <FolderTree
            tree={fileTree} selected={selectedScripts}
            onSelectionChange={setSelectedScripts}
            indexed={indexed}
          />
        )}
        {/* P1 catching-up window: the search panel is WITHHELD (not merely
            disabled) — its autocomplete reads the same in-flux index, so
            showing it would invite picking a table that is mid-update. The
            notice says why and for how long; the workspace itself (tree,
            open views, graphs) stays usable. */}
        {catchUp && (
          <div className="catchup-panel" data-testid="catchup-panel" role="status">
            <div className="catchup-title">Catching up…</div>
            <div className="catchup-line">
              {catchUp.changed == null
                ? 'Re-indexing changed scripts — search reopens when the index is whole.'
                : `Catching up: ${catchUp.changed} changed script${catchUp.changed === 1 ? '' : 's'}… search reopens when the index is whole.`}
            </div>
          </div>
        )}
        {/* P1 freshness, informational: a participant (who cannot rebuild,
            #272/#380) reading a stale-but-idle index is told so — search stays
            available, the creator's next open is what refreshes it. */}
        {indexed && !catchUp && staleHint && (
          <div className="stale-hint" data-testid="stale-hint" role="note">
            Index may be outdated — the creator's next open refreshes it.
          </div>
        )}
        {indexed && !catchUp && (
          <FilterPanel
            wsId={wsId}
            username={username}
            tableIndex={tableIndex} fieldIndex={fieldIndex}
            onSearch={handleSearch} loading={loading}
            onError={setError}
            recover={searchRecover}
            onFilterApplied={async (filterResult) => {
              if (filterResult && filterResult.filtered) {
                const ft = new Set(filterResult.filtered_tables || []);
                const ff = new Set(filterResult.filtered_fields || []);
                const filteredTI = {}; const filteredFI = {};
                for (const [k, v] of Object.entries(fullTableIndex)) {
                  if (ft.has(k)) filteredTI[k] = v;
                }
                for (const [k, v] of Object.entries(fullFieldIndex)) {
                  if (ff.has(k)) filteredFI[k] = v;
                }
                setTableIndex(filteredTI);
                setFieldIndex(filteredFI);
              } else {
                setTableIndex(fullTableIndex);
                setFieldIndex(fullFieldIndex);
              }
            }}
          />
        )}
        {/* R20: orphan resolution coverage report (index-time) */}
        {indexed && (
          <ResolutionReport
            stats={resolutionStats}
            orphanFieldSamples={orphanFieldSamples}
            schemaCandidates={schemaCandidates}
            schemaEvidence={schemaEvidence}
          />
        )}
        <ViewBar
          views={views} activeViewId={activeViewId}
          onSelect={handleViewTreeClick}
          canManageViews={isCreator}
          onRemove={handleDeleteView}
          onRemoveChild={async (parentId, childId) => {
            try {
              await api.deleteViewChild(wsId, parentId, childId);
              setViews(prev => {
                const updated = [...prev];
                const parent = updated.find(v => v.view_id === parentId);
                if (parent && parent.children) {
                  parent.children = parent.children.filter(c => c.view_id !== childId);
                }
                return updated;
              });
              // E-M7 (#282): deleting the ACTIVE L2 child drops back to L1 —
              // no stale L2 graph/header/SQL/toggle with no live view.
              if (activeViewId === childId) dropToL1();
            } catch (e) { setError(e.message); }
          }}
        />
      </div>

      {/* Resize handle: left | center */}
      <div {...leftResize.handleProps} />

      {/* Center: graph */}
      <div className="panel-center">
        {/* R3: visible notice for empty no-match search results (F1).
            Renders whenever the active view is a no_matches search — the
            backend message is shown verbatim. R29: no_flow (empty
            directional flow) renders the same way — the backend message
            ("No writing flow for T.F" / "No reading flow for T.F") is
            shown verbatim, never as an error. */}
        {activeView && (activeView.match_mode === 'no_matches' || activeView.match_mode === 'no_flow') && (
          <div className="no-match-banner">
            ⚠️ {activeView.match_mode === 'no_flow'
              ? `${activeView.message || 'no flow in this direction'} - empty result view`
              : `No matches: ${activeView.message || 'no tables in scope'} - empty result view`}
            {/* #400: one continuation per matched script — the L1 canvas is
                empty, so there is nothing to double-click. Opening swaps the
                banner for the L2 panel exactly like the L1 double-click (the
                active view becomes the child, whose own not-in-flow notice
                then explains the full-graph render). */}
            {noFlowScripts.length > 0 && (
              <div className="no-match-banner-actions">
                {noFlowScripts.map(s => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn-outline btn-sm banner-open-script"
                    disabled={loading}
                    onClick={() => handleOpenNoFlowScript(s)}
                    title={`Open ${scriptBaseName(s)}'s full Level 2 graph — the search matched this script, only this direction's flow is empty`}
                  >
                    Open {scriptBaseName(s)} full graph
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {/* V2-N4: matched scripts the L1 flow does NOT render. An exact-match
            search can match scripts whose own L2 answers search_matched:false
            (they never touch the searched field's downstream flow) — without
            this strip they are unreachable from the UI. Hidden when every
            matched script is in flow. */}
        {outOfFlowScripts.length > 0 && (
          <div className="no-match-banner banner-strip" data-testid="not-in-flow-strip">
            <span className="strip-label">Not in the flow:</span>
            {outOfFlowScripts.map(s => (
              <span key={s} className="strip-item">
                <span className="strip-script">{scriptBaseName(s)}</span>
                <button
                  type="button"
                  className="btn btn-outline btn-sm banner-open-script"
                  disabled={loading}
                  onClick={() => handleOpenNoFlowScript(s)}
                  title={`Open ${scriptBaseName(s)}'s full Level 2 graph — the search matched this script, but it is not in this view's rendered flow`}
                >
                  Open {scriptBaseName(s)} full graph
                </button>
              </span>
            ))}
          </div>
        )}
        {graphData && (
          <DataFlowGraph
            graphData={graphData}
            level="L1"
            layoutMode={l1LayoutMode}
            breadcrumb={breadcrumb}
            onOpenL2={handleOpenL2}
            onToggleLayout={(mode) => { if (mode) { setL1LayoutMode(mode); } else { setL1LayoutMode(m => m === 'snake' ? 'pipeline' : 'snake'); }}}
            onTableClick={handleTableClick}
            activeTable={activeL1Table}
            onClearTableFilter={handleClearTableFilter}
            onEdgeClick={handleEdgeClick}
            onCanvasTap={clearEdgeSelection}
            selectedEdgeId={selectedEdge?.id}
            refitKey={graphLevel}
            savedPositions={resumeLayouts['l1']}
            onPositionsChange={(positions) => handlePositionsChange('l1', positions)}
          />
        )}
        {loading && !graphData && (
          <div className="loading-skeleton">
            <div className="skeleton-header" />
            <div className="skeleton-graph">
              <div className="skeleton-node" style={{ top: '20%', left: '10%' }} />
              <div className="skeleton-node" style={{ top: '40%', left: '40%' }} />
              <div className="skeleton-node" style={{ top: '60%', left: '70%' }} />
              <div className="skeleton-node" style={{ top: '30%', left: '80%' }} />
              <div className="skeleton-edge" style={{ top: '35%', left: '20%', width: '25%' }} />
              <div className="skeleton-edge" style={{ top: '55%', left: '50%', width: '25%' }} />
            </div>
            <div className="skeleton-footer">Loading data flow...</div>
          </div>
        )}
        {!graphData && !wsId && !loading && (
          <div className="empty-state">Upload a folder to get started</div>
        )}
        {!graphData && wsId && indexed && !activeViewId && !loading && (
          <div className="empty-state">Search for a table.field to see data flow</div>
        )}
      </div>

      {/* Resize handle: L1 | L2 (vertical divider) */}
      {graphLevel === "L2" && <div {...l2Resize.handleProps} />}

      {/* L2 panel on the RIGHT of L1 (side-by-side) */}
      {graphLevel === 'L2' && (
        <div className="panel-inline-l2" style={{ width: l2PanelWidth, height: '100%' }}>
          <div className="inline-l2-header">
            <h3>📄 {currentScriptName?.split('/').pop() || 'Script'} — Level 2 Detail</h3>
          </div>
          <div className="inline-l2-graph">
            {/* A3: statement-level parse errors from the level2 response —
                one line per statement, backend detail shown verbatim. Uses the
                no-match-banner style in the BOTTOM slot (F-B2/S4 t47): the top
                slot below the toolbar belongs to the not-in-flow notice, and a
                bottom offset no longer has to guess its wrapped height. */}
            {l2ParseErrors.length > 0 && (
              <div className="no-match-banner banner-bottom">
                {l2ParseErrors.map(e => (
                  <div key={e.stmt_idx}>
                    ⚠️ SQL parse error in statement {e.stmt_idx} - {e.detail || 'check the script syntax'}
                  </div>
                ))}
              </div>
            )}
            {/* L2 not-in-flow: search field not referenced in this script —
                backend message shown verbatim above the full-script graph */}
            {l2NotInFlow && (
              <div className="no-match-banner">
                ⚠️ {l2NotInFlowMessage || 'Field not in this script - showing the full script graph'}
              </div>
            )}
            {/* F-B2 (S4 finding 6): a clicked element whose payload line is
                0/absent says so here — never a silent no-op. Neutral (not a
                warning), bottom slot, self-clears on the next valid click. */}
            {sqlLineNotice && (
              <div className="no-match-banner banner-bottom banner-neutral" role="status">
                {sqlLineNotice}
              </div>
            )}
            <DataFlowGraph
              graphData={l2GraphData}
              level="L2"
              layoutMode={l2LayoutMode}
              breadcrumb={[]}
              onEdgeClick={handleEdgeClick}
              onNodeClick={handleNodeClick}
              onCanvasTap={clearEdgeSelection}
              selectedEdgeId={selectedEdge?.id}
              viewMode={l2ViewMode}
              onViewModeChange={setL2ViewMode}
              flowNodeIds={l2Result?.flow_node_ids}
              flowEdgeIds={flowEdgeIds}
              savedPositions={resumeLayouts[resumeLayoutKey('l2', l2LayoutScriptKey)]}
              onPositionsChange={(positions) => handlePositionsChange('l2', positions)}
              storyFocus={storyFocus}
              onToggleLayout={(mode) => { if (mode) { setL2LayoutMode(mode); } else { setL2LayoutMode(m => m === 'snake' ? 'pipeline' : 'snake'); }}}
            />
          </div>
          {/* Resize handle: L2 graph | SQL panel */}
          <div {...sqlResize.handleProps} />
          {sqlText && (
            <>
              <div className="inline-l2-sql" style={{ height: sqlPanelHeight }}>
                <SqlPanel
                  ref={sqlPanelRef}
                  sqlText={sqlText}
                  sqlHighlightLine={sqlHighlightLine}
                  scriptName={currentScriptName}
                  wsId={wsId}
                  table={activeView?.table || ""}
                  field={activeView?.field || ""}
                  stringMatchCovered={layerCovered}
                  stringMatchMissed={layerMissed}
                  stringMatchActiveLine={layerActiveLine}
                />
              </div>
              {/* Field Story step-through bar — BELOW the SQL panel (the
                  slot the old flow-reason panel occupied), only when the
                  searched field's story has steps. Clicking a step lights
                  its edges/nodes (storyFocus) and scrolls the SQL panel
                  via the R37 channel; ✕ dismisses (focus null → dim
                  cleared). R10-#18: only rendered when there is a script
                  (sqlText) to scroll to.
                  R40.13: the gate WIDENS — the bar also renders when an L2
                  search is active with no story steps, because that is where
                  the string-match browse controls live; the story chips +
                  autoplay still render only when steps exist. */}
              {(fieldStory && fieldStory.steps.length > 0)
                || stringMatchSummary != null ? (
                <FieldStoryBar
                  steps={(fieldStory && fieldStory.steps) || []}
                  activeIndex={storyActiveIndex}
                  onStep={handleStoryStep}
                  onPrev={handleStoryPrev}
                  onNext={handleStoryNext}
                  autoplay={storyAutoplay}
                  onToggleAutoplay={handleStoryToggleAutoplay}
                  onDismiss={handleStoryDismiss}
                  stringMatchSummary={stringMatchSummary}
                  stringMatchCursor={stringMatchCursor}
                  stringMatchVisible={stringMatchVisible}
                  onToggleStringMatch={handleToggleStringMatch}
                  onPrevStringMatch={handleStringMatchPrev}
                  onNextStringMatch={handleStringMatchNext}
                />
              ) : null}
            </>
          )}
        </div>
      )}

      </div>{/* end .dataflow-main */}
      {/* Log panel resize handle */}
      {/* Log panel — bottom bar, collapsible, resizable */}
      {wsId && showLog && <LogPanel wsId={wsId} visible={true} onClose={() => setShowLog(false)} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// R32 (display-only): captions for line-merged SELF-LOOP edges.
//
// In a merged view a filter edge whose endpoints BOTH promote to the same
// table — e.g. `⟂ p_dt → east5` @190 where p_dt sits on east5_stzfxxb —
// becomes that table's self-loop `east5_stzfxxb → east5_stzfxxb` (backend
// build_line_merged_edges rule 4: kept as the line's sole edge). The merge
// pass erases the mechanism AND the field (`edge_type:"FLOW"`, label
// "FLOW"), so today it renders as an unlabeled tiny arc with no meaning.
// The information is NOT lost — it is recoverable from two payloads the
// client already holds: the merged NODE list (types + parents intact, never
// stripped at this layer) and the DETAILED closure edges (`l2Result.graph`
// .edges), which still name the absorbed field edges.
//
// Pure lookup, no fetches: for every detailed closure edge both of whose
// endpoints resolve to one table id while at least one endpoint IS a field,
// record that field's label under key `${highlight_line}|${tableId}` — but
// only when at least one such edge carries `edge_type === "FILTER"` (non-
// FILTER self-loops keep their uniform anonymity; only filters were judged
// meaningless without the caption). Returns Map(key → sorted comma-joined
// field labels); an empty Map for absent/malformed input — never a guess.
// ══════════════════════════════════════════════════════════════════
export function selfLoopFilterLabels(fullNodes, closureEdges) {
  const out = new Map();
  if (!Array.isArray(fullNodes) || !Array.isArray(closureEdges)) return out;

  // id → payload node data. fullNodes is the SERVED list, so parents are
  // present here — stripFieldParents happens later, inside Cytoscape prep.
  const byId = new Map();
  for (const n of fullNodes) {
    const d = n && n.data;
    if (d && d.id !== undefined) byId.set(d.id, d);
  }
  // Endpoint → {table, field, label}: a field promotes to its parent table
  // (merge rule 1); a parent-LESS field keeps its own id — exactly what the
  // backend does for those classifier-gap endpoints — and everything else
  // is already table-level.
  const endpoint = (id) => {
    const nd = byId.get(id);
    if (nd && nd.type === 'field') {
      return { table: nd.parent || id, field: true, label: nd.label };
    }
    return { table: id, field: false, label: null };
  };

  // key → {labels:Set, filter:boolean} — per (line, table) absorption site.
  const seen = new Map();
  for (const e of closureEdges) {
    const ed = e && e.data;
    if (!ed || ed.source === undefined || ed.target === undefined) continue;
    const line = Number(ed.highlight_line);
    if (!Number.isInteger(line) || line < 1) continue;
    const src = endpoint(ed.source);
    const tgt = endpoint(ed.target);
    if (src.table !== tgt.table) continue;   // different tables → normal arc
    if (!src.field && !tgt.field) continue;  // no promotion happened here
    const key = `${line}|${src.table}`;
    let rec = seen.get(key);
    if (!rec) seen.set(key, (rec = { labels: new Set(), filter: false }));
    for (const side of [src, tgt]) {
      if (side.field && side.label != null) rec.labels.add(String(side.label));
    }
    if (ed.edge_type === 'FILTER') rec.filter = true;
  }

  for (const [key, rec] of seen) {
    // Only FILTER-kind absorptions get a caption, and only when a field
    // label was actually collected — otherwise the text would read "⟂ "
    // with nothing between it and "(filtered…)".
    if (rec.filter && rec.labels.size > 0) out.set(key, [...rec.labels].sort().join(', '));
  }
  return out;
}

function collectSqlFiles(tree) {
  const paths = [];
  if (tree.type === 'file' && tree.is_sql) paths.push(tree.path);
  if (tree.children) tree.children.forEach(c => paths.push(...collectSqlFiles(c)));
  return paths;
}

// Display label for a workspace rel_path (banner buttons, L2 header) — the
// basename only, so a deep script still fits the banner box.
function scriptBaseName(path) {
  return String(path || '').split('/').pop();
}

// ════════════════════════════════════════════════════════════════════
// P1 index-freshness contract (v3.3.194) — read defensively, require nothing.
//
//   GET /resume, GET /workspace/{id}/status → index_change
//   GET /index                              → freshness + catching_up
//   POST /index response                    → catching_up:false (+ reused/
//                                             extracted_scripts, filtered_index_cleared)
//
// `freshness` and `index_change` carry the SAME object:
//   { changed_scripts, changed_count (alias), added_count, removed_count,
//     schema_changed_count, total, indexed_at, extractor_version,
//     current_extractor_version, stale, reason }
// Counts are pipeline-scoped: changed_count is exactly what an incremental
// rebuild would extract.
function readFreshness(payload) {
  const p = payload && typeof payload === 'object' ? payload : {};
  const status = p.indexed && typeof p.indexed === 'object' ? p.indexed : null;
  // Accept either a WRAPPER payload ({freshness}|{index_change}|{indexed:{…}})
  // or the freshness object itself ({stale, changed_count, …}) — /resume hangs
  // the object off `index_change`, so the call site reads
  // readFreshness(resume.index_change) and lands here directly.
  const isFreshnessItself = p.stale !== undefined || p.changed_count !== undefined
    || p.changed_scripts !== undefined || p.reason !== undefined;
  const f = isFreshnessItself ? p
    : (p.freshness || p.index_change
      || (status && (status.freshness || status.index_change)) || null);
  if (!f || typeof f !== 'object') {
    return { present: false, stale: false, changed: null, indexedAt: null };
  }
  const raw = f.changed_count ?? f.changed_scripts;
  const changed = typeof raw === 'number' ? raw : Array.isArray(raw) ? raw.length : null;
  return {
    present: true,
    stale: f.stale === true,
    changed,
    indexedAt: typeof f.indexed_at === 'string' && f.indexed_at ? f.indexed_at : null,
  };
}

// A catch-up is IN FLIGHT only when a flag says so. `freshness.stale` alone
// must NEVER start a hold: a stale index nobody is rebuilding would hold
// search forever. Staleness is the AUTO-TRIGGER's signal (fire POST /index —
// the in-flight call then flips `catching_up` and the 409 gate protects the
// other readers); a participant who cannot rebuild gets a hint, not a lockout.
function readCatchUp(payload) {
  const p = payload && typeof payload === 'object' ? payload : {};
  const status = p.indexed && typeof p.indexed === 'object' ? p.indexed : null;
  const flag = [p.catching_up, p.reindexing, status && status.catching_up, status && status.reindexing]
    .find(v => typeof v === 'boolean');
  if (typeof flag !== 'boolean') return { catchingUp: false, changed: null };
  return { catchingUp: flag, changed: readFreshness(p).changed };
}

// ════════════════════════════════════════════════════════════════════
// MSC-1 (2026-08-31): the two 409s a search can get.
//
//   P1 index catch-up  "Index is being updated for this workspace — retry in
//                       a moment"   → hold + poll + replay (the search is
//                       fine, its SCOPE is mid-rebuild)
//   R31 heavy gate     "system busy — please wait"   → transient service
//                       condition: surface it, never hold, never replay
//
// The catch-up is recognised by its own words, not by the status code alone —
// the heavy gate returns the SAME 409 with a different detail. Both spellings
// of the catch-up sentence (em dash and plain hyphen) match; the match is
// case-insensitive because the sentence belongs to the backend.
// ════════════════════════════════════════════════════════════════════
const BUSY_409_MESSAGE = 'The service is busy — please retry in a moment';

function isIndexCatchUp409(e) {
  if (e?.status !== 409) return false;
  return /index is being updated/i.test(String(e?.message || ''));
}

// ════════════════════════════════════════════════════════════════════
// P4 (2026-08-31): what a FAILED catch-up poll means — and the "is this
// payload an index at all" read.
//
// A poll failure is one of three very different things:
//   404  the workspace is GONE (deleted in another tab mid-hold) — no number
//        of retries brings it back;
//   401  the session EXPIRED — the shared interceptor (E-M1) is already
//        handing the shell to login;
//   else TRANSIENT (a dropped connection, a 5xx) — worth retrying, bounded.
//
// The status is read off the error object when the client carries it
// (`searchDataFlow` does; a client that attaches it everywhere is the real
// fix), then off the server's own detail wording ("Workspace not found",
// "Not logged in"), then off the client's `HTTP <code>` fallback for a
// non-JSON body. The wording is the backend's, so the match is
// case-insensitive and deliberately narrow — an unknown error must classify
// as TRANSIENT, never as a terminal one.
// ════════════════════════════════════════════════════════════════════
const POLL_GONE = 'gone';
const POLL_UNAUTHORIZED = 'unauthorized';

function classifyIndexPollError(e) {
  const status = typeof e?.status === 'number' ? e.status : null;
  const message = String(e?.message || '');
  if (status === 404 || /workspace not found/i.test(message)) return POLL_GONE;
  if (status === 401 || /not logged in/i.test(message) || /http 401\b/i.test(message)) {
    return POLL_UNAUTHORIZED;
  }
  return 'transient';
}

// Does this index payload describe an index that can serve a search? The
// corrupt/missing-cache convention reads as {} (never 500), so a payload can
// legitimately carry nothing: an empty table_index AND no `indexed` status,
// or a status that says indexed:false, must not switch search on.
function hasServedIndex(payload) {
  const p = payload && typeof payload === 'object' ? payload : {};
  if (p.table_index && Object.keys(p.table_index).length > 0) return true;
  const status = p.indexed;
  const flag = typeof status === 'boolean'
    ? status
    : (status && typeof status === 'object' ? status.indexed : undefined);
  return flag === true;
}
