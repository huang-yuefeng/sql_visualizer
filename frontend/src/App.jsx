import React, { useState, useEffect, useRef, useCallback } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
cytoscape.use(fcose);
import * as api from './api/client';
import { NODE_STYLES, LAYOUT_OPTIONS } from './utils/graphStyles';
import D from './utils/debug';
import { exportCurrentView } from './utils/export';

const C = {
  script:'#F39C12',
  table:'#4A90D9',view:'#5DADE2',column:'#A8D4FF',cte:'#5CB85C',
  cte_column:'#8FD98F',expression:'#F0AD4E',window:'#967ADC',
  aggregate:'#37BC9B',case:'#D770AD',transform:'#FFCE54',
  literal:'#CCCCCC',merge_target:'#DA4453',union_branch:'#E6E9ED',subquery:'#AC92EC',
  virtual_table:'#2ECC71',
};
const EC = {TABLE_FLOW:'#2ECC71',SCHEMA:'#8AB4F8',ALIAS:'#1ABC9C',REF:'#9AA0A6',AGGREGATE:'#37BC9B',TRANSFORM:'#F0AD4E',WINDOW:'#967ADC',COMPUTED:'#D770AD',INDIRECT:'#5DADE2',DML:'#E74C3C',SUBSET:'#E67E22',FILTER:'#3498DB',SET_OP:'#9B59B6'};

const VT = [{value:'',label:'All Types'},{value:'script',label:'Script',desc:'Entire SQL script (multi-view)'},{value:'table',label:'Table',desc:'TABLE, TEMP TABLE, FOREIGN DATA WRAPPER'},{value:'view',label:'View',desc:'VIEW, MATERIALIZED VIEW (virtual source)'},{value:'virtual_table',label:'Output',desc:'Result of a SELECT / JOIN statement'},{value:'cte',label:'CTE',desc:'Common Table Expression (WITH ... AS)'},{value:'subquery',label:'Subquery',desc:'SUBQUERY in FROM / JOIN'},{value:'merge_target',label:'Merge',desc:'Target table in MERGE INTO'},{value:'union_branch',label:'Union',desc:'UNION / INTERSECT / EXCEPT branch'},{value:'column',label:'Column',desc:'Column reference: table.column or bare name'},{value:'cte_column',label:'CTE Col',desc:'Column inside a CTE definition'},{value:'aggregate',label:'Aggregate',desc:'SUM, COUNT, AVG, MIN, MAX'},{value:'window',label:'Window',desc:'ROW_NUMBER, RANK, LAG, SUM OVER'},{value:'case',label:'Case',desc:'CASE WHEN ... THEN ... END'},{value:'transform',label:'Transform',desc:'COALESCE, CAST, CONCAT result'},{value:'expression',label:'Expression',desc:'Computed alias like (a+b) AS total'},{value:'literal',label:'Constant',desc:'String or number literal'}];
const ET = [{value:'',label:'All Edges'},{value:'TABLE_FLOW',label:'TABLE_FLOW',desc:'Table-to-table data flow (high-level)'},{value:'SCHEMA',label:'SCHEMA',desc:'Column belongs to table'},{value:'ALIAS',label:'ALIAS',desc:'Alias → original name'},{value:'REF',label:'REF',desc:'Direct column reference'},{value:'AGGREGATE',label:'AGGREGATE',desc:'SUM/COUNT/AVG'},{value:'TRANSFORM',label:'TRANSFORM',desc:'COALESCE/CAST'},{value:'WINDOW',label:'WINDOW',desc:'Window function'},{value:'COMPUTED',label:'COMPUTED',desc:'CASE WHEN expression'},{value:'INDIRECT',label:'INDIRECT',desc:'HAVING→SELECT ref'},{value:'FILTER',label:'FILTER',desc:'WHERE/HAVING condition'},{value:'DML',label:'DML',desc:'INSERT/UPDATE/DELETE'},{value:'SET_OP',label:'SET_OP',desc:'UNION/INTERSECT/EXCEPT'},{value:'SUBSET',label:'SUBSET',desc:'Disconnected component bridge'}];

