// ── Global state ──────────────────────────────────────────────────────────────
let SIM=null, tables={}, runCfg={};
let step=0, playing=false, timer=null, spdIdx=0;
const SPDS=[1,2,4,8];
let prevSpot=null, curTable=null;

const $=id=>document.getElementById(id);
function toast(m,d=2400){const e=$('toast');e.textContent=m;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),d)}

// ── Derived maps from config tables ──────────────────────────────────────────
// These are recalculated from tables each time they're needed — if you edit
// viz_companies in the Config tab and re-run, the new colours take effect.
function companyColors(){return Object.fromEntries((tables.viz_companies||[]).map(r=>[r.name,r.color]))}
function groupRadius(){return Object.fromEntries((tables.viz_ship_groups||[]).map(r=>[r.group,+r.map_radius]))}
function uiSettings(){return Object.fromEntries((tables.portal_settings||[]).map(r=>[r.key,r.value]))}

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('panel-'+t.dataset.tab).classList.add('active');
  if(t.dataset.tab==='dash'&&SIM) buildDashboard();
  if(t.dataset.tab==='export'&&SIM) buildExportSummary();
  if(t.dataset.tab==='settings') renderSettings();
}));

// ── Init ──────────────────────────────────────────────────────────────────────
async function init(){
  try{
    tables=await fetch('/api/tables').then(r=>r.json());
    runCfg=buildRunCfg();
    buildConfigNav();
    buildObjectsNav();
    buildScenarioParams();
    buildLegend();
    initMap();
    const st=await fetch('/api/status').then(r=>r.json());
    if(st.has_result){SIM=await fetch('/api/result').then(r=>r.json());onSimLoaded();}
    toast('Ready — press INIT to build simulation frames');
  }catch(e){toast('Server error: '+e.message,5000);console.error(e);}
}

function buildRunCfg(){
  const cfg={};
  (tables.portal_params||[]).forEach(p=>{
    if(!p.key)return;
    const raw=String(p.default_val??'');
    if(p.param_type==='number')cfg[p.key]=raw.includes('.')?parseFloat(raw):parseInt(raw);
    else if(p.param_type==='bool')cfg[p.key]=raw.toLowerCase()==='true';
    else cfg[p.key]=raw;
  });
  return cfg;
}

// ── Run ───────────────────────────────────────────────────────────────────────
async function startRun(){
  const btn=$('run-btn');btn.disabled=true;
  $('run-prog').style.display='block';$('run-txt').textContent='starting…';
  await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:runCfg})});
  const poll=setInterval(async()=>{
    const st=await fetch('/api/status').then(r=>r.json());
    $('run-prog-bar').style.width=st.progress+'%';
    $('run-txt').textContent=st.running?`running ${st.progress}%`:st.error?'error':'done';
    if(!st.running){
      clearInterval(poll);btn.disabled=false;$('run-prog').style.display='none';
      if(st.error){toast('Sim error — see console',5000);console.error(st.error);return;}
      SIM=await fetch('/api/result').then(r=>r.json());
      onSimLoaded();toast(`✓ Done — ${SIM.steps.length} steps`);
    }
  },400);
}

function onSimLoaded(){
  $('scrubber').max=SIM.steps.length-1;
  initMapLayers();render(0);
  const s=uiSettings();
  // autoplay disabled — use Play button
  if(document.querySelector('#panel-dash.active'))buildDashboard();
}

// ── Leaflet map ───────────────────────────────────────────────────────────────
let lmap,vlayer,rmarks={},nmarks={},vmarks={};

function initMap(){
  if(lmap)return;
  const s=uiSettings();
  lmap=L.map('map',{center:[+(s.map_center_lat||20),+(s.map_center_lon||20)],
    zoom:+(s.map_zoom||2),zoomControl:true,attributionControl:false,minZoom:2,maxZoom:6,
    worldCopyJump:true});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:6}).addTo(lmap);
  vlayer=L.layerGroup().addTo(lmap);
}

function initMapLayers(){
  if(!SIM||!lmap)return;
  Object.values(rmarks).forEach(m=>lmap.removeLayer(m));rmarks={};
  Object.values(nmarks).forEach(m=>lmap.removeLayer(m));nmarks={};
  vlayer.clearLayers();vmarks={};
  const s=uiSettings();
  // Routes (from SIM.routes — assembled server-side from viz_routes table)
  if(s.show_route_lines!=='false'){
    const op=parseFloat(s.route_opacity||0.08);
    Object.values(SIM.routes).forEach(rt=>
      L.polyline(rt.waypoints,{color:'#00e5ff',opacity:op,weight:1.5,dashArray:'4 6'}).addTo(lmap));
  }
  // Node pins (config from viz_nodes table via SIM.nodes)
  if(s.show_node_pins!=='false')
    Object.entries(SIM.nodes).forEach(([name,c])=>{
      const gateLbl = (c.is_gateway?'⬦ ':'◦ ') + (c.label||name);
      nmarks[name]=L.marker([c.lat,c.lon],{icon:nodeIcon(c,true)})
        .bindTooltip(gateLbl,{className:'leaflet-tooltip',sticky:false})
        .addTo(lmap);
    });
  // Region pins: hover for tooltip, click to pin popup panel
  if(s.show_region_pins!=='false')
    Object.entries(SIM.regions).forEach(([name,c])=>{
      const m=L.marker([c.lat,c.lon],{icon:regionIcon(name,SIM.steps[0],c)}).addTo(lmap);
      m.on('mouseover',e=>showHoverTip(name,e,c));
      m.on('mouseout',()=>{$('rpop').style.display='none'});
      m.on('click',e=>pinRegionPanel(name,c));
      rmarks[name]=m;
    });
}

function nodeIcon(c,open){
  const col=open?(c.color_open||'#ffd23f'):(c.color_closed||'#ff3860');
  const isGate=c.is_gateway||c.icon_shape==='diamond';
  if(isGate){
    // Diamond shape for gateways — rotate a square 45deg
    const sz=open?14:12; const shadow=open?`0 0 10px ${col}99`:`0 0 6px ${col}`;
    return L.divIcon({className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2],
      html:`<div style="width:${sz}px;height:${sz}px;transform:rotate(45deg);border:2px solid ${col};background:${col}${open?'22':'55'};box-shadow:${shadow}"></div>`});
  }
  // Circle for secondary chokepoints
  return L.divIcon({className:'',iconSize:[9,9],iconAnchor:[4,4],
    html:`<div style="width:9px;height:9px;border-radius:50%;border:1.5px solid ${col};background:${col}18;box-shadow:0 0 5px ${col}66"></div>`});
}

function regionIcon(name,sd,coords){
  const rd=(sd.regions||{})[name]||{};
  const ratio=rd.supply>0?rd.demand/rd.supply:0;
  // Colour pulse: green=balanced, amber=tight, red=shortage
  const col=ratio>1.1?'#ff3860':ratio>0.85?'#39ff14':'#ffd23f';
  const r=6;
  return L.divIcon({className:'',iconSize:[r*2,r*2],iconAnchor:[r,r],
    html:`<div title="${coords.label||name}" style="width:${r*2}px;height:${r*2}px;border-radius:50%;
      border:1.5px solid ${col};background:${col}28;
      box-shadow:0 0 6px ${col}88;cursor:pointer;transition:box-shadow .2s"
      onmouseenter="this.style.boxShadow='0 0 12px ${col}'"
      onmouseleave="this.style.boxShadow='0 0 6px ${col}88'"></div>`});
}

