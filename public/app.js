/* TTNN Ops Dashboard — self-contained renderer (no deps) */
(function(){
"use strict";
const D = window.DASH;
const $ = (s,p=document)=>p.querySelector(s);
const $$ = (s,p=document)=>[...p.querySelectorAll(s)];
const fmt = n => n.toLocaleString('en-US');
const pct = (n,d)=> d? (100*n/d):0;

/* ---- status meta ---- */
const SMETA = {
  PASS:       {c:'#10b981', label:'Pass',          short:'PASS',   desc:'Output matched the golden reference within the PCC accuracy threshold.'},
  PCC_FAIL:   {c:'#f59e0b', label:'PCC Fail',       short:'PCC',    desc:'Ran to completion, but the result was numerically inaccurate — PCC below threshold or NaN.'},
  ERROR:      {c:'#ef4444', label:'Hard Error',     short:'ERR',    desc:'Crashed before producing a result (TT_FATAL / TT_THROW — a device assertion or build failure).'},
  NO_GOLDEN:  {c:'#38bdf8', label:'No Golden Ref',  short:'NOGOLD', desc:'Ran, but there was no golden reference output to verify the result against.'},
  SKIP:       {c:'#64748b', label:'Skipped',        short:'SKIP',   desc:'Intentionally skipped — this configuration is unsupported for the op.'},
  NOT_IN_TTNN:{c:'#475569', label:'Not in TTNN',    short:'N/A',    desc:'The operation is not implemented in TTNN.'},
};
// Canonical order; drop any status with zero configs in the current dataset so
// empty categories don't show up anywhere (donut, legend, chips, snapshot, table).
const ALL_ORDER = ['PASS','PCC_FAIL','ERROR','NO_GOLDEN','SKIP','NOT_IN_TTNN'];
const ORDER = ALL_ORDER.filter(s => (D.statusCounts[s]||0) > 0);

/* ---- tooltip ---- */
const tip = $('#tip');
function showTip(html, e){
  tip.innerHTML = html; tip.style.opacity='1';
  moveTip(e);
}
function moveTip(e){
  const pad=14, w=tip.offsetWidth, h=tip.offsetHeight;
  let x=e.clientX+pad, y=e.clientY+pad;
  if(x+w>innerWidth-8) x=e.clientX-w-pad;
  if(y+h>innerHeight-8) y=e.clientY-h-pad;
  tip.style.left=x+'px'; tip.style.top=y+'px';
}
function hideTip(){ tip.style.opacity='0'; }
function tipHead(status, txt){
  const m=SMETA[status];
  return `<div class="t-h"><span class="sw" style="background:${m.c}"></span>${txt||m.label}</div>`;
}

/* =========================================================
   META + KPIs
========================================================= */
function renderMeta(){
  const m=D.meta, sc=D.statusCounts;
  $('#meta').innerHTML =
    `<b>${fmt(m.total)}</b> configs`+
    `<span class="dotsep"></span><b>${m.ops}</b> ops`+
    `<span class="dotsep"></span>${m.dtypes.length} dtypes × ${m.layouts.length} layouts × ${m.mems.length} mem`;
  $('#footMeta').textContent = `${fmt(m.total)} configurations across ${m.ops} operations · data refreshed ${m.generated}`;

  const runnable = m.total - sc.SKIP - sc.NOT_IN_TTNN;
  const verifiable = sc.PASS + sc.PCC_FAIL;       // had a golden ref to compare
  const passRate = pct(sc.PASS, verifiable);
  const cards = [
    {cls:'k-pass',  lab:'Pass Rate', ico:'check', val:passRate.toFixed(1)+'%',
      meta:`${fmt(sc.PASS)} of ${fmt(verifiable)} verifiable`, color:'#10b981'},
    {cls:'k-err',   lab:'Hard Errors', ico:'alert', val:fmt(sc.ERROR),
      meta:`${pct(sc.ERROR,m.total).toFixed(1)}% of all configs`, color:'#ef4444'},
    {cls:'k-pcc',   lab:'PCC Failures', ico:'wave', val:fmt(sc.PCC_FAIL),
      meta:'ran but inaccurate', color:'#f59e0b'},
    {cls:'k-nogold',lab:'No Golden', ico:'eye', val:fmt(sc.NO_GOLDEN),
      meta:'unverifiable output', color:'#38bdf8', skipIfZero:sc.NO_GOLDEN},
    {cls:'k-ops',   lab:'Operations', ico:'grid', val:fmt(m.ops),
      meta:`${fmt(runnable)} runnable configs`, color:'#3b82f6'},
    {cls:'k-total', lab:'Total Configs', ico:'layers', val:fmt(m.total),
      meta:`${m.dtypes.length}×${m.layouts.length}×${m.mems.length} sweep`, color:'#a78bfa'},
  ];
  const ICO={
    check:'<path d="M20 6 9 17l-5-5"/>',
    alert:'<path d="M10.3 3.3 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    wave:'<path d="M2 12c2-4 4-4 6 0s4 4 6 0 4-4 6 0"/>',
    eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    layers:'<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 17l9 5 9-5"/>'
  };
  // drop cards explicitly flagged skipIfZero===0 (e.g. No-Golden when absent)
  const shown = cards.filter(c=>!('skipIfZero' in c) || c.skipIfZero>0);
  const kpis=$('#kpis');
  // Publish the card count as a CSS var instead of hard-setting grid-template-columns
  // inline. An inline grid-template-columns would beat every @media rule by
  // specificity (it did — that single line was what broke the mobile layout: 5
  // un-shrinkable cards forced a ~600px floor). With a var, the base CSS lays out
  // `repeat(var(--kpi-cols),1fr)` on desktop while the mobile media queries are
  // free to override the column count (2-up, then 1-up).
  kpis.style.setProperty('--kpi-cols', shown.length);
  kpis.innerHTML = shown.map(c=>`
    <div class="kpi ${c.cls}" style="--accent-2:${c.color}">
      <div class="lab"><svg viewBox="0 0 24 24" fill="none" stroke="${c.color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICO[c.ico]}</svg>${c.lab}</div>
      <div class="val" style="color:${c.color==='#a78bfa'||c.color==='#3b82f6'?'var(--text)':c.color}">${c.val}</div>
      <div class="meta">${c.meta}</div>
    </div>`).join('');
}

/* =========================================================
   LAST-UPDATED PILL  (relative time, self-refreshing)
========================================================= */
function relTime(ms){
  const s = Math.max(0, Math.round((Date.now()-ms)/1000));
  if (s < 45)            return 'just now';
  if (s < 90)            return 'a minute ago';
  const m = Math.round(s/60);
  if (m < 60)            return `${m} minute${m>1?'s':''} ago`;
  const h = Math.round(m/60);
  if (h < 24)            return `${h} hour${h>1?'s':''} ago`;
  const d = Math.round(h/24);
  if (d < 30)            return `${d} day${d>1?'s':''} ago`;
  const mo = Math.round(d/30);
  if (mo < 12)           return `${mo} month${mo>1?'s':''} ago`;
  return `${Math.round(mo/12)} year${mo>=24?'s':''} ago`;
}
function renderUpdated(){
  const m = D.meta;
  const el = $('#updated'), val = $('#updatedVal');
  // prefer the precise ISO timestamp; fall back to the human string if absent
  const t = m.generatedUTC ? new Date(m.generatedUTC) : (m.generated ? new Date(m.generated.replace(' UTC','Z').replace(' ','T')) : null);
  if (!t || isNaN(t)){ // graceful fallback — show whatever string we have
    if (m.generated){ val.textContent = m.generated; el.hidden = false; }
    return;
  }
  const ms = t.getTime();
  const exactLocal = t.toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'});
  const exactUTC   = t.toISOString().slice(0,16).replace('T',' ') + ' UTC';
  el.title = `${exactLocal}\n${exactUTC}`;
  const tick = ()=>{ val.textContent = relTime(ms); };
  tick(); el.hidden = false;
  // live refresh: every 30s (cheap, and reduced-motion safe — it's just text)
  clearInterval(renderUpdated._iv);
  renderUpdated._iv = setInterval(tick, 30000);
}

/* =========================================================
   DONUT (SVG arcs)
========================================================= */
function arc(cx,cy,r,a0,a1){
  const p=(a)=>[cx+r*Math.cos(a), cy+r*Math.sin(a)];
  const [x0,y0]=p(a0),[x1,y1]=p(a1);
  const large = (a1-a0)>Math.PI?1:0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}
function renderDonut(){
  const sc=D.statusCounts, total=D.meta.total;
  $('#donutTotal').textContent=fmt(total);
  const size=190, cx=size/2, cy=size/2, r=72, sw=24;
  let a=-Math.PI/2; const gap=0.018;
  let paths='';
  ORDER.forEach(s=>{
    const v=sc[s]; if(!v) return;
    const frac=v/total, a1=a+frac*2*Math.PI;
    const aa0=a+gap/2, aa1=Math.max(a1-gap/2,aa0+0.001);
    paths+=`<path d="${arc(cx,cy,r,aa0,aa1)}" stroke="${SMETA[s].c}" stroke-width="${sw}" fill="none" stroke-linecap="round" data-s="${s}"/>`;
    a=a1;
  });
  $('#donut').innerHTML=`
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${cx}" cy="${cy}" r="${r}" stroke="#0e1626" stroke-width="${sw}" fill="none"/>
      ${paths}
    </svg>
    <div class="center">
      <div class="big">${fmt(total)}</div>
      <div class="small">tests run</div>
    </div>`;
  const sliceTip = s => tipHead(s)+
    `<div class="t-r"><b>${fmt(sc[s])}</b> configs · <b>${pct(sc[s],total).toFixed(1)}%</b></div>`+
    `<div class="t-d">${SMETA[s].desc}</div>`;
  $$('#donut path').forEach(p=>{
    const s=p.dataset.s;
    p.addEventListener('mousemove',e=>showTip(sliceTip(s),e));
    p.addEventListener('mouseleave',hideTip);
    p.addEventListener('click',()=>soloStatus(s));
  });

  // legend
  $('#legend').innerHTML=ORDER.map(s=>{
    const v=sc[s]; if(!v) return '';
    return `<div class="lg-item" data-s="${s}">
      <span class="sw" style="background:${SMETA[s].c}"></span>
      <span class="nm">${SMETA[s].label}</span>
      <span class="ct tnum">${fmt(v)}</span>
      <span class="pc">${pct(v,total).toFixed(1)}%</span>
    </div>`;}).join('');
  $$('#legend .lg-item').forEach(el=>{
    const s=el.dataset.s;
    el.addEventListener('click',()=>soloStatus(s));
    el.addEventListener('mousemove',e=>showTip(sliceTip(s),e));
    el.addEventListener('mouseleave',hideTip);
  });
}

/* =========================================================
   DIMENSION STACKED BARS  (dtype / layout / mem)
========================================================= */
function dimBlock(title, sub, arr){
  let html=`<div style="margin-bottom:6px"><div style="font-size:11.5px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:.05em">${title}</div>`;
  if(sub) html+=`<div style="font-size:10.5px;color:var(--faint);margin-bottom:9px">${sub}</div>`;
  arr.forEach(row=>{
    const tot=row.total;
    let segs='';
    ORDER.forEach(s=>{
      const v=row[s]; if(!v) return;
      segs+=`<i style="width:${pct(v,tot)}%;background:${SMETA[s].c}" data-s="${s}" data-v="${v}" data-tot="${tot}" data-dim="${row.value}"></i>`;
    });
    const verif=row.PASS+row.PCC_FAIL;
    const pr= verif? pct(row.PASS,verif):0;
    html+=`<div class="sbar-row">
      <span class="sbar-lab" title="${row.value}">${row.value}</span>
      <div class="sbar">${segs}</div>
      <span class="sbar-pct" style="color:${pr>=66?'var(--pass)':pr>=33?'var(--pcc)':'var(--err)'}">${pr.toFixed(0)}%</span>
    </div>`;
  });
  html+='</div>';
  return html;
}
function renderDims(){
  const c=$('#dims'); c.style.gridTemplateColumns='1fr';
  c.innerHTML =
    dimBlock('Data Type','pass-rate of verifiable configs per dtype', D.dims.dtype)+
    `<div style="height:14px"></div>`+
    dimBlock('Tensor Layout','tile vs row-major', D.dims.layout)+
    `<div style="height:14px"></div>`+
    dimBlock('Memory','dram vs l1', D.dims.mem)+
    (D.dims.bcast && D.dims.bcast.length
      ? `<div style="height:14px"></div>`+
        dimBlock('Broadcast','none vs scalar / row / col (binary ops)', D.dims.bcast)
      : '');
  $$('#dims .sbar i').forEach(seg=>{
    const s=seg.dataset.s;
    seg.addEventListener('mousemove',e=>showTip(
      tipHead(s)+`<div class="t-r"><b>${seg.dataset.dim}</b> · ${SMETA[s].label}<br><b>${fmt(+seg.dataset.v)}</b> of ${fmt(+seg.dataset.tot)} · <b>${pct(+seg.dataset.v,+seg.dataset.tot).toFixed(1)}%</b></div>`,e));
    seg.addEventListener('mouseleave',hideTip);
  });
}

/* =========================================================
   ERROR FAMILIES
========================================================= */
function renderErr(){
  const fams=D.errFamilies, max=fams[0]?fams[0].count:1;
  $('#errTotal').textContent=fmt(D.statusCounts.ERROR);
  $('#efam').innerHTML=fams.map(f=>{
    const nm=f.sig.replace(/^(TT_FATAL|TT_THROW)\s+/, m=>m);
    const msg=(f.sample.split('—')[1]||'').trim();
    return `<div class="efam-row">
      <div class="efam-top">
        <span class="efam-name" title="${f.sample.replace(/"/g,'&quot;')}">${nm}</span>
        <span class="efam-ct tnum">${f.count}</span>
      </div>
      <div class="efam-bar"><i style="width:${pct(f.count,max)}%"></i></div>
      ${msg?`<div class="efam-msg">${msg}</div>`:''}
    </div>`;
  }).join('');
}

/* =========================================================
   COVERAGE SNAPSHOT (mini horizontal split bars)
========================================================= */
function renderSnapshot(){
  const sc=D.statusCounts, total=D.meta.total;
  $('#snapTotal').textContent=fmt(total);
  const rows=[
    {lab:'Verifiable & correct', v:sc.PASS, of:total, c:SMETA.PASS.c},
    {lab:'Ran but inaccurate', v:sc.PCC_FAIL, of:total, c:SMETA.PCC_FAIL.c},
    {lab:'Crashed before result', v:sc.ERROR, of:total, c:SMETA.ERROR.c},
    {lab:'No reference to check', v:sc.NO_GOLDEN, of:total, c:SMETA.NO_GOLDEN.c},
    {lab:'Skipped / unsupported', v:sc.SKIP+sc.NOT_IN_TTNN, of:total, c:SMETA.SKIP.c},
  ].filter(r=>r.v>0);  // hide categories absent from the current dataset
  $('#snapshot').innerHTML=rows.map(r=>`
    <div>
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">
        <span style="font-size:12px;color:var(--dim)">${r.lab}</span>
        <span class="mono tnum" style="font-size:12.5px;font-weight:600">${fmt(r.v)} <span style="color:var(--faint);font-weight:400">· ${pct(r.v,r.of).toFixed(1)}%</span></span>
      </div>
      <div style="height:9px;border-radius:5px;background:#0a1120;overflow:hidden;border:1px solid #18263f">
        <i style="display:block;height:100%;width:${pct(r.v,r.of)}%;background:${r.c};border-radius:5px;transition:width 700ms cubic-bezier(.4,0,.2,1)"></i>
      </div>
    </div>`).join('');
}

/* =========================================================
   ULP ACCURACY DISTRIBUTION  (log-bucketed histogram, dtype-filterable)
========================================================= */
let ulpSel='all';   // 'all' | a dtype name
function renderUlp(){
  const u=D.ulpDist;
  if(!u || !u.total){ return; }            // no ULP data -> leave panel empty
  $('#ulpTotal').textContent=fmt(u.total);

  // chips: All + each float dtype that has data
  const dtypes=Object.keys(u.byDtype);
  $('#ulpChips').innerHTML=
    [['all','All'],...dtypes.map(d=>[d,d])]
      .map(([k,lab])=>`<span class="ulp-chip${ulpSel===k?' active':''}" data-k="${k}">${lab}</span>`).join('');
  $$('#ulpChips .ulp-chip').forEach(ch=>ch.addEventListener('click',()=>{
    ulpSel=ch.dataset.k; renderUlp();
  }));

  const counts = ulpSel==='all' ? u.overall : u.byDtype[ulpSel];
  const tot = counts.reduce((a,b)=>a+b,0);
  const max = Math.max(...counts,1);       // scale bars to the tallest bucket
  $('#ulpBars').innerHTML=u.labels.map((lab,i)=>{
    const c=counts[i], wpc=pct(c,max), share=tot?pct(c,tot):0;
    const exact = i===0 ? ' exact' : '';   // bucket "0" = bit-exact
    return `<div class="ulp-row${exact}">
      <span class="ulp-lab">${lab}</span>
      <div class="ulp-track"><i class="ulp-fill" style="width:${c?Math.max(wpc,1.5):0}%"></i></div>
      <span class="ulp-ct"><b>${fmt(c)}</b> · ${share.toFixed(1)}%</span>
    </div>`;
  }).join('');
}

/* =========================================================
   LEADERBOARD TABLE  (sort / filter / drill-down)
========================================================= */
const state = {
  q:'', sort:'passRate', dir:1,
  active:new Set(ORDER),         // which statuses are "on"
  solo:null,                     // soloed status or null
  open:new Set(),                // expanded op rows
};
// status columns are dropped when that status has zero configs in the dataset
const COLS=[
  {k:'op', label:'Operation', num:false},
  {k:'composition', label:'Outcome Composition', num:false, nosort:true},
  {k:'passRate', label:'Pass Rate', num:true},
  {k:'PASS', label:'Pass', num:true},
  {k:'PCC_FAIL', label:'PCC', num:true},
  {k:'ERROR', label:'Err', num:true},
  {k:'NO_GOLDEN', label:'NoGold', num:true},
  {k:'SKIP', label:'Skip', num:true},
  {k:'total', label:'Σ', num:true},
].filter(c=>!SMETA[c.k] || (D.statusCounts[c.k]||0) > 0);

function renderChips(){
  const sc=D.statusCounts;
  $('#chips').innerHTML = ORDER.map(s=>{
    const on=state.active.has(s), solo=state.solo===s;
    return `<button class="chip ${on?'':'off'} ${solo?'solo':''}" data-s="${s}" aria-pressed="${on}" title="Click toggle · dbl-click solo">
      <span class="sw" style="background:${SMETA[s].c}"></span>${SMETA[s].label}<span class="n">${fmt(sc[s])}</span>
    </button>`;
  }).join('');
  $$('#chips .chip').forEach(ch=>{
    let t=null;
    ch.addEventListener('click',()=>{ // single = toggle (debounced vs dblclick)
      clearTimeout(t); t=setTimeout(()=>toggleStatus(ch.dataset.s),200);
    });
    ch.addEventListener('dblclick',()=>{ clearTimeout(t); soloStatus(ch.dataset.s); });
  });
}
function toggleStatus(s){
  state.solo=null;
  if(state.active.has(s)) state.active.delete(s); else state.active.add(s);
  if(state.active.size===0) state.active=new Set(ORDER);
  renderChips(); renderTable();
}
function soloStatus(s){
  if(state.solo===s){ state.solo=null; state.active=new Set(ORDER); }
  else { state.solo=s; state.active=new Set([s]); }
  renderChips(); renderTable();
  document.getElementById('tbl').scrollIntoView({behavior:'smooth',block:'start'});
}

function renderHead(){
  $('#thead').innerHTML = COLS.map(c=>{
    const sorted = state.sort===c.k;
    return `<th class="${c.num?'num':''} ${sorted?'sorted':''}" data-k="${c.k}" ${c.nosort?'style="cursor:default"':''}>
      ${c.label}${!c.nosort?`<span class="ar">${sorted?(state.dir<0?'▼':'▲'):'▲'}</span>`:''}
    </th>`;
  }).join('');
  $$('#thead th').forEach(th=>{
    const c=COLS.find(x=>x.k===th.dataset.k);
    if(c.nosort) return;
    th.addEventListener('click',()=>{
      if(state.sort===c.k) state.dir*=-1;
      else { state.sort=c.k; state.dir = c.k==='op'?1:-1; }
      renderHead(); renderTable();
    });
  });
}

function prClass(pr){ return pr==null?'pr-na':pr>=0.85?'pr-hi':pr>=0.5?'pr-mid':'pr-lo'; }

function compositionBar(o){
  // bar reflects currently-active statuses only. No trailing % here — that number
  // (verifiable-only pass rate) read as an unlabeled orphan next to the dedicated
  // "Pass Rate" column (overall pass rate), so the two looked contradictory
  // (e.g. 100% on the bar vs 5.0% in the column). The bar shows the visual split;
  // the Pass Rate column owns the number.
  const segs=ORDER.filter(s=>state.active.has(s)).map(s=>({s,v:o[s]})).filter(x=>x.v>0);
  const tot=segs.reduce((a,b)=>a+b.v,0);
  if(!tot) return `<div class="cellbar"><div class="track"></div></div>`;
  const inner=segs.map(x=>`<i style="width:${pct(x.v,tot)}%;background:${SMETA[x.s].c}" title="${SMETA[x.s].label}: ${x.v}"></i>`).join('');
  return `<div class="cellbar"><div class="track">${inner}</div></div>`;
}

function badge(v, kind){
  if(!v) return `<span class="badge b0">0</span>`;
  const cls = kind==='ERROR'?'b-err':kind==='PCC_FAIL'?'b-pcc':'';
  return `<span class="badge ${cls}">${v}</span>`;
}

function filteredRows(){
  let rows=D.opLeaderboard.slice();
  const q=state.q.trim().toLowerCase();
  if(q) rows=rows.filter(o=>o.op.toLowerCase().includes(q));
  if(state.solo) rows=rows.filter(o=>o[state.solo]>0);
  const k=state.sort, dir=state.dir;
  rows.sort((a,b)=>{
    if(k==='op') return dir*a.op.localeCompare(b.op);
    let av=a[k], bv=b[k];
    if(k==='passRate'){ av=av==null?-1:av; bv=bv==null?-1:bv; }
    return dir*((av||0)-(bv||0));
  });
  return rows;
}

function renderTable(){
  const rows=filteredRows();
  $('#tableSub').innerHTML = `${rows.length} ops shown` +
    (state.solo?` · soloing <b style="color:${SMETA[state.solo].c}">${SMETA[state.solo].label}</b>`:'') +
    (state.q?` · matching “${state.q}”`:'');
  const tb=$('#tbody');
  if(!rows.length){ tb.innerHTML=''; $('#emptyState').hidden=false; return; }
  $('#emptyState').hidden=true;

  const hasCol=k=>COLS.some(c=>c.k===k); // column survived the zero-count filter?
  tb.innerHTML = rows.map(o=>{
    const open=state.open.has(o.op);
    return `<tr class="op-row ${open?'open':''}" data-op="${o.op}">
      <td><span class="opname"><svg class="tw" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>${o.op}</span></td>
      <td>${compositionBar(o)}</td>
      <td class="num ${prClass(o.passRate)}">${o.passRate==null?'—':(o.passRate*100).toFixed(1)+'%'}</td>
      <td class="num" style="color:var(--pass)">${o.PASS||'<span class="b0">0</span>'}</td>
      <td class="num">${badge(o.PCC_FAIL,'PCC_FAIL')}</td>
      <td class="num">${badge(o.ERROR,'ERROR')}</td>
      ${hasCol('NO_GOLDEN')?`<td class="num" style="color:var(--nogold)">${o.NO_GOLDEN||'<span class="b0">0</span>'}</td>`:''}
      ${hasCol('SKIP')?`<td class="num" style="color:var(--faint)">${o.SKIP||'<span class="b0">0</span>'}</td>`:''}
      <td class="num mono" style="color:var(--dim)">${o.total}</td>
    </tr>` + (open?detailRow(o.op):'');
  }).join('');

  $$('#tbody tr.op-row').forEach(tr=>{
    tr.addEventListener('click',()=>{
      const op=tr.dataset.op;
      if(state.open.has(op)) state.open.delete(op); else state.open.add(op);
      renderTable();
    });
  });
  // composition bar tooltips
  $$('#tbody .cellbar .track i').forEach(i=>{
    i.addEventListener('mousemove',e=>showTip(`<div class="t-r">${i.title}</div>`,e));
    i.addEventListener('mouseleave',hideTip);
  });
  bindMatrix();
}

/* ---- per-op drill-down: dtype × (layout∙mem) matrix ---- */
// Active broadcast mode for the matrix. Binary ops have up to 4 rows per
// (dt,ly,mem) — one per mode — so the matrix shows ONE mode at a time (chips
// below the table switch it). 'none' is the always-present default; unary ops
// only ever have 'none' rows.
let bcastSel = (D.meta.bcasts && D.meta.bcasts.includes('none')) ? 'none' : (D.meta.bcasts?.[0] || 'none');
// Broadcast-mode chip strip above the leaderboard. Hidden when there's only one
// mode (nothing to switch). Clicking a chip re-renders open matrices for that
// mode (mirrors the ULP ulpSel toggle pattern).
function renderBcastChips(){
  const bar=$('#bcastBar'), wrap=$('#bcastChips');
  const modes=D.meta.bcasts||[];
  if(!bar||!wrap||modes.length<2){ if(bar) bar.hidden=true; return; }
  bar.hidden=false;
  wrap.innerHTML=modes.map(m=>`<span class="ulp-chip${bcastSel===m?' active':''}" data-k="${m}">${m}</span>`).join('');
  $$('#bcastChips .ulp-chip').forEach(ch=>ch.addEventListener('click',()=>{
    bcastSel=ch.dataset.k;
    renderBcastChips();   // refresh active state
    renderTable();        // rebuild any open matrices for the new mode
  }));
}
function buildMatrix(op){
  // collect this op's rows for the selected broadcast mode
  const opi=D.ops.indexOf(op);
  const dts=D.meta.dtypes, lys=D.meta.layouts, mems=D.meta.mems;
  const cols=[]; lys.forEach(l=>mems.forEach(m=>cols.push({l,m,key:l+'·'+m})));
  // map[dt][col] = {status, reason, …} — one row per cell once filtered by bcast
  const map={}; dts.forEach(d=>map[d]={});
  for(const r of D.rows){
    if(r[0]!==opi) continue;
    if(D.bcasts[r[9]]!==bcastSel) continue;       // show only the active mode
    const dt=D.dts[r[1]], ly=D.lys[r[2]], mem=D.mems[r[3]];
    if(dt==='-'||ly==='-'||mem==='-') continue;
    map[dt][ly+'·'+mem]={status:D.statusList[r[4]], reason:D.reasons[r[5]], pcc:r[6], ulp:r[7], inputs:(r[8]>=0?D.inputs[r[8]]:''), bcast:D.bcasts[r[9]]};
  }
  return {dts,cols,map};
}
function detailRow(op){
  const {dts,cols,map}=buildMatrix(op);
  const o=D.opLeaderboard.find(x=>x.op===op);
  const colW=`minmax(56px,1fr)`;
  let grid=`grid-template-columns:96px repeat(${cols.length},${colW})`;
  let cells=`<div class="mtx-corner" style="grid-column:1;writing-mode:vertical">dtype ↓ / layout·mem →</div>`;
  cells+=cols.map(c=>`<div class="mtx-colh">${c.l}·${c.m}</div>`).join('');
  dts.forEach(dt=>{
    cells+=`<div class="mtx-rowh">${dt}</div>`;
    cols.forEach(c=>{
      const cell=map[dt][c.key];
      if(!cell){ cells+=`<div class="cell c-empty"></div>`; return; }
      const m=SMETA[cell.status];
      const dark = cell.status==='SKIP'||cell.status==='NOT_IN_TTNN';
      cells+=`<div class="cell" style="background:${m.c};color:${dark?'#cdd8ea':'#0a0e16'}" data-status="${cell.status}" data-dt="${dt}" data-cfg="${c.l}·${c.m}" data-bcast="${cell.bcast||''}" data-pcc="${cell.pcc==null?'':cell.pcc}" data-ulp="${cell.ulp==null?'':cell.ulp}" data-inputs="${cell.inputs||''}" data-reason="${(cell.reason||'').replace(/"/g,'&quot;')}">${m.short[0]}</div>`;
    });
  });
  // configs shown = cells present for the active broadcast mode (not o.total,
  // which sums all modes). Surface the mode so the count makes sense.
  const shown=dts.reduce((n,dt)=>n+cols.reduce((k,c)=>k+(map[dt][c.key]?1:0),0),0);
  const modeNote = (D.meta.bcasts&&D.meta.bcasts.length>1)
    ? `<span class="dotsep"></span> broadcast: <b>${bcastSel}</b>` : '';
  return `<tr class="detail"><td colspan="${COLS.length}"><div class="detail-inner">
    <div class="matrix-title">
      <b>${op}</b> configuration matrix
      <span class="dotsep"></span> ${shown} configs${modeNote}
      <span class="dotsep"></span> hover a cell for the exact result
    </div>
    <div class="mtx" style="${grid}">${cells}</div>
  </div></td></tr>`;
}
// PCC threshold per FLOAT dtype (mirrors the probe: 0.99 default, 0.97 bf8, 0.90 bf4).
// Integer dtypes are graded by EXACT equality, not PCC — their correlation is purely
// informational, so it's labelled differently and never implies pass/fail by threshold.
const PCC_THR={bfloat8_b:0.97, bfloat4_b:0.90};
const INT_DT=new Set(['int32','uint32','uint16','uint8']);
function pccLine(raw, dt, status){
  if(raw===''||raw==null) return '';           // FAIL / no-golden rows have no PCC
  const v=+raw; if(!isFinite(v)) return '';
  // colour by the cell's ACTUAL verdict, not a threshold compare — for ints the
  // threshold doesn't apply, and even for floats this keeps the number consistent
  // with the cell colour (green only when the config actually passed).
  const col = status==='PASS' ? 'var(--pass)' : 'var(--err)';
  const thr=(PCC_THR[dt]??0.99).toFixed(2);  // 2dp so bf4's 0.90 doesn't render as "0.9"
  const note = INT_DT.has(dt)
    ? `correlation · ${dt} graded by exact match`     // PCC is informational for ints
    : `vs ≥${thr} threshold (${dt})`;
  return `<div class="t-pcc">PCC <b style="color:${col}">${v.toFixed(4)}</b>`+
         `<span class="t-thr">${note}</span></div>`;
}
// Max per-element ULP error for the cell (informational — float dtypes only).
// 0 = bit-exact (green, like the accuracy chart); otherwise locale-grouped so
// the huge tail values (up to ~8e10) stay readable.
function ulpLine(raw){
  if(raw===''||raw==null) return '';           // ints / no-golden have no ULP
  const v=+raw; if(!isFinite(v)) return '';
  if(v===0) return `<div class="t-ulp">max error <b style="color:var(--pass)">bit-exact</b><span class="t-thr">0 ULP</span></div>`;
  const shown = v<100 ? (Number.isInteger(v)?v:v.toFixed(2)) : Math.round(v).toLocaleString('en-US');
  return `<div class="t-ulp">max error <b>${shown}</b> <span class="t-thr">ULP</span></div>`;
}
// The value range the probe fed the input tensors for this (op, dtype). Shown as
// part of the config context, since it defines the test rather than its result.
function inputsLine(raw){
  if(!raw) return '';
  return `<div class="t-in">inputs <b>${raw.replace(/</g,'&lt;')}</b></div>`;
}
// Broadcast mode for the cell — part of the config context. 'none' = no
// broadcast (the operands match shape); scalar/row/col = the tested broadcast.
function bcastLine(raw){
  if(!raw) return '';
  return `<div class="t-in">broadcast <b>${raw}</b></div>`;
}
function bindMatrix(){
  $$('#tbody .cell:not(.c-empty)').forEach(c=>{
    c.addEventListener('mousemove',e=>{
      const s=c.dataset.status, m=SMETA[s];
      let reason=c.dataset.reason||'';
      if(reason.length>240) reason=reason.slice(0,240)+'…';
      showTip(tipHead(s)+
        `<div class="t-r"><b>${c.dataset.dt}</b> · ${c.dataset.cfg}<br>`+
        (reason?reason.replace(/</g,'&lt;'):m.label)+`</div>`+
        bcastLine(c.dataset.bcast)+
        inputsLine(c.dataset.inputs)+
        pccLine(c.dataset.pcc, c.dataset.dt, s)+
        ulpLine(c.dataset.ulp),e);
    });
    c.addEventListener('mouseleave',hideTip);
  });
}

/* ---- search ---- */
let stim=null;
$('#search').addEventListener('input',e=>{
  clearTimeout(stim);
  stim=setTimeout(()=>{ state.q=e.target.value; renderTable(); },120);
});
document.addEventListener('mousemove',e=>{ if(tip.style.opacity==='1') moveTip(e); });
addEventListener('keydown',e=>{
  if(e.key==='/'&&document.activeElement!==$('#search')){ e.preventDefault(); $('#search').focus(); }
  if(e.key==='Escape'){ $('#search').blur(); if(state.solo){state.solo=null;state.active=new Set(ORDER);renderChips();renderTable();} }
});

/* =========================================================
   WHAT CHANGED  (build-time diff vs previous snapshot)
========================================================= */
// colour + label per change kind (regressions red, improvements green …)
const KMETA = {
  improved:    {c:'#10b981', label:'improved'},
  regressed:   {c:'#ef4444', label:'regressed'},
  new:         {c:'#38bdf8', label:'new'},
  removed:     {c:'#64748b', label:'removed'},
  statusChange:{c:'#a78bfa', label:'changed'},
  shift:       {c:'#f59e0b', label:'shifted'},
};
const esc = s => String(s).replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));