export default function App() {
  const [scripts, setScripts] = useState([]);
  const [sel, setSel] = useState(null);
  const [gd, setGd] = useState(null);
  const [loading, setLoading] = useState(false);
  const [prog, setProg] = useState({s:'',p:0});
  const [sq, setSq] = useState(''); const [tf, setTf] = useState(''); const [ef, setEf] = useState('');
  const cyR = useRef(null); const ctR = useRef(null); const flR = useRef(null);
  const [panel, setPanel] = useState(null);
  const viR = useRef({}); const diR = useRef({});
  const [tip, setTip] = useState({show:false,x:0,y:0,text:''});
  const tipDesc = Object.fromEntries(VT.map(t=>[t.value,t.desc||'']));
  const edgeDesc = Object.fromEntries(ET.map(t=>[t.value,t.desc||'']));
  const sqlR = useRef(''); const lmR = useRef({}); const snipR = useRef({});
  const [showSQL, setShowSQL] = useState(false);
  const [version, setVersion] = useState('');
  const [ioGraph, setIoGraph] = useState(null);
  const [ioPaths, setIoPaths] = useState([]);
  const ioRef = useRef(null);
  const [csvName, setCsvName] = useState('');
  const [csvContent, setCsvContent] = useState('');
  const [viewMode, setViewMode] = useState('tables'); // 'tables' | 'full'
  const [multiView, setMultiView] = useState(null);
  const multiRef = useRef(null);
  const [multiDetail, setMultiDetail] = useState(null);
  const multiCyRef = useRef(null);
  const multiDtlRef = useRef(null);
  const [showInfo, setShowInfo] = useState(true);
  const [filterTables, setFilterTables] = useState(null);
  const filterRef = useRef(null);
  const [filteredViews, setFilteredViews] = useState([]);
  const multiOriginal = useRef(null);
  const savedPositions = useRef(null); // preserve node positions
  const [multiLayout, setMultiLayout] = useState('ring');
  const multiGraphCache = useRef({});
  const dbg = (msg) => { D(msg); setProg({s:msg, p:0}); };
  

  useEffect(() => { api.listScripts().then(setScripts).catch(()=>{}); fetch('/api/health').then(r=>r.json()).then(d=>{setVersion(d.version);window.setDebugVersion&&window.setDebugVersion(d.version)}).catch(()=>{}); }, []);

  const load = useCallback(async (s) => {
    if (!s) return; D('📥 load() called: '+s.script_name);
    setLoading(true); setProg({s:'Loading...',p:10});
    try {
      // Check multi-view cache first
      let d = multiGraphCache.current[s.script_id];
      if (!d) {
        d = await api.getGraph(s.script_id, true);
        if (d) multiGraphCache.current[s.script_id] = d;
      }
      if (!d) { D('❌ load() cache miss: '+s.script_name); setProg({s:'Not found',p:0}); setLoading(false); return; }
      D('✅ load() got graph: '+s.script_name+' nodes='+(d.nodes?.length||0)+' edges='+(d.edges?.length||0));
      const tpl = d.template_replacements || [];
      if (tpl.length) { D('🔧 template replacements: '+tpl.length); tpl.slice(0,20).forEach(r=>D('  '+r)); }
      setGd(d); setProg({s:'',p:0}); setShowInfo(true);
      const vi={}; d.nodes.forEach(n=>{vi[n.data.id]=n.data;}); viR.current=vi;
      snipR.current = (d.snippets||{});
      const di={}; d.edges.forEach(e=>{di[`${e.data.source}→${e.data.target}`]=e.data;}); diR.current=di;
      sqlR.current = d.sql_text||''; lmR.current = d.line_map||{};
    } catch { setProg({s:'Failed',p:0}); }
    finally { setLoading(false); }
  }, []);
  useEffect(()=>{if(sel)load(sel);},[sel,load]);

  useEffect(() => {
    try {
    dbg('🔄 useEffect: ioGraph='+!!ioGraph+' sel='+!!sel+' gd='+!!gd+' multiView='+!!multiView+' multiDetail='+!!multiDetail);
    let data = ioGraph || gd;
    if (ioGraph) {
      data = ioGraph;
      D('📊 IO graph active: nodes='+(data.nodes?.length||0)+' edges='+(data.edges?.length||0));
    } else if (sel && gd) {
      D('📄 Single view: sel='+(sel?.script_name||'?')+' nodes='+gd?.nodes?.length); data = gd;
    } else if (multiDetail) {
      data = multiDetail.graph;
    } else if (multiView && !sel) {
      D('🔍 Filter: multiView mode active');
      data = {nodes: multiView.meta_nodes, edges: multiView.meta_edges};
    }
    if (!data || !ctR.current) return;
    if (cyR.current) cyR.current.destroy();

    let renderNodes = (data.nodes||[]).map(n => ({...n, data: {...n.data}}));
    let renderEdges = [...(data.edges||[])];

    // Tables view: only show table-like nodes, filter out columns + computed
    if (viewMode === 'tables' && sel && gd && !ioGraph) {
      const tableTypes = new Set(['table','view','cte','virtual_table','merge_target','subquery','union_branch']);
      renderNodes = renderNodes.filter(n => tableTypes.has(n.data.variable_type));
      const nodeIds = new Set(renderNodes.map(n => n.data.id));
      renderEdges = renderEdges.filter(e => nodeIds.has(e.data.source) && nodeIds.has(e.data.target));
    }

    // Create Cytoscape empty, add elements + layout in one batch to avoid flash
    dbg('🟢 Creating Cytoscape instance'); const cy = cytoscape({
      container: ctR.current,
      elements: [],
      style: [...NODE_STYLES],
      wheelSensitivity: 0.3,
      // Performance settings for large graphs
      pixelRatio: (viewMode==='tables'&&!ioGraph)?1:1.5,
      textureOnViewport: true,
      hideEdgesOnViewport: viewMode==='full',
      hideLabelsOnViewport: viewMode==='full',
    });
    cy.on('mouseover','node',e=>{
      e.target.closedNeighborhood().removeClass('dimmed');
      cy.elements().not(e.target.closedNeighborhood()).addClass('dimmed');
      const nd = e.target.data();
      // Meta-graph: show I/O summary on hover
      if (nd.type === 'script_circle') {
        const sc = multiView?.scripts?.find(s=>s.script_id===nd.id);
        const ins = sc?.input_tables?.join(', ') || '(none)';
        const outs = sc?.output_tables?.join(', ') || '(none)';
        setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,
          text:`${nd.label}\n📥 in: ${ins}\n📤 out: ${outs}\nClick to open`});
      } else {
        const vt = nd.variable_type;
        if (vt) { const d = tipDesc[vt]||vt; setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,text:d}); }
      }
    });
    cy.on('mousemove','node',e=>{if(tip.show)setTip(t=>({...t,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10}));});
    cy.on('mouseout','node',()=>{cy.elements().removeClass('dimmed');setTip({show:false,x:0,y:0,text:''});});
    cy.on('tap','node',e=>{
      const id=e.target.id(); const nd=e.target.data();
      // Meta-graph nodes handled by multi-view specific handler below
      if (multiView && nd.type === 'script_circle') return; // handled by multi-view handlers
      const eds=(data?.edges||[]).filter(x=>x.data.source===id||x.data.target===id);
      const vi=ioGraph?{}:viR.current;
      setPanel({type:'node',id,node:vi[id]||{label:id},edges:eds.map(x=>({sid:x.data.source,tid:x.data.target,rel:x.data.relationship})),title:vi[id]?.label||id});
    });
    cy.on('mouseover','edge',e=>{
      const ed = e.target.data();
      // Meta-graph edges: show edge type
      if (ed.edge_type) {
        const descs = {data_lineage:'📤→📥 Data lineage: output→input', shared_input:'📥 Shared input table', shared_var:'🔗 Shared variable name'};
        setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,text:descs[ed.edge_type]||ed.edge_type});
      } else {
        const r = ed.relationship; if(r){const d=edgeDesc[r]||r;setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,text:d});}
      }
    });
    cy.on('mousemove','edge',e=>{if(tip.show)setTip(t=>({...t,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10}));});
    cy.on('mouseout','edge',()=>{setTip({show:false,x:0,y:0,text:''});});
    cy.on('tap','edge',e=>{
      const sid=e.target.data('source'),tid=e.target.data('target');
      if (ioGraph) {
        // Show path details for IO graph
        const pathInfo = ioPaths.find(p => {
          const nids = p.nodes.map(n=>n.id);
          return nids.includes(sid) && nids.includes(tid);
        });
        setPanel({type:'io_path',sid,tid,pathInfo,src:{label:sid},tgt:{label:tid},title:`Path segment`});
      } else {
        const edge=diR.current[`${sid}→${tid}`];
        setPanel({type:'edge',sid,tid,edge:edge||{source:sid,target:tid,relationship:'',operation:''},src:viR.current[sid],tgt:viR.current[tid],title:`${viR.current[sid]?.label||sid} → ${viR.current[tid]?.label||tid}`});
      }
    });
    // Meta-graph: click script parent → highlight + show detail in panel
    D('🔍 Filter: multiView='+!!multiView+' sel='+!!sel+' mode='+(multiView&&!sel?'multi':'single')); if (multiView && !sel) {
      // Single click → show details in right panel
      cy.on('tap','node',e=>{
        const nd = e.target.data();
        if (nd.type !== 'script_circle') return;
        const sc = multiView.scripts.find(s=>s.script_id===nd.id);
        if (!sc) return;
        D('🖱️ Single click: '+nd.label+' → info panel'); setShowInfo(true); setPanel({type:'script_meta', id:nd.id, script:sc, title:sc.script_name});
      });
      // Double click → open as single script view
      cy.on('dbltap','node',e=>{
        const nd = e.target.data();
        if (nd.type !== 'script_circle') return;
        const sc = multiView.scripts.find(s=>s.script_id===nd.id);
        if (!sc || !sc.graph) return;
        const entry = {script_id: sc.script_id, script_name: sc.script_name,
                       total_variables: sc.total_variables, total_dependencies: sc.total_dependencies};
        D('🖱️🖱️ Double click: '+nd.label+' → open single view, sel='+!!entry); const graphCopy = JSON.parse(JSON.stringify(sc.graph));
        multiGraphCache.current[sc.script_id] = graphCopy;
        setSel({...entry}); setGd(graphCopy); setShowInfo(true); setPanel(null);
        const vi={}; graphCopy.nodes.forEach(n=>{vi[n.data.id]=n.data;}); viR.current=vi; sqlR.current = graphCopy.sql_text||''; lmR.current = graphCopy.line_map||{};
        const di={}; graphCopy.edges.forEach(e=>{di[`${e.data.source}→${e.data.target}`]=e.data;}); diR.current=di;
        setIoGraph(null); setIoPaths([]);
        setScripts(prev => {
          if (prev.some(s=>s.script_id===sc.script_id)) return prev;
          return [{...entry, analyzed_at: ''}, ...prev];
        });
      });
      // Tap edge → show lineage info
      cy.on('tap','edge',e=>{
        const ed = e.target.data();
        if (ed.edge_type) {
          setPanel({type:'meta_edge', edge:ed,
            title: ed.edge_type==='data_lineage'?'📤→📥 Data Lineage':'📥 Shared Input'});
        }
      });
      // Tap background → show multi overview
      cy.on('tap', e => { if (e.target === cy && multiView) { setPanel(null); setMultiDetail(null); setShowInfo(true); } });
    }
    cyR.current=cy;
    const runLayout = () => {
      dbg('📏 Container check: ctR='+!!ctR.current+' w='+(ctR.current?.clientWidth||0)); const w = ctR.current?.clientWidth || 0;
      if (w > 0) {
        const added = cy.add([...renderNodes, ...renderEdges]); dbg('➕ Added '+added.nodes().length+' nodes + '+added.edges().length+' edges');
        if (added.nodes().length === 0) { D('⚠️ Empty graph — no layout needed'); return; }
        D('🔍 Filter: multiView='+!!multiView+' sel='+!!sel+' mode='+(multiView&&!sel?'multi':'single')); if (multiView && !sel) {
          const n = renderNodes.length;
          const e = renderEdges.length;
          dbg('📐 Multi layout: ring mode, n='+renderNodes.length); const spKeys = savedPositions.current ? Object.keys(savedPositions.current).length : 0; D('💾 savedPositions has '+spKeys+' keys, n='+n); const hasSavedPos = spKeys > 0; if (multiLayout === 'ring') { dbg('📍 Entering ring block, added='+!!added);
            // Ring arrangement with auto-zoom for readability
            const sp = 70;
            const R = (n * sp) / (2 * Math.PI);
            const centerX = R + 50, centerY = R + 50;
            dbg('📍 Positioning '+n+' nodes on ring R='+Math.round(R)); dbg('📍 Running forEach on '+added.nodes().length+' nodes'); if (hasSavedPos) { let restored=0; D('📍 Restoring '+n+' nodes from saved positions ('+spKeys+' saved)'); added.nodes().forEach(nd => { const p = savedPositions.current[nd.id()]; if (p) { nd.position(p); restored++; } }); D('📍 Restored '+restored+'/'+n+' nodes'); cy.fit(undefined, 30); } else { added.nodes().forEach((nd, i) => {
              const a = (2 * Math.PI * i) / n - Math.PI / 2;
              nd.position({x: centerX + R * Math.cos(a), y: centerY + R * Math.sin(a)});
            }); } let tries = 0;
            const doFit = () => {
              const bb = cy.elements().boundingBox();
              D('Ring fit #'+tries+' bbW='+Math.round(bb.w)+' bbH='+Math.round(bb.h));
              if (bb.w > 10 && bb.h > 10) {
                cy.fit(undefined, 30); cy.minZoom(0.1); cy.maxZoom(3);
                if (!sel && (!savedPositions.current || multiView === multiOriginal.current)) {
                  const sp={};cy.nodes().forEach(nd=>{sp[nd.id()]=nd.position();});savedPositions.current=sp;
                  D('Ring fit OK, saved '+Object.keys(sp).length+' positions (original)');
                } else {
                  D('Ring fit OK (filtered — using saved positions)');
                }
              } else if (++tries < 30) {
                requestAnimationFrame(doFit);
              } else {
                D('Ring fit FAIL after 30 tries');
              }
            };
            requestAnimationFrame(doFit);
          } else {
            cy.layout({name:'cose', animate: true, fit: true, padding: 30}).run();
          }
        } else {
          dbg('📐 Single layout: cose'); cy.layout({name:'cose',...LAYOUT_OPTIONS}).run();
        }
      } else {
        requestAnimationFrame(runLayout);
      }
    };
    requestAnimationFrame(runLayout);
    return ()=>{cy.destroy();};
    } catch(e) { D('💥 useEffect CRASH: '+e.message); console.error(e); }
  },[gd,ioGraph,ioPaths,viewMode,multiView,multiDetail,multiLayout]);

  const upload = async e => {
    const f=e.target.files?.[0]; if(!f) return;
    setLoading(true); setProg({s:'Analyzing...',p:30});
    try { const t=await f.text(); const r=await api.analyzeSql(t,f.name); const fresh=await api.listScripts(); setScripts(fresh); setSel(r); }
    catch(err){alert('Failed: '+err.message);setLoading(false);setProg({s:'',p:0});}
  };
  const paste = async () => {
    const t=prompt('Paste SQL:'); if(!t) return;
    setLoading(true); setProg({s:'Analyzing...',p:30});
    try { const r=await api.analyzeSql(t,'pasted.sql'); const fresh=await api.listScripts(); setScripts(fresh); setSel(r); }
    catch(err){alert('Failed: '+err.message);setLoading(false);setProg({s:'',p:0});}
  };

  const filter = useCallback(()=>{
    if(!cyR.current) return;
    const cy=cyR.current; cy.elements().removeClass('highlighted');
    if(!sq&&!tf&&!ef){cy.elements().style('opacity',1);return;}
    cy.nodes().forEach(n=>{const d=n.data();let m=true;if(sq&&!d.label.toLowerCase().includes(sq.toLowerCase()))m=false;if(tf&&d.variable_type!==tf)m=false;n.style('opacity',m?1:0.12);if(m)n.addClass('highlighted');});
    cy.edges().forEach(e=>{const d=e.data();let m=true;if(ef&&d.relationship!==ef)m=false;if(sq&&!(d.label||'').toLowerCase().includes(sq.toLowerCase()))m=false;e.style('opacity',m?1:0.08);if(m)e.addClass('highlighted');});
  },[sq,tf,ef]);
  useEffect(()=>{filter();},[sq,tf,ef,filter]);

  const pshow = !!prog.s;
  return (
    <div className="app-container">
      <header className="app-header">
        <h1>GPS SQL Data Flow Visualizer {version && <span style={{fontSize:'0.6rem',color:'#666',fontWeight:400}}>v{version}</span>}</h1>
        <div className="header-actions">
          <label className="btn btn-primary" style={{cursor:'pointer'}}>Multi SQL<input ref={multiRef} type="file" accept=".sql,.txt" multiple onChange={async e=>{
            const fs=[...e.target.files]; if(fs.length<2) return;
            setLoading(true); const total=fs.length; const t0=Date.now();
            setProg({s:`Analyzing 0/${total}...`,p:0});
            // Progress timer
            const timer=setInterval(()=>{
              const elapsed=((Date.now()-t0)/1000).toFixed(1);
              setProg(p=>({...p,s:`Analyzing ${total} scripts... ${elapsed}s`}));
            },200);
            try{
              const fd=new FormData(); fs.forEach(f=>fd.append('files',f));
              const r=await fetch('/api/analyze_multi',{method:'POST',body:fd});
              const d=await r.json(); setMultiView(d); multiOriginal.current = d; savedPositions.current = null; setMultiDetail(null); setFilterTables(null); setFilteredViews([]); setMultiLayout('ring'); setSel(null); setGd(null); setIoGraph(null); setIoPaths([]); setPanel(null);
              setProg({s:`Done in ${((Date.now()-t0)/1000).toFixed(1)}s`,p:100});
              setTimeout(()=>setProg({s:'',p:0}),1500);
            }catch{setProg({s:'',p:0});}
            finally{clearInterval(timer);setLoading(false);}
            e.target.value='';
          }} hidden/></label>
          <label className="btn btn-secondary" style={{cursor:'pointer'}}>Single SQL<input ref={flR} type="file" accept=".sql,.txt" onChange={upload} hidden/></label>
          <button className="btn btn-secondary" onClick={paste}>Paste SQL</button>
          {multiView && <select className="type-select" style={{width:'auto',marginTop:0,padding:'4px 8px'}} value={multiLayout} onChange={e=>setMultiLayout(e.target.value)}>
            <option value="cose">Cose</option><option value="ring">Ring</option>
          </select>}
          {sel && <select className="type-select" style={{width:'auto',marginTop:0,padding:'4px 8px'}} value={viewMode} onChange={e=>setViewMode(e.target.value)}>
            <option value="tables">Tables</option><option value="full">Full</option>
          </select>}
          {(multiView||sel) && <label className="btn btn-outline" style={{cursor:'pointer'}}>Filter<input ref={filterRef} type="file" accept=".csv,.txt" onChange={async e=>{
            const f=e.target.files?.[0];if(!f)return;
            const text=await f.text();
            D('🔍 Filter: multiView='+!!multiView+' sel='+!!sel+' mode='+(multiView&&!sel?'multi':'single')); if (multiView && !sel) {
              // Multi-script: filter by table/column names in CSV
              setLoading(true);
              const lines=text.split(/[\n]/).map(s=>s.trim()).filter(s=>s.length>0);
              const parseLine=l=>{const p=l.split(',');return{col:p[2]||'',tbl:p[0]||''};};
              const filters=lines.map(parseLine).filter(x=>x.col||x.tbl);
              const fTables=new Set(filters.map(x=>x.tbl).filter(Boolean));
              const fCols=new Set(filters.map(x=>x.col).filter(Boolean));
              setProg({s:`Filtering ${multiView.scripts.length} scripts...`,p:20});
              // Process in chunks with progress
              setTimeout(()=>{
                const matched=new Set();
                multiView.scripts.forEach((sc,i)=>{
                  if (i%10===0) setProg({s:`Filtering ${i+1}/${multiView.scripts.length}...`,p:20+60*i/multiView.scripts.length});
                  const nodes=sc.graph?.nodes||[];
                  for (const n of nodes) {
                    const d=n.data||{};
                    if (fTables.has(d.label)||fCols.has(d.label)||
                        (d.variable_type==='column'&&d.label&&fCols.has(d.label.split('.')[1]||''))) {
                      matched.add(sc.script_id); break;
                    }
                  }
                });
                // Save original, create filtered view
                if (!multiOriginal.current) multiOriginal.current = multiView;
                if (matched.size > 0) {
                  const fvId = 'fv_'+Date.now();
                  const orig = multiOriginal.current;
                  const fvNodes = orig.meta_nodes.filter(n => matched.has(n.data.id));
                  const nIds = new Set(fvNodes.map(n=>n.data.id));
                  const fvEdges = orig.meta_edges.filter(e => nIds.has(e.data.source) && nIds.has(e.data.target));
                  const fvName = '🔍 Filtered ('+matched.size+'/'+orig.scripts.length+')';
                  const fv = { id: fvId, name: fvName, meta_nodes: fvNodes, meta_edges: fvEdges,
                    scripts: orig.scripts.filter(s=>matched.has(s.script_id)) };
                  setFilteredViews(prev => prev.some(v=>v.id===fvId) ? prev : [...prev, fv]);
                  setMultiView(fv);
                }
                setFilterTables(matched.size>0?[...matched]:null);
                // Also store CSV table names for the overview banner
                setCsvName(f.name);setCsvContent(text);
                setProg({s:matched.size?`Matched ${matched.size}/${multiView.scripts.length} scripts`:'No matches',p:100});
                setTimeout(()=>setProg({s:'',p:0}),1500);
                setLoading(false);
              },50);
            } else if (sel) { D('🔍 Filter: single-script IO graph for '+sel.script_name);
              // Single-script: IO graph saved as sidebar tag
              setCsvName(f.name);setCsvContent(text);
              const fd=new FormData();fd.append('csv_file',f);
              setLoading(true);setProg({s:'Building IO graph...',p:50});
              try{
                const r=await fetch(`/api/scripts/${sel.script_id}/io_graph`,{method:'POST',body:fd});
                const d=await r.json();
                const ioName = '🔍 Filtered_'+sel.script_name;
                  setScripts(prev => {
                  const exists = prev.some(s=>s.script_id===sel.script_id+'_io');
                  if (exists) return prev.map(s=>s.script_id===sel.script_id+'_io'?{...s,ioGraph:d,ioPaths:d.paths||[]}:s);
                  const idx = prev.findIndex(x=>x.script_id===sel.script_id); const nxt = [...prev]; nxt.splice(idx>=0?idx+1:0,0,{script_id:sel.script_id+'_io',script_name:ioName,total_variables:d.input_count+d.output_count,total_dependencies:d.path_count,ioGraph:d,ioPaths:d.paths||[],analyzed_at:''}); return nxt;
                });
                setIoGraph(d);setIoPaths(d.paths||[]);
                setProg({s:'',p:0});
              }catch{setProg({s:'',p:0});}
              finally{setLoading(false);}
            }
            e.target.value='';
          }} hidden/></label>}
          {multiView && filterTables && <button className="btn btn-outline" onClick={()=>setFilterTables(null)} style={{color:'#2ECC71'}}>✕ Filter</button>}
          {sel && <button className="btn btn-outline" onClick={()=>setShowSQL(!showSQL)}>{showSQL?'Hide SQL':'Show SQL'}</button>}
          {(sel||multiView) && <button className="btn btn-outline" onClick={()=>exportCurrentView({multiView,gd,sel,multiOriginal,filteredViews})}>Export CSV</button>}
          <button className="btn btn-outline" onClick={()=>{if(cyR.current)cyR.current.fit(undefined,50)}}>Fit</button>
        </div>
      </header>
      {pshow&&<div className="progress-bar-wrap"><div className="progress-bar-fill" style={{width:`${prog.p}%`}}/><span className="progress-label">{prog.s}</span></div>}
      <div className="app-body">
        <aside className="sidebar">
          <h3>Scripts</h3>
          <div className="script-list">
            {multiView && <div key="multi_tag" className={`script-item ${!sel&&!ioGraph&&multiView===multiOriginal.current?'active':''}`} style={{borderColor:'#F39C12'}} onClick={()=>{if(multiOriginal.current){setMultiView(multiOriginal.current)};setSel(null);setMultiDetail(null);setPanel(null);setShowInfo(true);setIoGraph(null);setIoPaths([]);setGd(null)}}>
              <div className="script-name" style={{color:'#F39C12'}}>📊 Multi ({(multiOriginal.current||multiView).scripts.length} scripts)</div>
              <div className="script-meta">{(multiOriginal.current||multiView).meta_edges.filter(e=>e.data.edge_type==='data_lineage').length} lineage links</div>
            </div>}
            {filteredViews.map(fv => <div key={fv.id} className={`script-item ${!sel&&multiView===fv?'active':''}`} style={{borderColor:'#2ECC71'}} onClick={()=>{setMultiView(fv);setSel(null);setMultiDetail(null);setPanel(null);setShowInfo(true);setGd(null);}}>
              <div className="script-name" style={{color:'#2ECC71'}}>{fv.name}</div>
              <div className="script-meta">{fv.scripts.length} scripts</div>
            </div>)}
            {scripts.map(s=><div key={s.script_id} className={`script-item ${(sel?.script_id===s.script_id||(!sel&&ioGraph&&s.ioGraph===ioGraph))?'active':''}`} onClick={()=>{ if(s.ioGraph){ setIoGraph(s.ioGraph); setIoPaths(s.ioPaths||[]); setSel(null); setGd(null); setShowInfo(true); } else { setSel(s); setIoGraph(null); setIoPaths([]); } }}><div className="script-name" style={s.ioGraph?{paddingLeft:16,fontSize:'0.85rem'}:{}}>{s.script_name}</div><div className="script-meta">{s.total_variables}v · {s.total_dependencies}e</div></div>)}
            {!multiView&&scripts.length===0&&<div className="empty-state">Upload a SQL script to begin</div>}
            {scripts.length>0 && <div style={{padding:'4px 16px 8px'}}><button className="btn btn-outline" style={{width:'100%',fontSize:'0.7rem',padding:'4px'}} onClick={async()=>{await fetch('/api/scripts',{method:'DELETE'});api.listScripts().then(setScripts);}}>Clear All</button></div>}
          </div>
          {sel&&<div className="filter-panel"><h3>Filter Nodes</h3><input type="text" placeholder="Search..." value={sq} onChange={e=>setSq(e.target.value)} className="search-input"/><select value={tf} onChange={e=>setTf(e.target.value)} className="type-select">{VT.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}</select><h3 style={{marginTop:8}}>Filter Edges</h3><select value={ef} onChange={e=>setEf(e.target.value)} className="type-select">{ET.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}</select></div>}
          <div className="legend-panel"><h3>Nodes <span style={{fontSize:'0.6rem',color:'#666'}}>hover for info</span></h3><div className="legend-cat">── Script ──</div>{VT.filter(t=>['script'].includes(t.value)).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><LegendIcon type={t.value}/><span className="legend-label">{t.label}</span></span>)}<div className="legend-cat">── Tables ──</div>{VT.filter(t=>['table','view','virtual_table','cte','subquery','merge_target','union_branch'].includes(t.value)).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><LegendIcon type={t.value}/><span className="legend-label">{t.label}</span></span>)}<div className="legend-cat">── Columns ──</div>{VT.filter(t=>['column','cte_column'].includes(t.value)).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><LegendIcon type={t.value}/><span className="legend-label">{t.label}</span></span>)}<div className="legend-cat">── Computed ──</div>{VT.filter(t=>!['','script','table','view','virtual_table','cte','subquery','merge_target','union_branch','column','cte_column'].includes(t.value)).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><LegendIcon type={t.value}/><span className="legend-label">{t.label}</span></span>)}<h3 style={{marginTop:10}}>Edges</h3>{ET.filter(t=>t.value).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><span className="legend-color" style={{background:EC[t.value]||'#555',width:14,height:3,borderRadius:1,marginLeft:4}}/><span className="legend-label">{t.label}</span></span>)}</div>
        </aside>
        <main className="main-area">
          {multiView&&(()=>{
            const lineageEdges=multiView.meta_edges.filter(e=>e.data.edge_type==='data_lineage').length;
            const inputEdges=multiView.meta_edges.filter(e=>e.data.edge_type==='shared_input').length;
            const shown=filterTables?filterTables.length:multiView.scripts.length;
            return <div style={{position:'absolute',top:4,left:4,background:'#16213e',padding:'6px 10px',borderRadius:4,fontSize:'0.65rem',color:'#F39C12',zIndex:5,lineHeight:1.4}}>
              <b>{shown}/{multiView.scripts.length} scripts</b> | 🟢 {lineageEdges} lineage &nbsp; 🔵 {inputEdges} shared
              {filterTables && <span style={{color:'#2ECC71'}}> | 🔍 filtered</span>}<br/>
              <span style={{color:'#888',fontSize:'0.55rem'}}>Click a circle to open &nbsp;|&nbsp; 🟢=output→input &nbsp; 🔵=shared source</span>
            </div>;
          })()}
          {!sel&&!loading&&!multiView&&<div className="welcome"><h2>GPS SQL Data Flow Visualizer</h2><p>Upload SQL to see variables as an interactive graph.</p><p>Use <b>Multi</b> to compare scripts sharing variables.</p></div>}
          {loading&&<div className="loading-overlay">{prog.s||'Loading...'}</div>}
          <div ref={ctR} className="graph-container" style={{opacity:(sel||multiView||ioGraph)&&!loading?1:0,pointerEvents:(sel||multiView||ioGraph)&&!loading?'auto':'none'}}/>
          {ioGraph && <div style={{position:'absolute',top:4,left:4,background:'#16213e',padding:'8px 12px',borderRadius:4,fontSize:'0.7rem',color:'#2ECC71',zIndex:5,maxWidth:300}}><b>IO View</b> — {ioGraph.input_count} inputs, {ioGraph.output_count} outputs, {ioGraph.path_count} paths{csvContent && <pre style={{margin:'4px 0 0',fontSize:'0.6rem',color:'#aaa',maxHeight:120,overflow:'auto',whiteSpace:'pre'}}>{csvContent}</pre>}</div>}
        </main>
        {D('📋 PanelCheck: showInfo='+!!showInfo+' panel='+!!panel+' multiDetail='+!!multiDetail+' multiView='+!!multiView+' ioGraph='+!!ioGraph+' sel='+!!sel),(showInfo||panel||multiDetail||multiView)&&<aside className="detail-panel">
          <div className="detail-header">
            <h3>{multiDetail ? multiDetail.script_name : panel ? panel.title : ioGraph ? '📊 IO Graph' : multiView ? '📊 Multi-Script Overview' : 'Overview'}</h3>
            <div style={{display:'flex',gap:4}}>
              {multiDetail && <button onClick={()=>{setMultiDetail(null);setPanel(null)}} style={{background:'#F39C12',color:'#000',border:'none',borderRadius:3,padding:'2px 8px',cursor:'pointer',fontSize:'0.7rem',fontWeight:600}}>✕</button>}
              {!multiDetail && <button onClick={()=>{setPanel(null);setShowInfo(false)}} className="close-btn">✕</button>}
            </div>
          </div>
          <div className="detail-content">
            {/* IO graph view */}
            {ioGraph && !panel && <div className="detail-scroll">
              <div className="detail-section"><div className="ds-title">📊 IO Graph</div>
                <Row k="Inputs" v={ioGraph.input_count||0}/>
                <Row k="Outputs" v={ioGraph.output_count||0}/>
                <Row k="Paths" v={ioGraph.path_count||0}/>
                {(ioGraph.nodes||[]).length===0 && <div style={{fontSize:'0.8rem',color:'#F39C12',marginTop:8}}>⚠️ No matching data flow found for this filter.</div>}
                {csvContent && <div className="detail-section"><div className="ds-title">Filter CSV</div><pre style={{fontSize:'0.65rem',color:'#aaa',maxHeight:150,overflow:'auto',whiteSpace:'pre',background:'#0a0a1a',padding:6,borderRadius:3}}>{csvContent}</pre></div>}
              </div>
            </div>}
            {/* Multi-script detail */}
            {!ioGraph && multiDetail && !panel && <ScriptSummary sc={multiDetail} multiView={multiView} onDrill={()=>{}} />}
            {/* Multi overview */}
            {!ioGraph && multiView&&!panel&&!multiDetail&&!sel&&<MultiOverview mv={multiView} ft={filterTables} ftCsv={csvContent} ftName={csvName}/>}
            {/* Single-script overview */}
            {!ioGraph && !multiView&&!panel&&!multiDetail&&sel&&<div className="detail-scroll">
              <div className="detail-section"><div className="ds-title">Script</div><Row k="Name" v={sel.script_name}/><Row k="Variables" v={gd?.total_variables+' variables'}/><Row k="Edges" v={gd?.total_dependencies+' edges'}/></div>
              <div className="detail-section"><div className="ds-title">How to Explore</div><div style={{fontSize:'0.8rem',color:'#aaa',lineHeight:1.6}}>Click any <b>node</b> to see its variable details.<br/>Click any <b>edge</b> to see the data flow between variables.<br/>Use the <b>search</b> and <b>filter</b> to find specific variables.</div></div>
            </div>}
            {!ioGraph && !panel&&!multiDetail&&!sel&&!multiView&&<div className="detail-scroll"><div className="detail-section"><div className="ds-title">Welcome</div><div style={{fontSize:'0.8rem',color:'#aaa',lineHeight:1.6}}>Upload a SQL script to begin.<br/>The graph and details will appear here.</div></div></div>}
            {panel&&(panel.type==='node'?<NodePanel p={panel} vi={viR.current} lm={lmR.current} sql={sqlR.current} snip={snipR.current}/>:panel.type==='io_path'?<IOPathPanel p={panel}/>:panel.type==='script_meta'?<ScriptSummary sc={panel.script} multiView={multiView}/>:panel.type==='meta_edge'?<MetaEdgePanel p={panel} scripts={multiView?.scripts||[]}/>:<EdgePanel p={panel} vi={viR.current} lm={lmR.current} sql={sqlR.current} snip={snipR.current}/>)}
          </div>
        </aside>}
      </div>
      {tip.show && <div className="graph-tooltip" style={{left:tip.x,top:tip.y,whiteSpace:'pre-line',maxWidth:350}}>{tip.text}</div>}
      {showSQL && sqlR.current && (
        <div className="sql-panel">
          <div className="sql-panel-header">
            <span>SQL Source — {sel?.script_name||''}</span>
            <button onClick={()=>setShowSQL(false)} className="close-btn">X</button>
          </div>
          <pre className="sql-panel-body">{sqlR.current}</pre>
        </div>
      )}
    </div>
  );
}