function showHoverTip(name,e,coords){
  if(!SIM)return;
  const rd=(SIM.steps[step].regions||{})[name]||{};
  const fields=(coords.popup_fields||'supply,demand,storage').split(',');
  const sd=rd.supply>0?(rd.demand/rd.supply).toFixed(3):'—';
  $('rpop').innerHTML=`<h4>${coords.label||name}</h4>
    ${fields.map(f=>`<div class="rpr"><span>${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`).join('')}
    <div class="rpr"><span>D/S ratio</span><span class="rpv">${sd}</span></div>`;
  const mr=$('map').getBoundingClientRect();
  let x=e.originalEvent.clientX-mr.left+12,y=e.originalEvent.clientY-mr.top+12;
  if(x+180>mr.width)x-=190;if(y+110>mr.height)y-=120;
  $('rpop').style.cssText+=`;left:${x}px;top:${y}px;display:block`;
}

// ── Master render ─────────────────────────────────────────────────────────────
function render(s){
  if(!SIM)return;
  step=Math.max(0,Math.min(SIM.steps.length-1,s));
  const sd=SIM.steps[step];
  $('date-bd').textContent=sd.date;
  $('step-bd').textContent=`${step+1}/${SIM.steps.length}`;
  $('scrubber').value=step;
  // Ticker
  const sp=sd.spot_rate,dir=prevSpot===null?'':sp>prevSpot?'up':'dn';
  $('tv-spot').textContent='$'+(sp/1000).toFixed(1)+'k';$('tv-spot').className='tkv '+dir;
  $('tv-wti').textContent='$'+sd.wti.toFixed(1);
  $('tv-vlsfo').textContent='$'+sd.vlsfo.toFixed(0);
  $('tv-fleet').textContent=sd.fleet_active+(sd.fleet_storage>0?'+'+sd.fleet_storage+'⚓':'');
  $('tv-sd').textContent=sd.sd_ratio.toFixed(3);
  const rt=sd.route_throughput||1;
  const rtEl=$('tv-rt');
  rtEl.textContent=(rt*100).toFixed(0)+'%';
  rtEl.style.color=rt<0.75?'#ff3860':rt<0.9?'#ffd23f':'#39ff14';
  prevSpot=sp;
  // Constraint/node badges
  const csts=(sd.constraints||'').split(';').filter(Boolean);
  const closed=Object.entries(sd.nodes||{}).filter(([,v])=>!v).map(([k])=>k);
  $('cst-strip').innerHTML=csts.map(c=>`<span class="cb">${c}</span>`).join('')+
    closed.map(n=>`<span class="cb closed">⛔ ${n}</span>`).join('');
  // Map update
  updateVessels(step);
  Object.entries(nmarks).forEach(([name,m])=>{
    const nc=SIM.nodes[name];if(!nc)return;
    const open=!sd.nodes||sd.nodes[name]!==false;
    m.setIcon(nodeIcon(nc,open));
  });
  Object.entries(rmarks).forEach(([name,m])=>m.setIcon(regionIcon(name,sd,SIM.regions[name]||{})));
  updateFleet(sd);updateSD(sd);updateSpark(step);updateAllPinnedPanels();
}

function updateVessels(s){
  if(!SIM)return;
  const frame=SIM.frames[s]||[];
  const fids=new Set(frame.map(v=>v.id));
  Object.keys(vmarks).forEach(id=>{if(!fids.has(+id)){vlayer.removeLayer(vmarks[id]);delete vmarks[id];}});
  const op=parseFloat(uiSettings().vessel_opacity||0.85);
  frame.forEach(v=>{
    if(!vmarks[v.id]){
      vmarks[v.id]=L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,
        fillOpacity:op,weight:1.2,opacity:.9})
        .bindTooltip(`<b style="color:${v.color}">${v.owner}</b><br>${v.type}`,{sticky:true})
        .addTo(vlayer);
    }else vmarks[v.id].setLatLng([v.lat,v.lon]);
  });
}

function updateFleet(sd){
  const fleet=sd.fleet||{},total=Object.values(fleet).reduce((a,b)=>a+b,0)||1;
  // Colour each type from the current frame's vessel data
  const typeColors={};
  (SIM.frames[step]||[]).forEach(v=>{typeColors[v.type]=v.color;});
  $('fleet-bd').innerHTML=Object.entries(fleet).map(([t,n])=>{
    const c=typeColors[t]||'#8892b0';
    return `<div class="fr"><div class="fd" style="background:${c}"></div>
      <div class="fn">${t}</div>
      <div class="fbw"><div class="fbf" style="width:${(n/total*100).toFixed(0)}%;background:${c}"></div></div>
      <div class="fn2">${n}</div></div>`;
  }).join('');
}

function updateSD(sd){
  const v=sd.sd_ratio||1,pct=Math.min(100,Math.max(0,(v-.5)/1*100));
  const c=v>1.15?'#ff3860':v>0.95?'#39ff14':'#ffd23f';
  $('sd-fill').style.width=pct+'%';$('sd-fill').style.background=c;
  $('sd-val').textContent='S/D = '+v.toFixed(3);$('sd-val').style.color=c;
}