function chgDate(d){
  if(!d || d==='current') return d||'';
  const t=Date.parse(d+'T00:00:00Z');
  return Number.isNaN(t) ? d
    : new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:'UTC'});
}
// a from/to side -> short status + numeric tail (pcc / ulp), or "—" if absent
function chgSide(side){
  if(!side) return `<span class="st" style="color:var(--faint)">—</span>`;
  const m=SMETA[side.s]||SMETA.SKIP;
  let tail='';
  if(side.pcc!=null) tail+=` <span class="num">pcc ${(+side.pcc).toFixed(3)}</span>`;
  if(side.ulp!=null) tail+=` <span class="num">ulp ${(+side.ulp).toFixed(side.ulp<10?2:0)}</span>`;
  return `<span class="st" style="color:${m.c}">${m.short}</span>${tail}`;
}

function renderChanges(){
  const C = D.changes, body=$('#changesBody'), sub=$('#changesSub'), label=$('#changesLabel');
  if(!body) return;

  // No baseline yet → honest empty state; button stays but says "no baseline".
  if(!C || !C.baseline){
    if(label) label.textContent='Changes';
    if(sub) sub.textContent='Comparison appears once two dated probe runs exist.';
    body.innerHTML=
      `<div class="chg-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/></svg>
        <div><b style="color:var(--dim)">No baseline snapshot yet.</b><br>
        The comparison turns on once the probe has run with <code>--dated</code> on two
        separate days and both snapshots are committed. Until then there's nothing to diff against.</div>
      </div>`;
    return;
  }

  if(sub) sub.textContent=`Changes from the ${chgDate(C.baseline)} run to ${chgDate(C.current)}.`;
  if(label) label.textContent='Changes · vs '+chgDate(C.baseline);

  // summary chips (zeros are dimmed so the row's shape stays stable)
  const order=['improved','regressed','new','removed','statusChange','shift'];
  const S=C.summary;
  // summary stores 'shifted'; the per-item kind is 'shift' — map between them
  const sval={improved:S.improved,regressed:S.regressed,new:S.new,removed:S.removed,
              statusChange:S.statusChange,shift:S.shifted};
  const chips=order.map(k=>{
    const m=KMETA[k], v=sval[k]||0;
    return `<span class="chg-chip${v?'':' zero'}"><span class="d" style="background:${m.c}"></span>${v} ${m.label}</span>`;
  }).join('');

  const ops=C.byOp.map(o=>{
    const mini=order.filter(k=>o.counts[k]).map(k=>{
      const m=KMETA[k];
      return `<i style="color:${m.c};background:${m.c}1f">${o.counts[k]} ${m.label}</i>`;
    }).join('');
    const rows=o.items.map(it=>{
      const m=KMETA[it.kind]||KMETA.statusChange;
      const cfg=`<b>${esc(it.dt)}</b> · ${esc(it.ly)}·${esc(it.mem)}`;
      let mv;
      if(it.kind==='new')          mv=`<span class="arr">+</span>${chgSide(it.to)}`;
      else if(it.kind==='removed') mv=`${chgSide(it.from)}<span class="arr">→ ✕</span>`;
      else                         mv=`${chgSide(it.from)}<span class="arr">→</span>${chgSide(it.to)}`;
      return `<div class="chg-row"><span class="cfg">${cfg}</span>
        <span class="mv"><span class="chg-kind" style="color:${m.c};background:${m.c}1f">${m.label}</span>${mv}</span></div>`;
    }).join('');
    const more=o.more?`<div class="chg-more">+${o.more} more change${o.more>1?'s':''} in ${esc(o.op)}</div>`:'';
    return `<div class="chg-op">
      <div class="chg-op-h"><span class="nm">${esc(o.op)}</span><span class="mini">${mini}</span></div>
      <div class="chg-rows">${rows}${more}</div></div>`;
  }).join('');

  const total=order.reduce((a,k)=>a+(sval[k]||0),0);
  body.innerHTML=
    `<div class="chg-sum">${chips}</div>
     <div class="chg-meta"><b>${total}</b> config change${total===1?'':'s'} across <b>${C.byOp.length}</b> op${C.byOp.length===1?'':'s'} · baseline <b>${esc(chgDate(C.baseline))}</b></div>
     <div class="chg-list">${ops||'<div class="chg-empty">No differences from the previous run.</div>'}</div>`;
}