// ── Node Detail Panel ──────────────────────────────────────────────────
function NodePanel({p,vi,lm,sql,snip}) {
  const n=p.node||{}; const ls=lm[n.id]||[0,0];
  const srcLines=sql?sql.split('\n').slice(Math.max(0,ls[0]-1),ls[1]).join('\n'):'';
  const upstream=p.edges.filter(e=>e.tid===p.id);
  const downstream=p.edges.filter(e=>e.sid===p.id);
  return (
    <div className="detail-scroll">
      <div className="detail-section"><div className="ds-title">Identity</div>
        <Row k="Name" v={n.label||''}/>
        <Row k="Type"><span className="type-badge" style={{background:C[n.variable_type]||'#999'}}>{n.variable_type}</span></Row>
        <Row k="ID" v={n.id} small/>
      </div>
      <div className="detail-section"><div className="ds-title">Location</div>
        <Row k="Defined In" v={n.defined_in||'(top level)'}/>
        <Row k="Lines" v={ls[0]?`${ls[0]}–${ls[1]}`:'N/A'}/>
        <Row k="Output Column" v={n.is_output?'Yes':'No'}/>
      </div>
      {n.sql_expression&&<div className="detail-section"><div className="ds-title">SQL Expression</div><pre className="sql-expr">{n.sql_expression}</pre></div>}
      {srcLines&&<div className="detail-section"><div className="ds-title">Source Lines {ls[0]}–{ls[1]}</div><pre className="sql-expr">{srcLines}</pre></div>}
      {(n.source_tables||[]).length>0&&<div className="detail-section"><div className="ds-title">Source Tables</div><div className="tag-list">{(n.source_tables||[]).map((t,i)=><span key={i} className="tag">{t}</span>)}</div></div>}
      {upstream.length>0&&<div className="detail-section"><div className="ds-title">Depends On ({upstream.length})</div>{upstream.map((e,i)=><div key={i} className="dep-row"><span className="dep-arrow" style={{color:EC[e.rel]||'#555'}}>↑</span><span style={{color:C[vi[e.sid]?.variable_type]||'#ccc'}}>{vi[e.sid]?.label||e.sid}</span><span className="dep-rel">[{e.rel}]</span></div>)}</div>}
      {downstream.length>0&&<div className="detail-section"><div className="ds-title">Used By ({downstream.length})</div>{downstream.map((e,i)=><div key={i} className="dep-row"><span className="dep-arrow" style={{color:EC[e.rel]||'#555'}}>↓</span><span style={{color:C[vi[e.tid]?.variable_type]||'#ccc'}}>{vi[e.tid]?.label||e.tid}</span><span className="dep-rel">[{e.rel}]</span></div>)}</div>}
      {!n.sql_expression&&!upstream.length&&!downstream.length&&<div className="ds-empty">No additional data available for this node.</div>}
      {snip?.node_snippets?.[p.id]&&<div className="detail-section"><div className="ds-title">Resolved SQL</div><pre className="sql-expr" style={{maxHeight:200}}>{snip.node_snippets[p.id]}</pre></div>}
    </div>
  );
}