function updateSpark(upTo){
  if(!SIM)return;
  const cv=$('spark'),ctx=cv.getContext('2d'),dpr=devicePixelRatio||1;
  cv.width=cv.offsetWidth*dpr;cv.height=cv.offsetHeight*dpr;ctx.scale(dpr,dpr);
  const W=cv.offsetWidth,H=cv.offsetHeight;
  const rates=SIM.steps.slice(0,upTo+1).map(s=>s.spot_rate);
  const mn=Math.min(...rates),mx=Math.max(...rates),rng=mx-mn||1;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='#00e5ff';ctx.lineWidth=1.3;ctx.shadowColor='#00e5ff';ctx.shadowBlur=3;
  ctx.beginPath();
  rates.forEach((r,i)=>{const x=(i/(rates.length-1||1))*W,y=H-((r-mn)/rng)*(H-5)-3;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
  ctx.stroke();ctx.shadowBlur=0;
  const lx=(rates.length-1)/(SIM.steps.length-1||1)*W,ly=H-((rates[rates.length-1]-mn)/rng)*(H-5)-3;
  ctx.beginPath();ctx.arc(lx,ly,2.5,0,Math.PI*2);ctx.fillStyle='#00e5ff';ctx.fill();
}

function buildLegend(){
  // Legend is built from viz_companies and viz_ship_groups tables — not hardcoded
  $('leg-owners').innerHTML=(tables.viz_companies||[]).map(r=>
    `<div class="li"><div class="ld" style="background:${r.color}"></div><span class="ll">${r.label||r.name}</span></div>`).join('');
  $('leg-groups').innerHTML=(tables.viz_ship_groups||[]).map(r=>{
    const d=+r.map_radius*2+2;
    return `<div class="sr"><div class="sg" style="width:${d}px;height:${d}px"></div><span class="ll">${r.label||r.group}</span></div>`;
  }).join('');
}

// ── Playback controls ─────────────────────────────────────────────────────────
function setPlay(v){
  playing=v;$('tb-play').textContent=v?'⏸':'▶';$('tb-play').classList.toggle('active',v);
  if(v)timer=setInterval(()=>{
    if(step>=(SIM?.steps.length||1)-1){setPlay(false);return;}
    render(step+SPDS[spdIdx]);
  },parseInt(uiSettings().animation_tick_ms||600));
  else clearInterval(timer);
}
$('tb-play').onclick=()=>{if(SIM)setPlay(!playing)};
$('tb-stop').onclick=()=>{setPlay(false);render(0)};
$('tb-prev').onclick=()=>{setPlay(false);if(SIM)render(step-1)};
$('tb-next').onclick=()=>{setPlay(false);if(SIM)render(step+1)};
$('tb-fa').onclick=()=>{spdIdx=Math.min(spdIdx+1,SPDS.length-1);$('spd-ind').textContent=SPDS[spdIdx]+'×'};
$('tb-sl').onclick=()=>{spdIdx=Math.max(spdIdx-1,0);$('spd-ind').textContent=SPDS[spdIdx]+'×'};
$('scrubber').oninput=function(){setPlay(false);if(SIM)render(+this.value)};

// ── Objects panel — driven by object_lists + object_fields ──────────────────

let curObjTable = null;

function buildObjectsNav() {
  const lists = [...(tables.object_lists || [])]
    .filter(r => String(r.enabled).toLowerCase() !== 'false')
    .sort((a,b) => (+a.sort_order||99) - (+b.sort_order||99));

  const groups = {};
  lists.forEach(r => {
    const g = r.object_type || 'other';
    if (!groups[g]) groups[g] = [];
    groups[g].push(r);
  });

  const nav = $('onav'); nav.innerHTML = '';
  let firstItem = null;

  Object.entries(groups).forEach(([g, items]) => {
    // Only add group header if at least one item will render
    const gh = document.createElement('div'); gh.className = 'cng';
    gh.textContent = g.toUpperCase();
    let addedHeader = false;

    items.forEach(r => {
      if (!addedHeader) { nav.appendChild(gh); addedHeader = true; }
      const rows = tables[r.table_name] || [];
      const el = document.createElement('div'); el.className = 'cni';
      el.id = 'oni-' + r.table_name;
      // Show row count badge so user can see data is there
      el.innerHTML = `<span>${r.icon||''} ${r.label||r.table_name}</span>`
                   + `<span style="float:right;font-size:.55rem;color:var(--t3);margin-top:1px">${rows.length}</span>`;
      el.title = r.description || '';
      el.onclick = () => loadObjectTable(r.table_name, r);
      nav.appendChild(el);
      if (!firstItem) firstItem = {name: r.table_name, meta: r};
    });
  });

  // Auto-open the first object table so the tab isn't blank
  if (firstItem) loadObjectTable(firstItem.name, firstItem.meta);
}

function loadObjectTable(name, meta) {
  curObjTable = name;
  document.querySelectorAll('.cni').forEach(x => x.classList.remove('active'));
  const el = $('oni-' + name); if (el) el.classList.add('active');

  const titleEl = $('obj-title');
  titleEl.textContent = (meta.icon||'') + ' ' + (meta.label||name);
  if (meta.description) titleEl.title = meta.description;

  const actEl = $('obj-actions');
  actEl.style.display = 'flex';

  const rows  = tables[name] || [];
  const specs = getFieldSpecs(name);
  const specMap = Object.fromEntries(specs.map(s => [s.field_name, s]));

  let cols;
  if (specs.length) {
    const specCols = specs.map(s => s.field_name);
    const rawCols  = rows.length ? Object.keys(rows[0]) : [];
    cols = [...specCols, ...rawCols.filter(c => !specCols.includes(c))];
  } else {
    cols = rows.length ? Object.keys(rows[0]) : [];
  }

  $('obj-count').textContent = rows.length + ' rows';

  $('ot-head').innerHTML = '<tr><th style="width:22px"></th>' +
    cols.map(c => {
      const s = specMap[c];
      const lbl = s ? s.field_label : c;
      const tip = s && s.description ? ` title="${esc(s.description)}"` : '';
      return `<th${tip}>${lbl}</th>`;
    }).join('') + '</tr>';

  $('ot-body').innerHTML = rows.map((row, ri) =>
    `<tr><td><button class="dr" onclick="delObjRow(${ri})">✕</button></td>` +
    cols.map(c => {
      const spec = specMap[c] || {field_name:c, field_type:'text', editable:true};
      return renderCell(spec, row[c], ri, 'obj');
    }).join('') + '</tr>'
  ).join('');
}

function saveObjTable() {
  if (!curObjTable) return;
  const rows = [];
  $('ot-body').querySelectorAll('tr').forEach(tr => {
    const row = {};
    tr.querySelectorAll('.oci').forEach(i => {
      row[i.dataset.col] = i.dataset.bool ? String(i.checked) : i.value;
    });
    if (Object.keys(row).length) rows.push(row);
  });
  tables[curObjTable] = rows;
  fetch('/api/table', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: curObjTable, rows})})
    .then(() => { $('obj-count').textContent = rows.length + ' rows'; toast(`✓ ${curObjTable} saved`); });
  document.querySelectorAll('.oci.ch').forEach(i => i.classList.remove('ch'));
}

function addObjRow() {
  if (!curObjTable) return;
  const rows = tables[curObjTable] || [];
  const specs = getFieldSpecs(curObjTable);
  const blank = specs.length
    ? Object.fromEntries(specs.map(s => [s.field_name, s.field_type==='bool'?'False':'']))
    : (rows.length ? Object.fromEntries(Object.keys(rows[0]).map(k=>[k,''])) : {});
  if (!tables[curObjTable]) tables[curObjTable] = [];
  tables[curObjTable].push(blank);
  const meta = (tables.object_lists||[]).find(r=>r.table_name===curObjTable)||{};
  loadObjectTable(curObjTable, meta);
  toast('Row added — fill in and Save');
}

function delObjRow(ri) {
  if (!curObjTable) return;
  tables[curObjTable].splice(ri, 1);
  const meta = (tables.object_lists||[]).find(r=>r.table_name===curObjTable)||{};
  loadObjectTable(curObjTable, meta);
  toast('Row deleted — Save to apply');
}

// ── Config nav — driven by table_registry ─────────────────────────────────────
function buildConfigNav(){
  const reg=[...(tables.table_registry||[])].filter(r=>String(r.enabled||'true').toLowerCase()!=='false');
  reg.sort((a,b)=>(+a.sort_order||99)-(+b.sort_order||99));
  const groups={};
  reg.forEach(r=>{const g=r.group||'Other';if(!groups[g])groups[g]=[];groups[g].push(r);});
  const nav=$('cnav');nav.innerHTML='';
  Object.entries(groups).forEach(([g,items])=>{
    const gh=document.createElement('div');gh.className='cng';gh.textContent=g;nav.appendChild(gh);
    items.forEach(r=>{
      if(!tables[r.table_name])return;
      const el=document.createElement('div');el.className='cni';
      el.textContent=r.label||r.table_name;el.id='cni-'+r.table_name;
      el.onclick=()=>loadTable(r.table_name,r.label||r.table_name);
      nav.appendChild(el);
    });
  });
}

// ── Config table editor — driven by object_fields metadata ───────────────────

// Build field spec index: {table_name: [{field_name, field_label, field_type, ...}]}
function getFieldSpecs(tableName) {
  const specs = (tables.object_fields || [])
    .filter(f => f.table_name === tableName)
    .sort((a,b) => (+a.sort_order||99) - (+b.sort_order||99));
  return specs;
}

// Get all distinct values for a ref field (group_ref → groups.group_id, etc.)
function getRefOptions(fieldType) {
  const MAP = {
    group_ref:  () => (tables.groups||[]).map(r=>r.group_id).filter(Boolean),
    node_ref:   () => (tables.nodes||[]).map(r=>r.node_id).filter(Boolean),
    region_ref: () => (tables.regions||[]).map(r=>r.region).filter(Boolean),
    vessel_ref: () => (tables.vessel_groups||[]).map(r=>r.group_id).filter(Boolean),
    multiref:   () => [],  // freetext for multiref
  };
  return (MAP[fieldType] || (() => []))();
}