(function changesModal(){
  const overlay=$('#changesOverlay'); if(!overlay) return;
  const openBtn=$('#changesOpen'), closeEls=[$('#changesClose')];
  let lastFocus=null;
  function open(){
    lastFocus=document.activeElement;
    overlay.hidden=false; document.body.style.overflow='hidden';
    addEventListener('keydown',onKey);
    setTimeout(()=>{ const x=$('#changesClose'); x&&x.focus(); },40);
  }
  function close(){
    overlay.hidden=true; document.body.style.overflow='';
    removeEventListener('keydown',onKey);
    if(lastFocus&&lastFocus.focus) lastFocus.focus();
  }
  function onKey(e){
    if(e.key==='Escape'){ e.preventDefault(); close(); }
    if(e.key==='Tab') trapTab(e);
  }
  function trapTab(e){
    const f=overlay.querySelectorAll('button,input,select,textarea,a[href]');
    const vis=[...f].filter(el=>!el.disabled&&el.offsetParent!==null);
    if(!vis.length) return;
    const first=vis[0], last=vis[vis.length-1];
    if(e.shiftKey&&document.activeElement===first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey&&document.activeElement===last){ e.preventDefault(); first.focus(); }
  }
  openBtn&&openBtn.addEventListener('click',open);
  closeEls.forEach(el=>el&&el.addEventListener('click',close));
  overlay.addEventListener('mousedown',e=>{ if(e.target===overlay) close(); });
})();