// ── Edge Detail Panel ──────────────────────────────────────────────────
function EdgePanel({p,vi,lm,sql,snip}) {
  const s=p.src||{}, t=p.tgt||{}, e=p.edge||{};
  const sl=lm[p.sid]||[0,0], tl=lm[p.tid]||[0,0];
  const srcSQL=sql?sql.split('\n').slice(Math.max(0,sl[0]-1),sl[1]).join('\n'):'';
  const tgtSQL=sql?sql.split('\n').slice(Math.max(0,tl[0]-1),tl[1]).join('\n'):'';
  const ctxLines=[];
  if (sl[0]&&sql) for (let i=Math.max(0,sl[0]-1);i<=Math.min(tl[1]-1,sql.split('\n').length-1);i++) ctxLines.push(sql.split('\n')[i]);
  return (
    <div className="detail-scroll">
      <div className="detail-section"><div className="ds-title">Connection</div>
        <div style={{display:'flex',alignItems:'center',gap:8,padding:'8px 0'}}>
          <span className="type-badge" style={{background:C[s.variable_type]||'#999'}}>{s.label||p.sid}</span>
          <span style={{fontSize:'1.2rem',color:EC[e.relationship]||'#555'}}>→</span>
          <span className="type-badge" style={{background:C[t.variable_type]||'#999'}}>{t.label||p.tid}</span>
        </div>
        <Row k="Relationship"><span style={{color:EC[e.relationship]||'#888',fontWeight:600}}>{e.relationship}</span></Row>
        {e.operation&&<Row k="Operation" v={e.operation}/>}
        {e.sql_context&&<Row k="Context" v={e.sql_context} small/>}
      </div>
      <div className="detail-section"><div className="ds-title">Source — {s.label||p.sid}</div>
        <Row k="Type"><span className="type-badge" style={{background:C[s.variable_type]||'#999'}}>{s.variable_type}</span></Row>
        <Row k="Lines" v={sl[0]?`${sl[0]}–${sl[1]}`:'N/A'}/>
        {s.sql_expression&&<pre className="sql-expr">{s.sql_expression}</pre>}
        {srcSQL&&<pre className="sql-expr" style={{borderLeft:`3px solid ${EC[e.relationship]||'#555'}`}}>{srcSQL}</pre>}
      </div>
      <div className="detail-section"><div className="ds-title">Target — {t.label||p.tid}</div>
        <Row k="Type"><span className="type-badge" style={{background:C[t.variable_type]||'#999'}}>{t.variable_type}</span></Row>
        <Row k="Lines" v={tl[0]?`${tl[0]}–${tl[1]}`:'N/A'}/>
        {t.sql_expression&&<pre className="sql-expr">{t.sql_expression}</pre>}
        {tgtSQL&&<pre className="sql-expr" style={{borderLeft:`3px solid ${EC[e.relationship]||'#555'}`}}>{tgtSQL}</pre>}
      </div>
      {ctxLines.length>0&&<div className="detail-section"><div className="ds-title">Connecting SQL (lines {sl[0]}–{tl[1]})</div><pre className="sql-expr">{ctxLines.join('\n')}</pre></div>}
      {snip?.edge_snippets?.[`${p.sid}->${p.tid}`]&&<div className="detail-section"><div className="ds-title">Resolved SQL Segment</div><pre className="sql-expr">{snip.edge_snippets[`${p.sid}->${p.tid}`]}</pre></div>}
    </div>
  );
}