// Render one cell input based on field spec
function renderCell(spec, value, ri, cls='c') {
  const col  = spec.field_name;
  const ft   = spec.field_type || 'text';
  const ccls = cls + 'ci';  // 'ci' for config, 'oci' for objects
  const ch   = `this.classList.add('ch')`;
  const base = `data-col="${col}" data-ri="${ri}" class="${ccls}"`;

  if (ft === 'bool') {
    const chk = (String(value).toLowerCase() === 'true' || value === true) ? 'checked' : '';
    return `<td style="text-align:center"><input type="checkbox" ${base} ${chk}
      onchange="this.classList.add('ch')" data-bool="1"></td>`;
  }
  if (ft === 'number') {
    const attrs = [
      spec.min_val !== '' && spec.min_val != null ? `min="${spec.min_val}"` : '',
      spec.max_val !== '' && spec.max_val != null ? `max="${spec.max_val}"` : '',
      spec.step    !== '' && spec.step    != null ? `step="${spec.step}"` : '',
    ].filter(Boolean).join(' ');
    return `<td><input type="number" ${base} value="${esc(value??'')}" ${attrs} oninput="${ch}" style="width:80px"></td>`;
  }
  if (ft === 'select') {
    const opts = (spec.options || '').split(';').filter(Boolean);
    const optHtml = opts.map(o =>
      `<option value="${esc(o)}" ${String(value)===o?'selected':''}>${o}</option>`
    ).join('');
    return `<td><select ${base} onchange="${ch}" style="min-width:90px">
      <option value=""></option>${optHtml}</select></td>`;
  }
  if (ft === 'group_ref' || ft === 'node_ref' || ft === 'region_ref' || ft === 'vessel_ref') {
    const opts = getRefOptions(ft);
    if (opts.length) {
      const optHtml = opts.map(o =>
        `<option value="${esc(o)}" ${String(value)===o?'selected':''}>${o}</option>`
      ).join('');
      return `<td><select ${base} onchange="${ch}" style="min-width:100px">
        <option value=""></option>${optHtml}</select></td>`;
    }
  }
  // text / multiref / unknown
  const editable = spec.editable !== false && String(spec.editable) !== 'False';
  const ro = editable ? '' : 'readonly style="opacity:.5"';
  const title = spec.description ? `title="${esc(spec.description)}"` : '';
  return `<td><input type="text" ${base} value="${esc(value??'')}" oninput="${ch}" ${ro} ${title} style="min-width:80px"></td>`;
}

function loadTable(name, label) {
  curTable = name;
  document.querySelectorAll('.cni').forEach(x => x.classList.remove('active'));
  const el = $('cni-' + name); if (el) el.classList.add('active');
  $('cfg-title').textContent = label || name;
  $('cfg-actions').style.display = 'flex';

  const rows = tables[name] || [];
  const specs = getFieldSpecs(name);

  // Determine columns: use spec order if available, else raw keys
  let cols;
  if (specs.length) {
    const specCols = specs.map(s => s.field_name);
    const rawCols  = rows.length ? Object.keys(rows[0]) : [];
    // Union: spec cols first, then any extra raw cols not in spec
    cols = [...specCols, ...rawCols.filter(c => !specCols.includes(c))];
  } else {
    cols = rows.length ? Object.keys(rows[0]) : [];
  }

  const specMap = Object.fromEntries(specs.map(s => [s.field_name, s]));

  // Header: use field_label from spec when available
  $('ct-head').innerHTML = '<tr><th style="width:22px"></th>' +
    cols.map(c => {
      const s = specMap[c];
      const lbl = s ? s.field_label : c;
      const tip = s && s.description ? ` title="${esc(s.description)}"` : '';
      return `<th${tip}>${lbl}</th>`;
    }).join('') + '</tr>';

  // Body rows
  $('ct-body').innerHTML = rows.map((row, ri) =>
    `<tr><td><button class="dr" onclick="delRow(${ri})">✕</button></td>` +
    cols.map(c => {
      const spec = specMap[c] || {field_name:c, field_type:'text', editable:true};
      return renderCell(spec, row[c], ri);
    }).join('') +
    '</tr>'
  ).join('');
}

function esc(v){return String(v??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}

function saveTable(){
  if(!curTable)return;
  const rows=[];
  $('ct-body').querySelectorAll('tr').forEach(tr=>{
    const row={};
    tr.querySelectorAll('.ci').forEach(i=>{
      // Checkbox: read .checked; others: read .value
      row[i.dataset.col] = i.dataset.bool ? String(i.checked) : i.value;
    });
    if(Object.keys(row).length)rows.push(row);
  });
  tables[curTable]=rows;
  fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:curTable,rows})})
    .then(()=>toast(`✓ ${curTable} saved (${rows.length} rows)`));
  document.querySelectorAll('.ci.ch').forEach(i=>i.classList.remove('ch'));
  if(['viz_companies','viz_ship_groups'].includes(curTable))buildLegend();
}

function resetTable(){
  if(!curTable)return;
  fetch('/api/tables').then(r=>r.json()).then(t=>{
    tables[curTable]=t[curTable];loadTable(curTable);toast(`↺ ${curTable} reset`);
  });
}
function addRow(){
  if(!curTable)return;
  const rows=tables[curTable]||[];
  const specs=getFieldSpecs(curTable);
  let blank;
  if(specs.length){
    blank=Object.fromEntries(specs.map(s=>[s.field_name, s.field_type==='bool'?'False':'']));
  } else {
    blank=rows.length?Object.fromEntries(Object.keys(rows[0]).map(k=>[k,''])):{};
  }
  tables[curTable].push(blank);
  loadTable(curTable);toast('Row added — fill in and Save');
}
function delRow(ri){if(!curTable)return;tables[curTable].splice(ri,1);loadTable(curTable);toast('Row deleted — Save to apply');}



// ── Scenario params — driven by portal_params table ────────────────────────
function buildScenarioParams(){
  const params=(tables.portal_params||[]).filter(p=>String(p.enabled||'true').toLowerCase()!=='false');
  const groups={};
  params.forEach(p=>{const g=p.group||'General';if(!groups[g])groups[g]=[];groups[g].push(p);});
  const grid=$('param-grid');grid.innerHTML='';
  Object.entries(groups).forEach(([g,ps])=>{
    const lbl=document.createElement('div');lbl.className='pg-lbl';lbl.textContent=g;grid.appendChild(lbl);
    ps.forEach(p=>{
      const wrap=document.createElement('div');wrap.className='pr';
      const lel=document.createElement('label');lel.className='pl';lel.textContent=p.label||p.key;
      wrap.appendChild(lel);
      let inp;
      if(p.param_type==='select'){
        inp=document.createElement('select');inp.className='pi';
        (p.options||'').split(';').filter(Boolean).forEach(o=>{
          const opt=document.createElement('option');opt.value=o;opt.textContent=o;
          if(String(runCfg[p.key])===o)opt.selected=true;
          inp.appendChild(opt);
        });
      }else{
        inp=document.createElement('input');inp.className='pi';
        inp.type=p.param_type==='number'?'number':'text';
        inp.value=runCfg[p.key]??p.default_val??'';
        if(p.min_val!=null&&p.min_val!=='')inp.min=p.min_val;
        if(p.max_val!=null&&p.max_val!=='')inp.max=p.max_val;
        if(p.step!=null&&p.step!=='')inp.step=p.step;
      }
      inp.onchange=()=>{runCfg[p.key]=p.param_type==='number'?+inp.value:inp.value;};
      wrap.appendChild(inp);
      if(p.description){const d=document.createElement('div');d.className='pi-d';d.textContent=p.description;wrap.appendChild(d);}
      grid.appendChild(wrap);
    });
  });

  // Presets loaded from scenario_presets table — not hardcoded
  const presetRows = (tables.scenario_presets || [])
    .filter(p => String(p.enabled) !== 'false' && String(p.enabled) !== '0')
    .sort((a,b) => (+a.sort_order||99) - (+b.sort_order||99));
  window._PRESETS = presetRows;
  $('prst-grid').innerHTML = '';
  presetRows.forEach((p, i) => {
    const b = document.createElement('button');
    b.className = 'prst';
    b.textContent = p.name;
    b.title = p.description || '';
    b.onclick = () => applyPreset(i);
    $('prst-grid').appendChild(b);
  });
}

