import React, { useState, useEffect, useRef, useCallback } from 'react';
import cytoscape from 'cytoscape';
import * as api from './api/client';
import { NODE_STYLES, LAYOUT_OPTIONS } from './utils/graphStyles';

const C = {
  database_table:'#4A90D9',table_column:'#A8D4FF',cte_table:'#5CB85C',
  cte_column:'#8FD98F',intermediate:'#F0AD4E',window_result:'#967ADC',
  aggregate:'#37BC9B',case_result:'#D770AD',function_result:'#FFCE54',
  literal:'#CCCCCC',merge_target:'#DA4453',union_branch:'#E6E9ED',subquery_result:'#AC92EC',
  virtual_table:'#2ECC71',
};
const EC = {BELONGS_TO:'#8AB4F8',ALIAS_OF:'#1ABC9C',FEEDS_INTO:'#2ECC71',DIRECT_REFERENCE:'#9AA0A6',AGGREGATION:'#37BC9B',TRANSFORMATION:'#F0AD4E',WINDOW:'#967ADC',COMPUTED_FROM:'#D770AD',REFERENCES:'#5DADE2',OPERATES_ON:'#E74C3C',COMPONENT_LINK:'#E67E22'};

const VT = [{value:'',label:'All Types'},{value:'database_table',label:'Table',desc:'Physical table or alias'},{value:'cte_table',label:'CTE',desc:'Temporary result set (WITH ... AS)'},{value:'virtual_table',label:'Output',desc:'Result of a SELECT statement'},{value:'merge_target',label:'Merge',desc:'Target table in MERGE INTO'},{value:'union_branch',label:'Union',desc:'One arm of UNION ALL'},{value:'table_column',label:'Column',desc:'A column read from a table'},{value:'cte_column',label:'CTE Col',desc:'Column inside a CTE definition'},{value:'aggregate',label:'Aggregate',desc:'SUM, COUNT, AVG, MIN, MAX'},{value:'window_result',label:'Window',desc:'ROW_NUMBER, RANK, LAG, SUM OVER'},{value:'case_result',label:'If-Then',desc:'CASE WHEN ... THEN ... END'},{value:'function_result',label:'Function',desc:'COALESCE, CAST, CONCAT result'},{value:'intermediate',label:'Computed',desc:'Expression like (a+b) AS total'},{value:'subquery_result',label:'Subquery',desc:'Scalar subquery result'},{value:'literal',label:'Constant',desc:'String or number literal'}];
const ET = [{value:'',label:'All Edges'},{value:'BELONGS_TO',label:'Owns',desc:'Table owns this column'},{value:'ALIAS_OF',label:'Alias',desc:'Alias → original table name'},{value:'FEEDS_INTO',label:'Input',desc:'Table feeds into SELECT output'},{value:'DIRECT_REFERENCE',label:'Ref',desc:'Direct column reference'},{value:'AGGREGATION',label:'Agg',desc:'Column → SUM/COUNT/AVG'},{value:'TRANSFORMATION',label:'Xform',desc:'Column → function result'},{value:'WINDOW',label:'Window',desc:'Column → window function'},{value:'COMPUTED_FROM',label:'Compute',desc:'Column → CASE expression'},{value:'REFERENCES',label:'NameRef',desc:'HAVING ref → SELECT definition'},{value:'OPERATES_ON',label:'DML',desc:'Column → INSERT/UPDATE/DELETE'},{value:'COMPONENT_LINK',label:'Bridge',desc:'Cross-scope connection'}];

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
  const [viewMode, setViewMode] = useState('full'); // 'full' | 'compact' | 'tables'
  const [multiView, setMultiView] = useState(null);  // multi-script meta-graph
  const multiRef = useRef(null);
  const [multiDetail, setMultiDetail] = useState(null); // selected sub-script detail

  useEffect(() => { api.listScripts().then(setScripts).catch(()=>{}); fetch('/api/health').then(r=>r.json()).then(d=>setVersion(d.version)).catch(()=>{}); }, []);

  const load = useCallback(async (s) => {
    if (!s) return;
    setLoading(true); setProg({s:'Loading...',p:10});
    try {
      const d = await api.getGraph(s.script_id, true);
      setGd(d); setProg({s:'',p:0});
      const vi={}; d.nodes.forEach(n=>{vi[n.data.id]=n.data;}); viR.current=vi;
      snipR.current = (d.snippets||{});
      const di={}; d.edges.forEach(e=>{di[`${e.data.source}→${e.data.target}`]=e.data;}); diR.current=di;
      sqlR.current = d.sql_text||''; lmR.current = d.line_map||{};
    } catch { setProg({s:'Failed',p:0}); }
    finally { setLoading(false); }
  }, []);
  useEffect(()=>{if(sel)load(sel);},[sel,load]);

  useEffect(() => {
    // Multi-script view: render meta-graph or detail
    let data = ioGraph || gd;
    if (multiView && !multiDetail) {
      data = {nodes: multiView.meta_nodes, edges: multiView.meta_edges};
    } else if (multiDetail) {
      data = multiDetail.graph;  // full graph of selected sub-script
    }
    if (!data || !ctR.current) return;
    if (cyR.current) cyR.current.destroy();

    const renderNodes = data.nodes.map(n => ({...n, data: {...n.data}}));
    const renderEdges = [...data.edges];

    // Compact mode: hide column children, show only parent tables + non-column nodes
    if (viewMode === 'compact') {
      for (const n of renderNodes) {
        if (n.data.parent || n.data.variable_type === 'table_column') {
          n.classes = 'hidden-node';
        }
      }
    } else if (viewMode === 'tables') {
      // Hide everything except table/CTE/VT nodes
      for (const n of renderNodes) {
        if (n.data.variable_type !== 'database_table' && n.data.variable_type !== 'cte_table' && n.data.variable_type !== 'virtual_table') {
          n.classes = 'hidden-node';
        }
      }
    }

    const cy = cytoscape({
      container: ctR.current,
      elements: [...renderNodes, ...renderEdges],
      style: [...NODE_STYLES, {selector:'.hidden-node',style:{'display':'none'}}],
      layout: {name:'cose',...LAYOUT_OPTIONS},
      wheelSensitivity: 0.3,
      // Performance settings for large graphs
      pixelRatio: viewMode==='tables'?1:1.5,
      textureOnViewport: true,
      hideEdgesOnViewport: viewMode==='full',
      hideLabelsOnViewport: viewMode==='full',
    });
    cy.on('mouseover','node',e=>{e.target.closedNeighborhood().removeClass('dimmed');cy.elements().not(e.target.closedNeighborhood()).addClass('dimmed');const vt=e.target.data('variable_type');if(vt){const d=tipDesc[vt]||vt;setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,text:d});}});
    cy.on('mousemove','node',e=>{if(tip.show)setTip(t=>({...t,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10}));});
    cy.on('mouseout','node',()=>{cy.elements().removeClass('dimmed');setTip({show:false,x:0,y:0,text:''});});
    cy.on('tap','node',e=>{
      const id=e.target.id(); const eds=(data?.edges||[]).filter(x=>x.data.source===id||x.data.target===id);
      const vi=ioGraph?{}:viR.current;
      setPanel({type:'node',id,node:vi[id]||{label:id},edges:eds.map(x=>({sid:x.data.source,tid:x.data.target,rel:x.data.relationship})),title:vi[id]?.label||id});
    });
    cy.on('mouseover','edge',e=>{const r=e.target.data('relationship');if(r){const d=edgeDesc[r]||r;setTip({show:true,x:e.originalEvent.clientX+10,y:e.originalEvent.clientY-10,text:d});}});
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
    // Meta-graph: click a script node to see its detail in side panel
    if (multiView && !multiDetail) {
      cy.on('tap','node',async e=>{
        const sid=e.target.id(); const sc=multiView.scripts.find(s=>s.script_id===sid);
        if(sc){ setLoading(true); try{ const g=await api.getGraph(sid,true); setMultiDetail({...sc,graph:g}); }catch{} finally{setLoading(false);} }
      });
      // Double-click to open full view
      cy.on('dbltap','node',e=>{
        const sid=e.target.id(); const sc=multiView.scripts.find(s=>s.script_id===sid);
        if(sc && multiDetail) setMultiDetail(null);  // toggle off
      });
    }
    cyR.current=cy;
    return ()=>{cy.destroy();};
  },[gd,ioGraph,ioPaths,viewMode,multiView,multiDetail]);

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

  const pshow = prog.s && loading;
  return (
    <div className="app-container">
      <header className="app-header">
        <h1>GPS SQL Data Flow Visualizer {version && <span style={{fontSize:'0.6rem',color:'#666',fontWeight:400}}>v{version}</span>}</h1>
        <div className="header-actions">
          <label className="btn btn-primary" style={{cursor:'pointer'}}>Upload SQL<input ref={flR} type="file" accept=".sql,.txt" onChange={upload} hidden/></label>
          <button className="btn btn-secondary" onClick={paste}>Paste SQL</button>
          <button className="btn btn-outline" onClick={()=>{if(cyR.current)cyR.current.fit(undefined,50)}}>Fit</button>
          <label className="btn btn-outline" style={{cursor:'pointer'}}>Multi<input ref={multiRef} type="file" accept=".sql,.txt" multiple onChange={async e=>{
            const fs=[...e.target.files]; if(fs.length<2) return;
            setLoading(true); setProg({s:'Analyzing scripts...',p:30});
            try{
              const fd=new FormData(); fs.forEach(f=>fd.append('files',f));
              const r=await fetch('/api/analyze_multi',{method:'POST',body:fd});
              const d=await r.json(); setMultiView(d); setMultiDetail(null);
              setProg({s:'',p:0});
            }catch{setProg({s:'',p:0});}
            finally{setLoading(false);}
            e.target.value='';
          }} hidden/></label>
          {sel && <button className="btn btn-outline" onClick={()=>setShowSQL(!showSQL)}>{showSQL?'Hide SQL':'Show SQL'}</button>}
          {sel && <select className="type-select" style={{width:'auto',marginTop:0,padding:'4px 8px'}} value={viewMode} onChange={e=>setViewMode(e.target.value)}>
            <option value="full">Full</option><option value="compact">Compact</option><option value="tables">Tables</option>
          </select>}
          {sel && <label className="btn btn-outline" style={{cursor:'pointer'}}>IO Graph<input ref={ioRef} type="file" accept=".csv" onChange={async e=>{
            const f=e.target.files?.[0];if(!f)return;
            setCsvName(f.name);setCsvContent(await f.text());
            setIoGraph(null);setIoPaths([]); // clear old graph before loading new
            const fd=new FormData();fd.append('csv_file',f);
            setLoading(true);setProg({s:'Building IO graph...',p:50});
            try{
              const r=await fetch(`/api/scripts/${sel.script_id}/io_graph`,{method:'POST',body:fd});
              const d=await r.json();setIoGraph(d);setIoPaths(d.paths||[]);
              setProg({s:'',p:0});
            }catch{setProg({s:'',p:0});}
            finally{setLoading(false);}
            e.target.value=''; // reset so same file can be re-selected
          }} hidden/></label>}
          {multiView && <button className="btn btn-outline" onClick={()=>setMultiDetail(null)}>Overview</button>}
          {multiView && <button className="btn btn-outline" onClick={()=>{setMultiView(null);setMultiDetail(null)}}>Exit Multi</button>}
          {ioGraph && <button className="btn btn-outline" onClick={()=>{setIoGraph(null);setIoPaths([]);setCsvName('');setCsvContent('')}}>Exit IO View</button>}
        </div>
      </header>
      {pshow&&<div className="progress-bar-wrap"><div className="progress-bar-fill" style={{width:`${prog.p}%`}}/><span className="progress-label">{prog.s}</span></div>}
      <div className="app-body">
        <aside className="sidebar">
          <h3>Scripts</h3>
          <div className="script-list">
            {scripts.map(s=><div key={s.script_id} className={`script-item ${sel?.script_id===s.script_id?'active':''}`} onClick={()=>setSel(s)}><div className="script-name">{s.script_name}</div><div className="script-meta">{s.total_variables}v · {s.total_dependencies}e</div></div>)}
            {scripts.length===0&&<div className="empty-state">Upload a SQL script to begin</div>}
          </div>
          {sel&&<div className="filter-panel"><h3>Filter Nodes</h3><input type="text" placeholder="Search..." value={sq} onChange={e=>setSq(e.target.value)} className="search-input"/><select value={tf} onChange={e=>setTf(e.target.value)} className="type-select">{VT.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}</select><h3 style={{marginTop:8}}>Filter Edges</h3><select value={ef} onChange={e=>setEf(e.target.value)} className="type-select">{ET.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}</select></div>}
          <div className="legend-panel"><h3>Nodes <span style={{fontSize:'0.6rem',color:'#666'}}>hover for info</span></h3>{VT.filter(t=>t.value).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><LegendIcon type={t.value}/><span className="legend-label">{t.label}</span></span>)}<h3 style={{marginTop:10}}>Edges</h3>{ET.filter(t=>t.value).map(t=><span key={t.value} className="legend-item" onMouseEnter={e=>setTip({show:true,x:e.clientX+10,y:e.clientY-10,text:t.desc||t.label})} onMouseLeave={()=>setTip({show:false,x:0,y:0,text:''})}><span className="legend-color" style={{background:EC[t.value]||'#555',width:14,height:3,borderRadius:1,marginLeft:4}}/><span className="legend-label">{t.label}</span></span>)}</div>
        </aside>
        <main className="main-area">
          {multiView&&!multiDetail&&<div style={{position:'absolute',top:4,left:4,background:'#16213e',padding:'6px 12px',borderRadius:4,fontSize:'0.7rem',color:'#F39C12',zIndex:5}}>Overview — {multiView.scripts.length} scripts, {Object.keys(multiView.shared_vars).length} shared vars</div>}
          {!sel&&!loading&&!multiView&&<div className="welcome"><h2>GPS SQL Data Flow Visualizer</h2><p>Upload SQL to see variables as an interactive graph.</p><p>Use <b>Multi</b> to compare scripts sharing variables.</p></div>}
          {multiView&&multiDetail&&<div style={{position:'absolute',top:4,left:4,background:'#16213e',padding:'6px 12px',borderRadius:4,fontSize:'0.7rem',color:'#4A90D9',zIndex:5}}>Detail — {multiDetail.script_name} ({multiDetail.total_variables}v {multiDetail.total_dependencies}e)</div>}
          {loading&&<div className="loading-overlay">{prog.s||'Loading...'}</div>}
          <div ref={ctR} className="graph-container" style={{display:(sel&&(gd||ioGraph)&&!loading)?'block':'none'}}/>
          {ioGraph && <div style={{position:'absolute',top:4,left:4,background:'#16213e',padding:'8px 12px',borderRadius:4,fontSize:'0.7rem',color:'#2ECC71',zIndex:5,maxWidth:300}}><b>IO View</b> — {ioGraph.input_count} inputs, {ioGraph.output_count} outputs, {ioGraph.path_count} paths{csvContent && <pre style={{margin:'4px 0 0',fontSize:'0.6rem',color:'#aaa',maxHeight:120,overflow:'auto',whiteSpace:'pre'}}>{csvContent}</pre>}</div>}
        </main>
        <aside className="detail-panel">
          <div className="detail-header"><h3>{panel?panel.title:'Overview'}</h3>{panel&&<button onClick={()=>setPanel(null)} className="close-btn">X</button>}</div>
          <div className="detail-content">
            {!panel&&sel&&<div className="detail-scroll">
              <div className="detail-section"><div className="ds-title">Script</div><Row k="Name" v={sel.script_name}/><Row k="Variables" v={gd?.total_variables+' variables'}/><Row k="Edges" v={gd?.total_dependencies+' edges'}/></div>
              <div className="detail-section"><div className="ds-title">How to Explore</div><div style={{fontSize:'0.8rem',color:'#aaa',lineHeight:1.6}}>Click any <b>node</b> to see its variable details.<br/>Click any <b>edge</b> to see the data flow between variables.<br/>Use the <b>search</b> and <b>filter</b> to find specific variables.</div></div>
            </div>}
            {!panel&&!sel&&<div className="detail-scroll"><div className="detail-section"><div className="ds-title">Welcome</div><div style={{fontSize:'0.8rem',color:'#aaa',lineHeight:1.6}}>Upload a SQL script to begin.<br/>The graph and details will appear here.</div></div></div>}
            {panel&&(panel.type==='node'?<NodePanel p={panel} vi={viR.current} lm={lmR.current} sql={sqlR.current} snip={snipR.current}/>:panel.type==='io_path'?<IOPathPanel p={panel}/>:<EdgePanel p={panel} vi={viR.current} lm={lmR.current} sql={sqlR.current} snip={snipR.current}/>)}
          </div>
        </aside>
      </div>
      {tip.show && <div className="graph-tooltip" style={{left:tip.x,top:tip.y}}>{tip.text}</div>}
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

const NODE_SHAPES={database_table:'rect',table_column:'ellipse',cte_table:'roundrect',cte_column:'tri',intermediate:'diamond',window_result:'hex',aggregate:'tri',case_result:'pentagon',function_result:'rhomboid',literal:'ellipse',merge_target:'rect',union_branch:'vee',subquery_result:'diamond',virtual_table:'roundrect'};
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