function IOPathPanel({p}) {
  const pi = p.pathInfo;
  if (!pi) return <div className="ds-empty">No path info available for this edge.</div>;
  return (
    <div className="detail-scroll">
      <div className="detail-section"><div className="ds-title">Path: {pi.input.name} → {pi.output.name}</div>
        <Row k="Length" v={`${pi.length} steps`}/>
        <Row k="Input Column" v={pi.input.name}/>
        <Row k="Output Column" v={pi.output.name}/>
      </div>
      <div className="detail-section"><div className="ds-title">Path Nodes ({pi.nodes.length})</div>
        {pi.nodes.map((n,i) => (
          <div key={i} style={{padding:'3px 0',fontSize:'0.75rem',display:'flex',alignItems:'center',gap:4}}>
            <span style={{color:'#888',width:20}}>{i+1}.</span>
            <span style={{color:'#ccc'}}>{n.name}</span>
            {n.table && <span style={{color:'#666',fontSize:'0.65rem'}}>({n.table})</span>}
            <span className="type-badge" style={{background:'#555',fontSize:'0.6rem',padding:'1px 4px'}}>{n.type}</span>
          </div>
        ))}
      </div>
      {pi.edges.length>0 && <div className="detail-section"><div className="ds-title">Path Edges ({pi.edges.length})</div>
        {pi.edges.map((e,i) => (
          <div key={i} className="dep-item" style={{padding:4,background:'#0a1a2e',borderRadius:4,marginBottom:3}}>
            <span style={{color:'#888',fontSize:'0.65rem'}}>{e.relationship}</span>
          </div>
        ))}
      </div>}
    </div>
  );
}