function applyPreset(i){
  const p = window._PRESETS[i];
  if(!p) return;
  // Apply cfg_overrides (key=value;key=value pairs)
  if(p.cfg_overrides){
    p.cfg_overrides.split(';').forEach(pair => {
      const [k,v] = pair.split('=');
      if(k && v !== undefined){
        const num = parseFloat(v);
        runCfg[k.trim()] = isNaN(num) ? v.trim() : num;
      }
    });
    buildScenarioParams();
  }
  // Add constraint row if preset has a constraint_type
  if(p.constraint_type){
    addConstraintRow({
      type:   p.constraint_type,
      target: p.target_nodes || p.target_companies || p.target_regions || '',
      day:    p.apply_on_day  != null ? +p.apply_on_day  : 0,
      end:    p.end_on_day    != null ? p.end_on_day      : '',
      mult:   p.multiplier    != null ? +p.multiplier     : 1,
      add:    p.additive      != null ? +p.additive       : 0,
    }, p.name);
  }
  toast(`"${p.name}" applied — press RUN`);
}

function addConstraintRow(c,label){
  const row={constraint_id:'EVT_'+Date.now(),constraint_type:c.type,
    apply_on_day:c.day??0,end_on_day:c.end??'',description:label||c.type,
    target_nodes:c.type==='node_closure'?c.target:'',
    target_companies:c.type.includes('sanction')?c.target:'',
    target_countries:'',target_regions:'',target_products:'',
    multiplier:c.mult??1,additive:c.add??0,capacity_vessels:''};
  if(!tables.constraints)tables.constraints=[];
  tables.constraints.push(row);
  fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'constraints',rows:tables.constraints})});
}

function addEvent(){
  const type=$('qe-type').value,target=$('qe-target').value.trim();
  addConstraintRow({type,target,day:+$('qe-day').value,end:$('qe-end').value.trim()||'',mult:+$('qe-mult').value},`Quick: ${type} on ${target}`);
  toast('Event added — triggering re-run…');startRun();
}

// ── Dashboard — driven by dashboard_charts table ──────────────────────────────
function buildDashboard(){
  if(!SIM)return;
  const charts=[...(tables.dashboard_charts||[])].filter(c=>String(c.enabled||'true').toLowerCase()!=='false');
  charts.sort((a,b)=>(+a.sort_order||99)-(+b.sort_order||99));
  const dash=$('panel-dash');dash.innerHTML='';
  charts.forEach(c=>{
    const div=document.createElement('div');div.className='cc '+(c.width_class||'third');
    const h=parseInt(c.height||160);
    div.innerHTML=`<div class="cct">${c.title||c.chart_id}</div><canvas class="ch" id="ch-${c.chart_id}" height="${h}" style="height:${h}px"></canvas>`;
    dash.appendChild(div);
    setTimeout(()=>drawChart(c),20);
  });
}

function drawChart(cfg){
  const canvas=document.getElementById('ch-'+cfg.chart_id);if(!canvas)return;
  const ctx=canvas.getContext('2d'),dpr=devicePixelRatio||1;
  canvas.width=canvas.offsetWidth*dpr;canvas.height=canvas.offsetHeight*dpr;ctx.scale(dpr,dpr);
  const W=canvas.offsetWidth,H=canvas.offsetHeight;
  const P={l:44,r:8,t:10,b:24},CW=W-P.l-P.r,CH=H-P.t-P.b;
  const fields=(cfg.series_fields||'').split(';').filter(Boolean);
  const labels=(cfg.series_labels||'').split(';');
  const colors=(cfg.series_colors||'').split(';');
  const fill=cfg.chart_type==='area';
  const series=fields.map((f,i)=>({data:SIM.steps.map(s=>parseFloat(s[f])||0),label:labels[i]||f,color:colors[i]||'#00e5ff',fill}));
  const all=series.flatMap(s=>s.data).filter(isFinite);
  let mn=Math.min(...all),mx=Math.max(...all);
  const hl=cfg.hline&&cfg.hline!==''?parseFloat(cfg.hline):null;
  if(hl!==null){mn=Math.min(mn,hl*.9);mx=Math.max(mx,hl*1.1);}
  const rng=mx-mn||1;
  const toX=i=>P.l+(i/(SIM.steps.length-1||1))*CW;
  const toY=v=>P.t+CH-((v-mn)/rng)*CH;
  ctx.fillStyle='#060e18';ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#1e3a5a';ctx.lineWidth=.5;
  for(let i=0;i<5;i++){const y=P.t+i*(CH/4);ctx.beginPath();ctx.moveTo(P.l,y);ctx.lineTo(P.l+CW,y);ctx.stroke();
    const v=mx-(i/4)*rng;ctx.fillStyle='#3d5a78';ctx.font='9px Share Tech Mono';
    ctx.fillText(v>9999?(v/1000).toFixed(1)+'k':v.toFixed(2),2,y+3);}
  if(hl!==null){ctx.strokeStyle='rgba(255,210,63,.35)';ctx.setLineDash([4,4]);ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(P.l,toY(hl));ctx.lineTo(P.l+CW,toY(hl));ctx.stroke();ctx.setLineDash([]);}
  series.forEach(s=>{
    if(s.fill){ctx.beginPath();s.data.forEach((v,i)=>i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)));
      ctx.lineTo(toX(s.data.length-1),P.t+CH);ctx.lineTo(toX(0),P.t+CH);ctx.closePath();ctx.fillStyle=s.color+'18';ctx.fill();}
    ctx.beginPath();ctx.strokeStyle=s.color;ctx.lineWidth=1.4;ctx.setLineDash([]);
    s.data.forEach((v,i)=>i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)));ctx.stroke();
  });
  // Draw branch fork markers
  fetch('/api/branches').then(r=>r.json()).then(data=>{
    (data.branches||[]).forEach(b=>{
      const n=SIM.steps.length; if(n<2)return;
      const fx=toX(b.fork_step);
      ctx.save();
      ctx.strokeStyle=b.color;ctx.lineWidth=1;ctx.setLineDash([3,3]);
      ctx.beginPath();ctx.moveTo(fx,P.t);ctx.lineTo(fx,P.t+CH);ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle=b.color;ctx.font='9px Share Tech Mono';
      ctx.fillText('⑂',fx+2,P.t+10);
      ctx.restore();
    });
  }).catch(()=>{});
  const xstep=Math.ceil(SIM.steps.length/8);
  ctx.fillStyle='#3d5a78';ctx.font='9px Share Tech Mono';
  SIM.steps.forEach((_,i)=>{if(i%xstep===0)ctx.fillText(SIM.steps[i].date,toX(i)-12,H-3);});
  let lx=P.l;series.forEach(s=>{ctx.fillStyle=s.color;ctx.fillRect(lx,4,6,4);ctx.fillStyle='#7a9abb';ctx.font='9px Share Tech Mono';
    ctx.fillText(s.label,lx+9,10);lx+=ctx.measureText(s.label).width+18;});
}