/* =========================================================
   SUGGESTIONS / FEEDBACK MODAL
========================================================= */
(function feedback(){
  const overlay=$('#suggestOverlay'), form=$('#suggestForm');
  if(!overlay||!form) return;
  const openBtn=$('#suggestOpen'), closeEls=[$('#suggestClose'),$('#suggestCancel')];
  const typeSel=$('#sgType'), msg=$('#sgMsg'), count=$('#sgCount'), opF=$('#sgOp');
  const email=$('#sgEmail'), website=$('#sgWebsite'), submit=$('#sgSubmit'), formMsg=$('#sgFormMsg');
  let lastFocus=null;

  const setMsg=(t,cls='')=>{ formMsg.textContent=t; formMsg.className='form-msg'+(cls?' '+cls:''); };

  function open(){
    lastFocus=document.activeElement;
    overlay.hidden=false;
    document.body.style.overflow='hidden';
    setMsg('');
    // op field is most relevant for mismatch/bug; keep visible but hint
    setTimeout(()=>typeSel.focus(),40);
    addEventListener('keydown',onKey);
  }
  function close(){
    overlay.hidden=true;
    document.body.style.overflow='';
    removeEventListener('keydown',onKey);
    if(lastFocus&&lastFocus.focus) lastFocus.focus();
  }
  function onKey(e){
    if(e.key==='Escape'){ e.preventDefault(); close(); }
    if(e.key==='Tab') trapTab(e);
  }
  function trapTab(e){
    const f=overlay.querySelectorAll('button,input,select,textarea,a[href]');
    const vis=[...f].filter(el=>!el.disabled&&el.offsetParent!==null);
    if(!vis.length) return;
    const first=vis[0], last=vis[vis.length-1];
    if(e.shiftKey&&document.activeElement===first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey&&document.activeElement===last){ e.preventDefault(); first.focus(); }
  }

  openBtn&&openBtn.addEventListener('click',open);
  closeEls.forEach(el=>el&&el.addEventListener('click',close));
  overlay.addEventListener('mousedown',e=>{ if(e.target===overlay) close(); });

  msg.addEventListener('input',()=>{ count.textContent=msg.value.length; });

  // pre-fill op if a single op row is open in the table, as a nicety
  function suggestedOp(){
    const open=[...state.open]; return open.length===1?open[0]:'';
  }
  openBtn&&openBtn.addEventListener('click',()=>{ if(!opF.value){ const s=suggestedOp(); if(s) opF.value=s; } });

  form.addEventListener('submit',async e=>{
    e.preventDefault();
    const message=msg.value.trim();
    if(message.length<3){ setMsg('Please enter a message (at least 3 characters).','err'); msg.focus(); return; }
    const em=email.value.trim();
    if(em && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)){ setMsg('That email looks invalid.','err'); email.focus(); return; }

    submit.disabled=true; submit.classList.add('loading'); setMsg('Sending…');
    const payload={
      type:typeSel.value, op:opF.value.trim(), message, email:em,
      website:website.value,                       // honeypot
      page:location.href.slice(0,300),
    };
    try{
      const res=await fetch('/api/feedback',{
        method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(payload),
      });
      const data=await res.json().catch(()=>({}));
      if(res.ok&&data.ok){
        setMsg('✓ Thank you — sent!','ok');
        form.reset(); count.textContent='0';
        setTimeout(close,1100);
      }else{
        setMsg(data.error||'Something went wrong. Please try again.','err');
      }
    }catch{
      setMsg('Network error — please try again.','err');
    }finally{
      submit.disabled=false; submit.classList.remove('loading');
    }
  });
})();

/* ---- sticky header: publish its height so the table's sticky <thead>
   pins just below it instead of overlapping (header wraps at breakpoints,
   so re-measure on resize). ---- */
function syncHeaderHeight(){
  const h=$('header.top');
  if(!h) return;
  const px=Math.round(h.getBoundingClientRect().height);
  document.documentElement.style.setProperty('--head-h', px+'px');
}
let rTO=null;
addEventListener('resize',()=>{ clearTimeout(rTO); rTO=setTimeout(syncHeaderHeight,120); });

/* ---- boot ---- */
renderMeta();
renderUpdated();
renderDonut();
renderDims();
renderErr();
renderSnapshot();
renderUlp();
renderChanges();
renderChips();
renderBcastChips();
renderHead();
renderTable();
syncHeaderHeight();
// re-measure after fonts settle (Fira can change header height once loaded)
if(document.fonts&&document.fonts.ready) document.fonts.ready.then(syncHeaderHeight);
addEventListener('load',syncHeaderHeight);
})();