const NODE_SHAPES={script:'roundrect',table:'rect',view:'rect',column:'ellipse',cte:'roundrect',cte_column:'tri',expression:'diamond',window:'hex',aggregate:'tri',case:'pentagon',transform:'rhomboid',literal:'ellipse',merge_target:'rect',union_branch:'vee',subquery:'diamond',virtual_table:'roundrect'};
function LegendIcon({type}) {
  const s=NODE_SHAPES[type]||'ellipse';const c=C[type]||'#999';const sz=10;
  if(s==='rect') return <svg width={sz+4} height={sz}><rect x={2} y={0} width={sz} height={sz} fill={c} rx={1}/></svg>;
  if(s==='roundrect') return <svg width={sz+4} height={sz}><rect x={2} y={0} width={sz} height={sz} fill={c} rx={3}/></svg>;
  if(s==='diamond') return <svg width={sz+2} height={sz+2}><polygon points={`${(sz+2)/2},0 ${sz+2},${(sz+2)/2} ${(sz+2)/2},${sz+2} 0,${(sz+2)/2}`} fill={c}/></svg>;
  if(s==='tri') return <svg width={sz} height={sz}><polygon points={`${sz/2},0 ${sz},${sz} 0,${sz}`} fill={c}/></svg>;
  if(s==='hex') return <svg width={sz+2} height={sz+2}><polygon points={`${(sz+2)*0.25},0 ${(sz+2)*0.75},0 ${sz+2},${(sz+2)/2} ${(sz+2)*0.75},${sz+2} ${(sz+2)*0.25},${sz+2} 0,${(sz+2)/2}`} fill={c}/></svg>;
  if(s==='pentagon') return <svg width={sz+2} height={sz+2}><polygon points={`${(sz+2)/2},0 ${sz+2},${(sz+2)*0.4} ${(sz+2)*0.8},${sz+2} ${(sz+2)*0.2},${sz+2} 0,${(sz+2)*0.4}`} fill={c}/></svg>;
  if(s==='rhomboid') return <svg width={sz+4} height={sz}><polygon points={`3,0 ${sz+4},0 ${sz+1},${sz} 0,${sz}`} fill={c}/></svg>;
  if(s==='vee') return <svg width={sz} height={sz}><polygon points={`${sz/2},0 ${sz},${sz} 0,${sz}`} fill={c} opacity={0.5}/></svg>;
  return <svg width={sz+2} height={sz+2}><ellipse cx={(sz+2)/2} cy={(sz+2)/2} rx={(sz+2)/2} ry={(sz+2)/2} fill={c}/></svg>;
}