// ── Export ────────────────────────────────────────────────────────────────────
function downloadTables(){
  const b=new Blob([JSON.stringify(tables,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='maritime_tables.json';a.click();
}
function exportMap(){
  if(!SIM){toast('Run simulation first');return;}
  const html=`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Maritime Map Export</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{margin:0;height:100%}#m{height:100vh}.leaflet-tile{filter:brightness(.28) saturate(.3) hue-rotate(190deg)}.leaflet-container{background:#010608}</style>
</head><body><div id="m"></div><script>
const D=${JSON.stringify(SIM)};
const m=L.map('m',{center:[20,20],zoom:2,attributionControl:false});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(m);
Object.values(D.routes).forEach(r=>L.polyline(r.waypoints,{color:'#00e5ff',opacity:.08,weight:1.5,dashArray:'4 6'}).addTo(m));
let s=0;const vl=L.layerGroup().addTo(m),vm={};
setInterval(()=>{
  const fr=D.frames[s]||[],ids=new Set(fr.map(v=>v.id));
  Object.keys(vm).forEach(id=>{if(!ids.has(+id)){vl.removeLayer(vm[id]);delete vm[id];}});
  fr.forEach(v=>{if(!vm[v.id])vm[v.id]=L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,fillOpacity:.85,weight:1}).bindTooltip(v.owner+': '+v.type).addTo(vl);else vm[v.id].setLatLng([v.lat,v.lon]);});
  s=(s+1)%D.steps.length;
},600);
</script></body></html>`;
  const b=new Blob([html],{type:'text/html'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='maritime_map.html';a.click();
  toast('Map HTML exported');
}
function buildExportSummary(){
  if(!SIM)return;
  const steps=SIM.steps,f=steps[0],l=steps[steps.length-1];
  $('x-summary').style.display='block';
  $('x-sum-body').innerHTML=[`Granularity: ${SIM.meta.granularity}`,`Periods: ${SIM.meta.n_periods}`,
    `Range: ${f.date} → ${l.date}`,`Spot: $${(f.spot_rate/1000).toFixed(1)}k → $${(l.spot_rate/1000).toFixed(1)}k /day`,
    `Fleet: ${f.fleet_active} → ${l.fleet_active} vessels`,
    `Peak spot: $${(Math.max(...steps.map(s=>s.spot_rate))/1000).toFixed(1)}k/day`,
    `Constraints (final): ${l.constraints||'none'}`].map(t=>`<div>${t}</div>`).join('');
}

window.addEventListener('resize',()=>{if(SIM&&document.querySelector('#panel-dash.active'))buildDashboard();});

// ═══════════════════════════════════════════════════════════════════════════
// SETTINGS TAB
// ═══════════════════════════════════════════════════════════════════════════
let dataCfg=null;

async function renderSettings(){
  const panel=document.getElementById('panel-settings');
  panel.innerHTML='<div style="padding:20px;font-family:var(--mono);font-size:.7rem;color:var(--t2)">Loading…</div>';
  try{ dataCfg=await fetch('/api/data_config').then(r=>r.json()); }
  catch(e){ panel.innerHTML='<div style="padding:20px;color:var(--rd)">Error: '+e.message+'</div>'; return; }

  panel.innerHTML=`
    <div class="st-card">
      <h3>📁 DATA DIRECTORY</h3>
      <p>CSV files in this folder override built-in templates. Leave blank to auto-discover <code style="color:var(--cy)">./data/</code> next to portal.py. Apply reloads all tables.</p>
      <div class="dir-row">
        <input class="dir-input" id="dir-input" placeholder="/path/to/your/data  or  ./data" value="${dataCfg.data_dir||''}">
        <button class="st-btn" onclick="applyDataDir()">Apply &amp; Reload All</button>
        <button class="st-btn" onclick="exportAllCSV()">⬇ Export all CSVs</button>
      </div>
      <div id="dir-status" style="font-family:var(--mono);font-size:.6rem;color:var(--t3)">
        ${dataCfg.data_dir?'✓ Using: '+dataCfg.data_dir:'Using built-in templates — no data dir configured'}
      </div>
    </div>
    <div class="st-card">
      <h3>📊 TABLE SOURCES  <span style="color:var(--t3);font-size:.62rem">${dataCfg.tables.length} tables</span></h3>
      <p>Download any table as CSV, upload your own CSV to replace it, save the current in-browser edits to a file, or reset to the built-in template.</p>
      <div style="margin-bottom:8px;font-family:var(--mono);font-size:.58rem">
        <span style="color:var(--gn)">■</span> from CSV &nbsp; <span style="color:var(--t3)">■</span> built-in template &nbsp; <span style="color:var(--am)">■</span> uploaded
      </div>
      <div class="table-grid" id="table-grid"></div>
    </div>
    <div class="st-card">
      <h3>🎨 UI SETTINGS  <span style="color:var(--t3);font-size:.62rem">portal_settings table</span></h3>
      <p>These control map center, animation speed, accent colour etc. Saved to the portal_settings table and take effect on next reload.</p>
      <div class="kv-grid" id="settings-kv"></div>
      <button class="st-btn" style="margin-top:10px" onclick="savePortalSettings()">💾 Save</button>
    </div>`;
  renderTableGrid(); renderSettingsKV();
}

function renderTableGrid(){
  if(!dataCfg) return;
  const grid=document.getElementById('table-grid');
  if(!grid) return;
  grid.innerHTML=dataCfg.tables.map(t=>{
    const st=t.source.startsWith('csv')?'csv':t.source==='upload'?'upload':'template';
    const sl=st==='csv'?'📄 '+t.source.replace('csv:',''):st==='upload'?'⬆ uploaded this session':'⬡ built-in template';
    return `<div class="tbl-card" id="tc-${t.name}">
      <div class="tbl-name">${t.name}</div>
      <div class="tbl-src ${st}">${sl}</div>
      <div class="tbl-rows">${t.rows} rows</div>
      <div class="tbl-actions">
        <button class="tbl-btn" onclick="downloadTable('${t.name}')">⬇ CSV</button>
        <button class="tbl-btn" onclick="uploadTable('${t.name}')">⬆ Upload</button>
        <button class="tbl-btn" onclick="saveTableToFile('${t.name}')">💾 Save to file</button>
        ${t.has_template?`<button class="tbl-btn red" onclick="resetTable('${t.name}')">↺ Reset</button>`:''}
      </div>
      <div class="upload-zone" onclick="triggerUpload('${t.name}')"
           ondragover="event.preventDefault()" ondrop="handleDrop(event,'${t.name}')">
        drop CSV here or click
      </div>
      <input type="file" accept=".csv" style="display:none" id="fi-${t.name}" onchange="handleFileInput(this,'${t.name}')">
    </div>`;
  }).join('');
}

function renderSettingsKV(){
  const rows=tables.portal_settings||[];
  const kv=document.getElementById('settings-kv');
  if(!kv) return;
  kv.innerHTML=rows.map((r,i)=>`
    <div class="kv-key" title="${r.description||''}">${r.key}<span style="display:block;font-size:.52rem;color:var(--t3)">${r.group||''}</span></div>
    <input class="kv-val" id="kv-${i}" value="${r.value!=null?r.value:''}" placeholder="${r.description||''}">
  `).join('');
}

async function savePortalSettings(){
  const rows=tables.portal_settings||[];
  rows.forEach((r,i)=>{const el=document.getElementById('kv-'+i);if(el)r.value=el.value;});
  tables.portal_settings=rows;
  await fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'portal_settings',rows})});
  toast('✓ UI settings saved');
}

async function applyDataDir(){
  const val=document.getElementById('dir-input').value.trim();
  const ds=document.getElementById('dir-status');
  ds.textContent='Applying…'; ds.style.color='var(--t3)';
  const r=await fetch('/api/set_data_dir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data_dir:val})}).then(r=>r.json()).catch(e=>({error:e.message}));
  if(r.error){ds.textContent='✗ '+r.error;ds.style.color='var(--rd)';return;}
  tables=await fetch('/api/tables').then(r=>r.json());
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  ds.textContent='✓ Loaded '+r.loaded+' tables from: '+(r.data_dir||'built-in templates');
  ds.style.color='var(--gn)';
  renderTableGrid(); buildConfigNav();
  toast('✓ '+r.loaded+' tables reloaded');
}

function downloadTable(name){window.location.href='/api/download_table/'+name;}

async function saveTableToFile(name){
  const r=await fetch('/api/save_table_csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).then(r=>r.json());
  if(r.error){toast('✗ '+r.error);return;}
  toast('✓ Saved → '+r.path);
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  renderTableGrid();
}

async function resetTable(name){
  if(!confirm('Reset "'+name+'" to built-in template? Unsaved changes lost.'))return;
  const r=await fetch('/api/reset_table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).then(r=>r.json());
  tables=await fetch('/api/tables').then(r=>r.json());
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  renderTableGrid();
  toast('↺ '+name+' reset ('+r.rows+' rows)');
}

function uploadTable(name){document.getElementById('fi-'+name)?.click();}
function triggerUpload(name){document.getElementById('fi-'+name)?.click();}

function handleFileInput(input,name){
  const f=input.files[0]; if(!f)return;
  uploadCSVFile(name,f); input.value='';
}
function handleDrop(e,name){
  e.preventDefault(); const f=e.dataTransfer.files[0]; if(f)uploadCSVFile(name,f);
}

async function uploadCSVFile(name,file){
  const text=await file.text();
  try{
    const r=await fetch('/api/upload_csv?table='+encodeURIComponent(name),{
      method:'POST',headers:{'Content-Type':'text/plain'},body:text
    }).then(r=>r.json());
    if(r.error){toast('✗ '+r.error);return;}
    tables=await fetch('/api/tables').then(r=>r.json());
    dataCfg=await fetch('/api/data_config').then(r=>r.json());
    renderTableGrid(); buildConfigNav();
    toast('✓ '+name+': '+r.rows+' rows loaded from file');
  }catch(e){toast('✗ Upload failed: '+e.message);}
}

async function exportAllCSV(){
  const names=(dataCfg?.tables||[]).map(t=>t.name);
  for(const n of names){
    const a=document.createElement('a');a.href='/api/download_table/'+n;a.download=n+'.csv';a.click();
    await new Promise(r=>setTimeout(r,200));
  }
  toast('⬇ Downloading '+names.length+' CSV files…');
}


// ── Pinned region popup panels ────────────────────────────────────────────
const pinnedPanels = {};

function pinRegionPanel(name, coords) {
  if (pinnedPanels[name]) {
    // Already open — bring to front
    pinnedPanels[name].style.zIndex = nextZ();
    return;
  }
  if (!SIM) return;
  const el = document.createElement('div');
  el.className = 'rpin';
  el.id = 'rpin-'+name;
  el.style.cssText = `position:absolute;z-index:${nextZ()};left:${80+Object.keys(pinnedPanels).length*24}px;top:${60+Object.keys(pinnedPanels).length*24}px`;
  el.innerHTML = buildPinContent(name, coords, SIM.steps[step]);
  // Make draggable
  makeDraggable(el);
  $('map').parentElement.style.position='relative';
  $('map').parentElement.appendChild(el);
  pinnedPanels[name] = el;
  updatePinnedPanel(name);
}

let _zCounter = 2100;
function nextZ(){ return ++_zCounter; }

function buildPinContent(name, coords, sd) {
  const rd = (sd.regions||{})[name]||{};
  const fields = (coords.popup_fields||'supply,demand,storage').split(',');
  const dsRatio = rd.supply>0 ? (rd.demand/rd.supply).toFixed(3) : '—';
  const bal = rd.supply - rd.demand;
  const balCol = bal>=0?'#39ff14':'#ff3860';
  const rows = fields.map(f=>
    `<div class="rprow"><span class="rpk">${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`
  ).join('');
  return `
    <div class="rpin-hdr">
      <span class="rpin-title">${coords.label||name}</span>
      <span class="rpin-sub">${name}</span>
      <button class="rpin-x" onclick="closePin('${name}')">✕</button>
    </div>
    <div class="rpin-body" id="rpinb-${name}">
      ${rows}
      <div class="rprow"><span class="rpk">D/S ratio</span><span class="rpv">${dsRatio}</span></div>
      <div class="rprow"><span class="rpk">Balance</span><span class="rpv" style="color:${balCol}">${bal>=0?'+':''}${bal.toFixed(2)} MMT</span></div>
    </div>
    <canvas class="rpin-spark" id="rpinspark-${name}" height="40"></canvas>`;
}

function updatePinnedPanel(name) {
  if (!SIM || !pinnedPanels[name]) return;
  const coords = SIM.regions[name]; if(!coords) return;
  const sd = SIM.steps[step];
  const rd = (sd.regions||{})[name]||{};
  const fields = (coords.popup_fields||'supply,demand,storage').split(',');
  const dsRatio = rd.supply>0 ? (rd.demand/rd.supply).toFixed(3) : '—';
  const bal = rd.supply - rd.demand;
  const balCol = bal>=0?'#39ff14':'#ff3860';
  const rows = fields.map(f=>
    `<div class="rprow"><span class="rpk">${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`
  ).join('');
  const bodyEl = document.getElementById('rpinb-'+name);
  if(bodyEl) bodyEl.innerHTML = rows +
    `<div class="rprow"><span class="rpk">D/S ratio</span><span class="rpv">${dsRatio}</span></div>
     <div class="rprow"><span class="rpk">Balance</span><span class="rpv" style="color:${balCol}">${bal>=0?'+':''}${bal.toFixed(2)} MMT</span></div>`;
  // Spark — supply history for this region
  const cvs = document.getElementById('rpinspark-'+name);
  if(cvs) {
    const ctx=cvs.getContext('2d'), dpr=devicePixelRatio||1;
    cvs.width=cvs.offsetWidth*dpr; cvs.height=40*dpr; ctx.scale(dpr,dpr);
    const W=cvs.offsetWidth, H=40;
    const vals = SIM.steps.slice(0,step+1).map(s=>(s.regions||{})[name]?.supply||0);
    const mn=Math.min(...vals),mx=Math.max(...vals),rng=mx-mn||1;
    ctx.clearRect(0,0,W,H);
    // Supply line (green)
    ctx.strokeStyle='#39ff14'; ctx.lineWidth=1.2; ctx.beginPath();
    vals.forEach((v,i)=>{const x=(i/(vals.length-1||1))*W,y=H-((v-mn)/rng)*(H-4)-2;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
    // Demand line (amber)
    const dvals = SIM.steps.slice(0,step+1).map(s=>(s.regions||{})[name]?.demand||0);
    ctx.strokeStyle='#ffd23f'; ctx.lineWidth=1; ctx.beginPath();
    dvals.forEach((v,i)=>{const x=(i/(dvals.length-1||1))*W,y=H-((v-mn)/rng)*(H-4)-2;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
  }
}

function updateAllPinnedPanels() {
  Object.keys(pinnedPanels).forEach(name=>updatePinnedPanel(name));
}

function closePin(name) {
  if(pinnedPanels[name]) {
    pinnedPanels[name].remove();
    delete pinnedPanels[name];
  }
}

function makeDraggable(el) {
  let ox,oy,mx,my,dragging=false;
  el.querySelector('.rpin-hdr').addEventListener('mousedown',e=>{
    if(e.target.classList.contains('rpin-x')) return;
    dragging=true; ox=el.offsetLeft; oy=el.offsetTop; mx=e.clientX; my=e.clientY;
    el.style.zIndex=nextZ();
    e.preventDefault();
  });
  document.addEventListener('mousemove',e=>{
    if(!dragging) return;
    el.style.left=(ox+e.clientX-mx)+'px';
    el.style.top=(oy+e.clientY-my)+'px';
  });
  document.addEventListener('mouseup',()=>{dragging=false;});
}

init();

// ── Fork / Branch system ──────────────────────────────────────────────────────

/* CSS injected inline */
(function(){
  const s=document.createElement('style');
  s.textContent=`
  #fork-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:4000;align-items:center;justify-content:center}
  #fork-modal.open{display:flex}
  #fork-box{background:#050c18;border:1px solid #1e3a5f;border-radius:6px;padding:20px 24px;min-width:340px;max-width:480px;font-family:var(--mono);color:var(--t1)}
  #fork-box h3{margin:0 0 14px;color:#00e5ff;font-size:.85rem;letter-spacing:.05em}
  .fp{margin-bottom:10px}
  .fp label{display:block;font-size:.6rem;color:#7a9abb;margin-bottom:3px}
  .fp input,.fp select{width:100%;background:#0a1628;border:1px solid #1e3a5f;color:var(--t1);
    border-radius:3px;padding:5px 8px;font-family:var(--mono);font-size:.7rem;box-sizing:border-box}
  .fp .fp-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  #fork-actions{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
  #fork-actions button{padding:6px 14px;border-radius:3px;font-family:var(--mono);font-size:.68rem;cursor:pointer;border:none}
  #fork-go{background:#00e5ff;color:#050c18;font-weight:700}
  #fork-cancel{background:#142540;color:#7a9abb;border:1px solid #1e3a5f}
  #branch-panel{position:fixed;right:12px;top:50%;transform:translateY(-50%);
    background:#050c18;border:1px solid #1e3a5f;border-radius:5px;z-index:1200;
    min-width:200px;max-width:240px;display:none;font-family:var(--mono)}
  #branch-panel.open{display:block}
  #branch-panel-hdr{padding:7px 10px;color:#00e5ff;font-size:.65rem;letter-spacing:.05em;
    border-bottom:1px solid #1e3a5f;display:flex;justify-content:space-between;align-items:center}
  .br-item{padding:6px 10px;border-bottom:1px solid #0d1f3a;cursor:pointer;transition:background .15s}
  .br-item:hover{background:#0a1628}
  .br-item.active{background:#0a1f3a;border-left:3px solid #00e5ff}
  .br-name{font-size:.65rem;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .br-meta{font-size:.55rem;color:#7a9abb;margin-top:2px}
  .br-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;flex-shrink:0}
  .br-row{display:flex;align-items:center}
  .br-del{margin-left:auto;padding:1px 5px;background:transparent;border:none;color:#ff3860;
    cursor:pointer;font-size:.7rem;opacity:.5;transition:opacity .15s}
  .br-del:hover{opacity:1}
  .fork-btn{background:#1e3a5f!important;color:#00e5ff!important;font-size:.6rem!important;padding:3px 8px!important}
  #branch-toggle{padding:3px 8px;background:#1e3a5f;color:#00e5ff;border:1px solid #2a4a7f;
    border-radius:3px;font-family:var(--mono);font-size:.58rem;cursor:pointer;margin-left:6px}
  .br-prog{height:2px;background:#142540;margin-top:3px;border-radius:1px;overflow:hidden}
  .br-prog-fill{height:100%;background:#00e5ff;transition:width .3s}
  `;
  document.head.appendChild(s);
})();

// Fork dialog
let forkOverrides = {};

function openForkDialog(){
  if(!SIM){toast('Run simulation first');return;}
  $('fork-step-val').value = step;
  $('fork-name').value = 'Branch @step '+step;
  // Reset overrides
  ['fork-spot','fork-wti','fork-vlsfo','fork-scrapping'].forEach(id=>{
    const el=$B(id); if(el) el.value='';
  });
  $('fork-modal').classList.add('open');
}
function closeForkDialog(){$('fork-modal').classList.remove('open');}

async function submitFork(){
  const forkStep = parseInt($('fork-step-val').value)||step;
  const name     = $('fork-name').value || ('Branch @'+forkStep);
  const cfg = {};
  const spot = parseFloat($('fork-spot').value);    if(!isNaN(spot))   cfg.base_spot_rate=spot;
  const wti  = parseFloat($('fork-wti').value);     if(!isNaN(wti))    cfg.wti_price=wti;
  const vlsfo= parseFloat($('fork-vlsfo').value);   if(!isNaN(vlsfo))  cfg.fuel_vlsfo=vlsfo;
  const scrap= parseFloat($('fork-scrapping').value);if(!isNaN(scrap)) cfg.scrapping_threshold=scrap;
  const n    = parseInt($('fork-nperiods').value);   if(!isNaN(n))      cfg.n_periods=n;
  closeForkDialog();
  toast('Forking simulation from step '+forkStep+'…');
  const r = await fetch('/api/branch/create',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({fork_step:forkStep, fork_branch_id:'main', name, config:cfg})});
  const d = await r.json();
  if(d.error){toast('Fork error: '+d.error);return;}
  $('branch-sel-wrap').style.display='';
  $('branch-panel').classList.add('open');
  pollBranches();
}

async function activateBranch(bid){
  await fetch('/api/branch/activate',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({branch_id:bid})});
  SIM=null; step=0;
  const r=await fetch('/api/result'); if(!r.ok)return;
  SIM=await r.json();
  if(SIM&&SIM.steps){
    $('scrubber').max=SIM.steps.length-1;
    renderStep(step);
    renderInitMap();
  }
  toast(bid==='main'?'Showing main run':'Showing '+bid);
}

async function deleteBranch(bid){
  if(!confirm('Delete branch '+bid+'?'))return;
  await fetch('/api/branch/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({branch_id:bid})});
  refreshBranchPanel();
  if($('branch-sel').value===bid) activateBranch('main');
}

let _branchPoll=null;
function pollBranches(){
  if(_branchPoll)clearInterval(_branchPoll);
  _branchPoll=setInterval(async()=>{
    await refreshBranchPanel();
    const any=Object.values(await (await fetch('/api/branches')).json().then(d=>d.branches||[])).some(b=>b.status==='running');
    if(!any){clearInterval(_branchPoll);_branchPoll=null;}
  },1200);
}

async function refreshBranchPanel(){
  const resp=await fetch('/api/branches');
  const data=await resp.json();
  const branches=data.branches||[];
  const active=data.active||'main';

  // Update selector
  const sel=$('branch-sel');
  const prevVal=sel.value;
  sel.innerHTML='<option value="main">● main</option>';
  branches.forEach(b=>{
    const o=document.createElement('option');
    o.value=b.id;
    o.textContent=(b.status==='running'?'⟳ ':b.status==='error'?'✗ ':'⑂ ')+b.name;
    sel.appendChild(o);
  });
  sel.value=active||'main';

  // Update panel
  const list=$('branch-list');
  list.innerHTML='';
  if(branches.length===0){
    list.innerHTML='<div style="padding:8px 10px;font-size:.58rem;color:#7a9abb">No branches yet.<br>Click ⑂ Fork to create one.</div>';
    return;
  }
  branches.forEach(b=>{
    const isActive=(b.id===active);
    const div=document.createElement('div');
    div.className='br-item'+(isActive?' active':'');
    const progHtml=b.status==='running'?
      `<div class="br-prog"><div class="br-prog-fill" style="width:${b.progress}%"></div></div>`:'';
    div.innerHTML=`<div class="br-row">
      <span class="br-dot" style="background:${b.color}"></span>
      <span class="br-name">${b.name}</span>
      <button class="br-del" onclick="deleteBranch('${b.id}')" title="Delete">✕</button>
    </div>
    <div class="br-meta">⑂ step ${b.fork_step} · ${b.status}${b.status==='running'?' '+b.progress+'%':''}</div>
    ${progHtml}`;
    div.onclick=e=>{if(e.target.classList.contains('br-del'))return;activateBranch(b.id);};
    list.appendChild(div);
  });
  if(branches.length>0) $('branch-sel-wrap').style.display='';
}

function $B(id){return document.getElementById(id);}