function Row({k,v,small,children}) {
  if (!v && !children) return null;
  return <div className="var-field"><span className="field-label">{k}</span>{children||<span className="field-value" style={small?{fontSize:'0.7rem',color:'#888'}:{}}>{v}</span>}</div>;
}

// ── Script Summary (shown in panel when script circle is tapped) ───────────
// ── Multi-Script Overview Panel ────────────────────────────────────────
function MultiOverview({mv, ft, ftCsv, ftName}) {
  const total = mv?.scripts?.length||0;
  const shown = ft ? ft.length : total;
  const lineage = (mv?.meta_edges||[]).filter(e=>e.data.edge_type==='data_lineage').length;
  const shared = (mv?.meta_edges||[]).filter(e=>e.data.edge_type==='shared_input').length;
  const ftNames = ftCsv ? ftCsv.split(/[\n]/).map(s=>s.trim()).filter(s=>s.length>0).map(l=>{const p=l.split(',');return p[2]||p[0]||'';}).filter(Boolean) : [];
  return <div className="detail-scroll">
    <div className="detail-section">
      <div className="ds-title">📊 Multi-Script Analysis</div>
      <Row k="Scripts" v={shown+'/'+total+(ft?' filtered':'')}/>
      <Row k="Data lineage" v={lineage+' edges'}/>
      <Row k="Shared inputs" v={shared+' edges'}/>
      {ft && <Row k="Filter"><span style={{color:'#2ECC71'}}>{ftNames.join(', ')||ftName||'active'}</span></Row>}
    </div>
    {mv?.scripts?.map(s=>{
      const match = !ft || ft.some(id=>s.script_id===id);
      if (ft && !match) return null;
      return <div key={s.script_id} className="detail-section">
        <div className="ds-title" style={{color:'#F39C12'}}>{s.script_name}</div>
        <Row k="Vars" v={s.total_variables+'v '+s.total_dependencies+'e'}/>
        <Row k="📥 In"><span style={{color:'#4A90D9',fontSize:'0.7rem'}}>{(s.input_tables||[]).join(', ')||'(none)'}</span></Row>
        <Row k="📤 Out"><span style={{color:'#2ECC71',fontSize:'0.7rem'}}>{(s.output_tables||[]).join(', ')||'(none)'}</span></Row>
      </div>;
    })}
    <div className="detail-section" style={{fontSize:'0.65rem',color:'#666',textAlign:'center'}}>
      Click a script node for detail &nbsp;|&nbsp; Double-click to open
    </div>
  </div>;
}

function ScriptSummary({sc, multiView, onDrill}) {
  const allScripts = multiView?.scripts||[];
  return (
    <div className="detail-scroll">
      <div className="detail-section">
        <div className="ds-title">{sc.script_name}</div>
        <Row k="Variables" v={sc.total_variables+'v · '+sc.total_dependencies+'e'}/>
      </div>
      <div className="detail-section">
        <div className="ds-title">📥 Input Tables ({sc.input_tables?.length||0})</div>
        {sc.input_tables?.length ? sc.input_tables.map((t,i)=>{
          // Find other scripts that also use this table
          const alsoIn = allScripts.filter(s=>s.script_id!==sc.script_id&&(s.input_tables||[]).includes(t));
          const alsoOut = allScripts.filter(s=>s.script_id!==sc.script_id&&(s.output_tables||[]).includes(t));
          return <div key={i} style={{marginBottom:6}}>
            <span className="tag" style={{background:'#4A90D9',marginRight:4}}>{t}</span>
            {alsoOut.length>0 && <span style={{fontSize:'0.65rem',color:'#2ECC71'}}>← {alsoOut.map(s=>s.script_name).join(', ')}</span>}
            {alsoIn.length>0 && <span style={{fontSize:'0.65rem',color:'#888',marginLeft:4}}>also in: {alsoIn.map(s=>s.script_name).join(', ')}</span>}
          </div>;
        }) : <div style={{fontSize:'0.75rem',color:'#888'}}>(none)</div>}
      </div>
      <div className="detail-section">
        <div className="ds-title">📤 Output Tables ({sc.output_tables?.length||0})</div>
        {sc.output_tables?.length ? sc.output_tables.map((t,i)=>{
          const consumers = allScripts.filter(s=>s.script_id!==sc.script_id&&(s.input_tables||[]).includes(t));
          return <div key={i} style={{marginBottom:4}}>
            <span className="tag" style={{background:'#2ECC71',color:'#000',marginRight:4}}>{t}</span>
            {consumers.length>0 && <span style={{fontSize:'0.65rem',color:'#4A90D9'}}>→ {consumers.map(s=>s.script_name).join(', ')}</span>}
          </div>;
        }) : <div style={{fontSize:'0.75rem',color:'#888'}}>(read-only)</div>}
      </div>
      <div className="detail-section" style={{fontSize:'0.65rem',color:'#666',textAlign:'center'}}>
        Double-click to open full graph
      </div>
    </div>
  );
}

// ── Meta Edge Panel (multi-script edge detail) ────────────────────────────
function MetaEdgePanel({p, scripts}) {
  const e = p.edge || {};
  const srcScript = scripts.find(s=>s.script_id===e.source);
  const tgtScript = scripts.find(s=>s.script_id===e.target);
  const descs = {
    data_lineage: 'Data flows FROM the first script\'s output INTO the second script\'s input via this table.',
    shared_input: 'Both scripts read from the same source table.',
    shared_var: 'Both scripts reference the same variable name.',
  };
  return (
    <div className="detail-scroll">
      <div className="detail-section">
        <div className="ds-title">Connection Type</div>
        <span className="type-badge" style={{background:e.edge_type==='data_lineage'?'#2ECC71':e.edge_type==='shared_input'?'#3498DB':'#7F8C8D',color:'#000',fontSize:'0.8rem'}}>
          {e.edge_type==='data_lineage'?'📤→📥 Data Lineage':e.edge_type==='shared_input'?'📥 Shared Input':'🔗 Shared Variable'}
        </span>
        <div style={{fontSize:'0.75rem',color:'#aaa',marginTop:4}}>{descs[e.edge_type]||''}</div>
      </div>
      {e.label && <div className="detail-section">
        <div className="ds-title">Table / Variable</div>
        <Row k="Name" v={e.label}/>
      </div>}
      <div className="detail-section">
        <div className="ds-title">Scripts</div>
        <Row k="Source">{srcScript ? <span style={{color:'#F39C12'}}>{srcScript.script_name}</span> : e.source}</Row>
        <Row k="Target">{tgtScript ? <span style={{color:'#F39C12'}}>{tgtScript.script_name}</span> : e.target}</Row>
      </div>
    </div>
  );
}
