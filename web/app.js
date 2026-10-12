'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const root = $('app');
  if (!root || root.dataset.initialized) return;
  root.dataset.initialized = '1';
  const PALETTE = {cpu:'#8866bd', ram:'#119bad', gpu:'#3179dd',
    vram:'#267db2', cpuTemp:'#bc8260', gpuTemp:'#c07b61', encode:'#d19a4d', decode:'#7787b8'};
  const GPU_METRICS = new Set(['gpu','vram','gpuTemp','encode','decode']);
  const METRICS = {
    cpu: {title:'Processor',field:'cpu_percent',peak:'cpu_percent_peak',unit:'%',scale:100,
      description:'System-wide CPU utilization. Process CPU percentages are per logical core.',
      appTitle:'Using CPU now', appNote:'A process at 100% occupies one logical core, not the entire CPU.'},
    ram: {title:'System memory',field:'ram_percent',peak:'ram_percent_peak',unit:'%',scale:100,
      description:'RAM in use as a percentage of physical memory, excluding reclaimable memory.',
      appTitle:'Using RAM now', appNote:'RSS is each process’s resident memory. Shared pages can be counted in multiple processes.'},
    gpu: {title:'Graphics processor',field:'gpu_percent',peak:'gpu_percent_peak',unit:'%',scale:100,
      description:'NVIDIA GPU compute/graphics utilization, as reported by the driver.',
      appTitle:'GPU contexts now', appNote:'Per-process GPU SM activity is driver-dependent and is not a percentage of total GPU ownership.'},
    vram: {title:'Video memory',field:'vram_used_bytes',peak:'vram_used_bytes_peak',unit:' GiB',factor:1073741824,
      description:'Allocated VRAM on the selected GPU. Not all driver-reserved memory is attributable to a process.',
      appTitle:'Using GPU memory now', appNote:'VRAM values report per-process allocations where NVIDIA exposes them.'},
    cpuTemp: {title:'CPU temperature',field:'cpu_temp_c',peak:'cpu_temp_c_peak',unit:'°C',
      description:'CPU package/die temperature. It is a sensor reading, not a process-owned measurement.',
      appTitle:'CPU workloads now', appNote:'These are current CPU users, not an assignment of temperature to applications.'},
    gpuTemp: {title:'GPU temperature',field:'gpu_temp_c',peak:'gpu_temp_c_peak',unit:'°C',
      description:'NVIDIA GPU core temperature. No software can assign an exact share of temperature to each program.',
      appTitle:'GPU contexts now', appNote:'GPU work may contribute heat; per-process temperature cannot be measured.'},
    encode: {title:'Video encoder',field:'video_encode_percent',peak:'video_encode_percent_peak',unit:'%',scale:100,
      description:'NVIDIA hardware video encoding engine utilization.',
      appTitle:'Video encoding contexts now', appNote:'Per-process video engine counters may be unavailable on some NVIDIA drivers.'},
    decode: {title:'Video decoder',field:'video_decode_percent',peak:'video_decode_percent_peak',unit:'%',scale:100,
      description:'NVIDIA hardware video decoding engine utilization.',
      appTitle:'Video decoding contexts now', appNote:'Per-process video engine counters may be unavailable on some NVIDIA drivers.'},
  };
  const keyName = 'faco-resource-watch-v1.0.2-preferences';
  function restore() {
    try { return JSON.parse(localStorage.getItem(keyName)) || {}; } catch (_) { return {}; }
  }
  const preference = restore();
  const state = {
    live:true, metric: METRICS[preference.metric] ? preference.metric : 'cpu',
    range: [15,60,1800,3600,21600,86400,604800].includes(preference.range) ? preference.range : 3600,
    gpu: Number.isInteger(preference.gpu) && preference.gpu >= -1 && preference.gpu <= 15 ? preference.gpu : 0,
    current:null, history:[], bucketSeconds:1, historicalProcesses:[],
    selected:null, processHistory:[], historySerial:0, processSerial:0,
    currentPending:false, expanded:false,
    liveSort:preference.liveSort && typeof preference.liveSort==='object' ? preference.liveSort : {},
    pastSortBy:'peak_sm_percent', pastDescending:true,
  };
  const chartEvents = {};
  const number = v => v == null || !Number.isFinite(Number(v)) ? null : Number(v);
  const percent = v => number(v) == null ? '—' : `${Math.round(Number(v))}%`;
  const degrees = v => number(v) == null ? '—' : `${Math.round(Number(v))}°C`;
  const gib = v => number(v) == null ? '—' : `${(Number(v)/1073741824).toFixed(1)} GiB`;
  const mib = v => number(v) == null ? '—' : `${(Number(v)/1048576).toFixed(0)} MiB`;
  const vramPercent = (used,total) => number(used)!=null && Number(total)>0 ? (Number(used)/Number(total))*100 : null;
  const nowSec = () => Math.floor(Date.now()/1000);
  const age = snapshot => nowSec()-Number(snapshot.ts);
  const when = ts => ts == null ? '—' : new Date(Number(ts)*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const shortTime = ts => {const date=new Date(Number(ts)*1000);return state.range<=60 ? date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : state.range>=86400 ? date.toLocaleDateString([], {month:'short',day:'numeric'}) : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});};
  const make = (tag, cls='', content) => {const node=document.createElement(tag); if(cls)node.className=cls; if(content!==undefined)node.textContent=String(content);return node;};
  const gpuNow = () => state.current?.gpus?.find(g=>g.index===state.gpu) || null;
  const savePrefs = () => {
    try { localStorage.setItem(keyName,JSON.stringify({metric:state.metric,range:state.range,gpu:state.gpu,liveSort:state.liveSort})); }
    catch (_) { /* Restricted browser storage is optional. */ }
  };
  const putBar = (id,n) => {const e=$(id);if(e)e.style.width=`${Math.min(100,Math.max(0,Number(n)||0))}%`;};
  async function json(url){const res=await fetch(url,{cache:'no-store'});if(!res.ok)throw Error(`HTTP ${res.status}`);return res.json();}
  function connection(ok,message){$('connection').classList.toggle('offline',!ok);$('connection').querySelector('span').textContent=message;}

  function updateGpuOptions(snapshot){
    const devices=(snapshot.gpus||[]).map(g=>({value:String(g.index),label:`GPU ${g.index}: ${g.name}`}));
    if (!devices.length) devices.push({value:'-1',label:'No NVIDIA GPU available'});
    if(!devices.some(g=>g.value===String(state.gpu)))state.gpu=Number(devices[0].value);
    const signature=JSON.stringify(devices),selector=$('gpuSelect');
    if(selector.dataset.key!==signature){selector.replaceChildren(...devices.map(d=>{const o=make('option','',d.label);o.value=d.value;return o;}));selector.dataset.key=signature;}
    selector.value=String(state.gpu);
    $('gpuChoice').hidden=!(snapshot.gpus||[]).length || !GPU_METRICS.has(state.metric);
  }
  function updateCards(snapshot){
    const g=gpuNow(),ram=snapshot.ram||{};
    const values={cpu:percent(snapshot.cpu_percent),ram:percent(ram.percent),gpu:percent(g?.percent),
      vram:gib(g?.vram_used_bytes),cpuTemp:degrees(snapshot.cpu_temp_c),gpuTemp:degrees(g?.temp_c),
      encode:percent(g?.video_encode_percent),decode:percent(g?.video_decode_percent)};
    Object.entries(values).forEach(([k,v])=>{$(`${k}Value`).textContent=v;});
    $('cpuExtra').textContent='Across all CPU cores';
    $('ramExtra').textContent=`${gib(ram.used_bytes)} / ${gib(ram.total_bytes)}`;
    $('gpuExtra').textContent=g?.name||'Driver or device unavailable';
    $('vramExtra').textContent=`of ${gib(g?.vram_total_bytes)} GPU memory`;
    $('cpuTempExtra').textContent=snapshot.cpu_temp_c==null?'CPU sensor unavailable':'Package / die sensor';
    $('gpuTempExtra').textContent=g?.temp_c==null?'GPU sensor unavailable':'GPU core sensor';
    $('encodeExtra').textContent=g?.video_encode_percent==null?'Driver data unavailable':'NVIDIA hardware engine';
    $('decodeExtra').textContent=g?.video_decode_percent==null?'Driver data unavailable':'NVIDIA hardware engine';
    putBar('cpuBar',snapshot.cpu_percent);putBar('ramBar',ram.percent);putBar('gpuBar',g?.percent);
    putBar('vramBar',vramPercent(g?.vram_used_bytes,g?.vram_total_bytes));
    putBar('encodeBar',g?.video_encode_percent);putBar('decodeBar',g?.video_decode_percent);
    $('lastUpdate').textContent=`Sample: ${when(snapshot.ts)} · ${Math.max(0,age(snapshot))}s ago`;
    $('deviceHint').textContent=g ? `${g.name} · ${snapshot.backend||'NVIDIA driver'} · ${g.process_list_supported ? 'GPU context tracking available' : 'GPU process tracking unavailable'}` :
      `CPU, RAM and CPU temperature continue recording independently of NVIDIA${snapshot.error ? ' · '+snapshot.error : ''}`;
  }
  function metricDetails(){
    const cfg=METRICS[state.metric];
    $('detailTitle').textContent=`${cfg.title} history`;
    $('detailEyebrow').textContent=`COMPONENT / ${cfg.title.toUpperCase()}`;
    $('detailDescription').textContent=cfg.description;
    $('chartTitle').textContent=cfg.title+' over time';
    $('chartUnit').textContent=cfg.unit==='%'?'UTILIZATION %':cfg.unit==='°C'?'TEMPERATURE °C':'ALLOCATED GIB';
    $('activeTitle').textContent=cfg.appTitle;
    $('activeDescription').textContent=cfg.appNote;
    $('sourceNote').textContent=state.metric.endsWith('Temp')?
      'Temperature sensors cannot measure heat contributed by individual applications. The process list shows relevant running workloads, not temperature ownership.':
      GPU_METRICS.has(state.metric) ? 'NVIDIA may omit system compositor processes or per-process GPU utilization depending on the driver and hardware.' :
      'System utilization and per-process consumption use different denominators. Process lists show a recent sample, not historical attribution.';
    document.querySelectorAll('[data-metric]').forEach(el=>{
      const selected=el.dataset.metric===state.metric;
      el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));
    });
    $('gpuHistorySection').hidden=!GPU_METRICS.has(state.metric);
    $('gpuChoice').hidden=!GPU_METRICS.has(state.metric)||!state.current?.gpus?.length;
    $('filterLive').value='';
    state.expanded=false;
    $('moreLiveBtn').textContent='Show more';
    $('moreLiveBtn').hidden=true;
    renderLive();drawHistory();
  }
  function selectMetric(key){
    if(!METRICS[key])return;
    state.metric=key;
    savePrefs();metricDetails();
    // Refresh old GPU historical process records only when useful.
    if(GPU_METRICS.has(key))loadPastProcesses();
  }
  function sortOptions(){
    const gpu=GPU_METRICS.has(state.metric);
    if(!gpu){
      return [{key:'name',label:'Application',format:p=>p.name},
              {key:'pid',label:'PID',format:p=>p.pid},
              {key:state.metric==='ram'?'rss_bytes':'cpu_percent',label:state.metric==='ram'?'RAM':'CPU',format:p=>state.metric==='ram'?mib(p.rss_bytes):percent(p.cpu_percent)},
              {key:state.metric==='ram'?'cpu_percent':'rss_bytes',label:state.metric==='ram'?'CPU':'RAM',format:p=>state.metric==='ram'?percent(p.cpu_percent):mib(p.rss_bytes)}];
    }
    const primary=state.metric==='vram'?'vram_bytes':state.metric==='encode'?'encode_percent':state.metric==='decode'?'decode_percent':'sm_percent';
    const alternate=primary==='vram_bytes'?'sm_percent':'vram_bytes';
    return [{key:'name',label:'Application',format:p=>p.name},
            {key:'pid',label:'PID',format:p=>p.pid},
            {key:primary,label:primary==='vram_bytes'?'VRAM':primary==='encode_percent'?'Encode':primary==='decode_percent'?'Decode':'GPU SM',format:p=>primary==='vram_bytes'?mib(p.vram_bytes):percent(p[primary])},
            {key:alternate,label:alternate==='vram_bytes'?'VRAM':'GPU SM',format:p=>alternate==='vram_bytes'?mib(p.vram_bytes):percent(p[alternate])}];
  }
  function liveProcesses(){
    const snapshot=state.current || {};
    if(GPU_METRICS.has(state.metric))return (snapshot.processes||[]).filter(p=>p.gpu_index===state.gpu);
    return snapshot.system_processes||[];
  }
  function compareBy(a,b,key,desc){
    const left=a[key],right=b[key];
    if(left==null&&right==null)return 0;
    if(left==null)return 1;if(right==null)return -1;
    const cmp=typeof left==='string'?String(left).localeCompare(String(right),undefined,{numeric:true}):Number(left)-Number(right);
    return desc ? -cmp : cmp;
  }
  function renderLive(){
    const cols=sortOptions(),defaultSort=cols[2].key;
    const setting=state.liveSort[state.metric]||{key:defaultSort,desc:true};
    if(!cols.some(c=>c.key===setting.key))setting.key=defaultSort;
    const head=$('liveHead'),r=make('tr');
    for(const col of cols){
      const th=make('th'),b=make('button','sort-button',col.label+(setting.key===col.key ? (setting.desc?' ↓':' ↑'):' ↕'));
      b.type='button';b.dataset.liveSort=col.key;
      b.setAttribute('aria-label',`Sort current processes by ${col.label}`);
      b.addEventListener('click',()=>{
        const setting=state.liveSort[state.metric]||{key:defaultSort,desc:true};
        state.liveSort[state.metric]={key:col.key,desc:setting.key===col.key?!setting.desc:col.key!=='name'};
        savePrefs();renderLive();
      });
      th.append(b);r.append(th);
    }
    head.replaceChildren(r);
    const query=$('filterLive').value.trim().toLowerCase();
    const all=liveProcesses().filter(p=>!query||`${p.name} ${p.pid}`.toLowerCase().includes(query))
      .sort((a,b)=>compareBy(a,b,setting.key,setting.desc));
    const limit=state.expanded?60:12,shown=all.slice(0,limit);
    const body=$('liveRows');body.replaceChildren();
    if(!shown.length){
      let message='No matching running processes.';
      if(!state.current)message='Waiting for collector…';
      else if(GPU_METRICS.has(state.metric))message=!gpuNow()?'GPU offline. No GPU processes available.':
        gpuNow().process_list_supported===false?'GPU process listing unavailable in this driver.':'No GPU process contexts reported in this sample.';
      else if(!Array.isArray(state.current.system_processes))message='Process telemetry starts after upgrading the background service.';
      const tr=make('tr'),td=make('td','empty-cell',message);td.colSpan=4;tr.append(td);body.append(tr);
    }
    for(const p of shown){
      const tr=make('tr');
      for(let i=0;i<cols.length;i++){
        const td=make('td',i===0?'app-name':'',cols[i].format(p));
        if(i===0)td.title=p.name||'';
        tr.append(td);
      }
      body.append(tr);
    }
    $('liveCount').textContent=`${all.length} current process${all.length===1?'':'es'}${all.length>shown.length?` · showing ${shown.length}`:''}`;
    const more=$('moreLiveBtn');
    more.hidden=all.length<=12;
    more.textContent=state.expanded?'Show fewer':'Show more';
  }

  function seriesValue(row,s){
    const v=s.transform?s.transform(row):row[s.key];
    return number(v);
  }
  function plot(id,rows,series,config={}){
    const canvas=$(id);if(!canvas)return;
    const tip=$(config.tip||`${id.replace(/Chart$/,'')}Tip`);
    const dims=canvas.getBoundingClientRect();
    const width=Math.max(220,Math.round(dims.width||canvas.parentElement?.clientWidth||450));
    const height=Math.max(150,Math.round(dims.height||260));
    const dpr=Math.min(2.5,Math.max(1,window.devicePixelRatio||1));
    if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    }
    const ctx=canvas.getContext('2d');if(!ctx)return;
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    const left=46,right=14,top=11,bottom=36,w=width-left-right,h=height-top-bottom;
    const numeric=rows.flatMap(r=>series.map(s=>seriesValue(r,s)).filter(v=>v!=null));
    const ceiling=config.fixedMax ?? Math.max(config.minimumMax||10,Math.ceil(Math.max(0,...numeric)*1.15/10)*10);
    const low=config.minimum??0;const ymax=Math.max(low+1,ceiling);
    // Time rather than array index controls x spacing. Missing intervals leave a gap.
    const now=nowSec();const rightTime=Math.max(now,rows.length?rows[rows.length-1].ts:now);
    const leftTime=rightTime-state.range;
    const x=ts=>left+Math.max(0,Math.min(1,(ts-leftTime)/Math.max(1,state.range)))*w;
    const y=v=>top+h-(Math.max(low,Math.min(ymax,v))-low)/(ymax-low)*h;
    ctx.font='11px system-ui,sans-serif';ctx.textBaseline='middle';ctx.textAlign='right';
    for(let i=0;i<=4;i++){
      const n=low+(ymax-low)*i/4,py=y(n);
      ctx.beginPath();ctx.strokeStyle='#e8edf5';ctx.lineWidth=1;ctx.moveTo(left,py);ctx.lineTo(width-right,py);ctx.stroke();
      ctx.fillStyle='#90a0b3';ctx.fillText(config.unit===' GiB'?n.toFixed(1):String(Math.round(n)),left-7,py);
    }
    ctx.textAlign='center';ctx.textBaseline='top';ctx.fillStyle='#8b9aaa';
    const tickCount=width<410?3:4;
    for(let i=0;i<tickCount;i++){
      const ts=leftTime+state.range*i/(tickCount-1);
      ctx.textAlign=i===0?'left':i===tickCount-1?'right':'center';
      ctx.fillText(shortTime(ts),x(ts),top+h+12);
    }
    const ok=rows.some(r=>series.some(s=>seriesValue(r,s)!=null));
    if(!ok){
      ctx.font='13px system-ui,sans-serif';ctx.textAlign='center';ctx.fillStyle='#9ba9b9';
      ctx.fillText(config.empty||'No recorded samples for this component',width/2,top+h/2);
    }
    for(const s of series){
      ctx.beginPath();let active=false;let lastTs=null;let points=0;
      for(const row of rows){
        const v=seriesValue(row,s);
        if(v==null){active=false;lastTs=null;continue;}
        const px=x(row.ts),py=y(v);
        // Surface missing samples rather than drawing a misleading flat line.
        if(!active||(lastTs!=null&&row.ts-lastTs>Math.max(4,state.bucketSeconds*2.5))){ctx.moveTo(px,py);}
        else ctx.lineTo(px,py);
        active=true;lastTs=row.ts;points++;
        if(rows.length<3){ctx.moveTo(px+2,py);ctx.arc?.(px,py,2.6,0,Math.PI*2);}
      }
      if(s.dashed)ctx.setLineDash?.([4,4]);
      ctx.strokeStyle=s.color;ctx.lineWidth=s.dashed?1.35:2.5;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();ctx.setLineDash?.([]);
    }
    let meta=chartEvents[id];
    if(!meta){
      meta={index:-1,pinned:false};chartEvents[id]=meta;
      const show=()=>{
        const d=meta;if(!d.rows?.length||d.index<0){if(d.tip)d.tip.hidden=true;return;}
        const row=d.rows[Math.min(d.index,d.rows.length-1)];
        d.tip.textContent=[when(row.ts),...d.series.map(s=>{
          const n=seriesValue(row,s);
          return `${s.name}: ${n==null?'N/A':n.toFixed(s.decimals??(s.unit===' GiB'?2:1))}${s.unit||'%'}`;
        })].join('\n');
        d.tip.hidden=false;
        const px=d.x(row.ts);d.tip.style.left=`${Math.max(5,Math.min(d.width-170,px+7))}px`;
      };
      const locate=(event,pin)=>{
        const mx=event.clientX-canvas.getBoundingClientRect().left;
        if(!meta.rows.length)return;
        let best=Infinity,index=0;
        meta.rows.forEach((row,i)=>{const delta=Math.abs(meta.x(row.ts)-mx);if(delta<best){best=delta;index=i;}});
        meta.index=index;if(pin)meta.pinned=!meta.pinned;show();
      };
      canvas.addEventListener('pointermove',e=>{if(!meta.pinned)locate(e,false);});
      canvas.addEventListener('pointerdown',e=>locate(e,true));
      canvas.addEventListener('pointerleave',()=>{if(!meta.pinned){meta.index=-1;meta.tip.hidden=true;}});
      canvas.addEventListener('keydown',e=>{
        if(e.key==='Escape'){meta.pinned=false;meta.index=-1;meta.tip.hidden=true;}
        else if(['ArrowLeft','ArrowRight'].includes(e.key)&&meta.rows.length){
          e.preventDefault();meta.index=Math.max(0,Math.min(meta.rows.length-1,(meta.index<0?0:meta.index)+(e.key==='ArrowRight'?1:-1)));
          meta.pinned=true;show();
        }
      });
      canvas.tabIndex=0;
    }
    meta.rows=rows;meta.series=series;meta.x=x;meta.tip=tip;meta.width=width;
    if(meta.index>=rows.length)meta.index=rows.length-1;
  }
  function drawHistory(){
    const cfg=METRICS[state.metric];const color=PALETTE[state.metric];
    const convert=r=>number(r[cfg.field])==null?null:r[cfg.field]/(cfg.factor||1);
    const peak=r=>number(r[cfg.peak])==null?null:r[cfg.peak]/(cfg.factor||1);
    const series=[{name:state.bucketSeconds>1?'Average':'Reading',transform:convert,color,unit:cfg.unit}];
    if(state.bucketSeconds>1)series.push({name:'Peak',transform:peak,color:'#9eacbc',dashed:true,unit:cfg.unit});
    const rows=state.history;
    const legend=$('chartLegend');legend.replaceChildren();
    for(const s of series){const span=make('span');const swatch=make('i','swatch');swatch.style.background=s.color;
      if(s.dashed)swatch.classList.add('dashed');span.append(swatch,document.createTextNode(s.name));legend.append(span);}
    plot('detailChart',rows,series,{tip:'detailTip',unit:cfg.unit,fixedMax:cfg.scale,
      minimumMax:cfg.unit==='°C'?90:cfg.unit===' GiB'?2:10,
      empty:GPU_METRICS.has(state.metric) ? 'No recorded GPU data or sensor unavailable' : 'No recorded samples for this component'});
    const bucket=state.bucketSeconds;
    $('bucketHint').textContent=rows.length?`${rows.length} time buckets · ${bucket}s per bucket · ${state.range===15?'15-second rolling window':state.range/60+'-minute window'}`:'No readings in this window';
  }
  function processKey(p){return `${p.gpu_index}:${p.pid}:${p.start_ticks}`;}
  function renderPastProcesses(){
    const q=$('filterHistory').value.trim().toLowerCase();
    const data=state.historicalProcesses.filter(p=>!q||`${p.name} ${p.pid} ${p.kind}`.toLowerCase().includes(q))
      .sort((a,b)=>compareBy(a,b,state.pastSortBy,state.pastDescending));
    const body=$('historyRows');body.replaceChildren();
    for(const p of data){
      const tr=make('tr','history-row');tr.tabIndex=0;tr.setAttribute('role','button');
      tr.setAttribute('aria-label',`Inspect history for ${p.name}, PID ${p.pid}`);
      if(state.selected&&processKey(state.selected)===processKey(p))tr.classList.add('selected');
      const cells=[p.name,p.pid,p.kind,percent(p.avg_sm_percent),percent(p.peak_sm_percent),
        gib(p.peak_vram_bytes),p.observations,when(p.last_seen)];
      cells.forEach((n,i)=>{const td=make('td',i===0?'app-name':'',n);tr.append(td);});
      tr.addEventListener('click',()=>selectProcess(p));
      tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectProcess(p);}});
      body.append(tr);
    }
    if(!data.length){const tr=make('tr'),td=make('td','empty-cell','No matching GPU process history for this period.');td.colSpan=8;tr.append(td);body.append(tr);}
    $('historyCount').textContent=`${state.historicalProcesses.length} recorded`;
    $('historyFooter').textContent=`${data.length} historical process${data.length===1?'':'es'} · Select a row to inspect its GPU timeline`;
  }
  function drawProcess(){
    if(!state.selected||$('inspect').hidden)return;
    plot('procSmChart',state.processHistory,[{name:'GPU SM',key:'sm_percent',unit:'%',color:PALETTE.gpu}],
      {tip:'procSmTip',fixedMax:100,unit:'%',empty:'Driver did not provide per-process SM samples'});
    plot('procMemChart',state.processHistory,[{name:'VRAM',unit:' GiB',color:PALETTE.vram,
      transform:r=>number(r.vram_bytes)==null?null:r.vram_bytes/1073741824}],
      {tip:'procMemTip',unit:' GiB',minimumMax:1,empty:'No per-process VRAM samples'});
  }
  async function selectProcess(p){
    state.selected=p;state.processHistory=[];
    $('inspect').hidden=false;
    $('inspectTitle').textContent=p.name;
    $('inspectMeta').textContent=`PID ${p.pid} · ${p.kind} · Last observed ${when(p.last_seen)} · Peak GPU SM ${percent(p.peak_sm_percent)} · Peak VRAM ${gib(p.peak_vram_bytes)}`;
    renderPastProcesses();drawProcess();
    await loadProcessHistory();
    $('inspect').scrollIntoView({block:'nearest',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }
  async function loadProcessHistory(){
    if(!state.selected)return;
    const p=state.selected,serial=++state.processSerial,range=state.range;
    try{
      const query=new URLSearchParams({range,gpu:p.gpu_index,pid:p.pid,start:p.start_ticks});
      const result=await json(`/api/process-history?${query}`);
      if(serial===state.processSerial&&state.selected&&processKey(state.selected)===processKey(p)){
        state.processHistory=result.rows||[];drawProcess();
      }
    }catch(e){console.warn('Per-process history:',e.message);}
  }
  async function loadPastProcesses(){
    if(!GPU_METRICS.has(state.metric))return;
    const serial=state.historySerial,range=state.range,gpu=state.gpu;
    if(gpu<0){state.historicalProcesses=[];renderPastProcesses();return;}
    try{
      const query=new URLSearchParams({range,gpu});
      const response=await json(`/api/processes?${query}`);
      if(serial===state.historySerial&&range===state.range&&gpu===state.gpu){
        state.historicalProcesses=response.rows||[];renderPastProcesses();
      }
    }catch(e){console.warn('Past GPU processes:',e.message);}
  }
  async function loadHistory(){
    const serial=++state.historySerial,range=state.range,gpu=state.gpu;
    try{
      const query=new URLSearchParams({range,gpu});
      const data=await json(`/api/history?${query}`);
      if(serial!==state.historySerial||gpu!==state.gpu||range!==state.range)return;
      state.history=data.rows||[];state.bucketSeconds=data.bucket_seconds||1;drawHistory();
      await loadPastProcesses();
      if(state.selected)await loadProcessHistory();
    }catch(e){
      if(serial!==state.historySerial)return;
      $('bucketHint').textContent=`Historical readings unavailable (${e.message})`;
      console.warn('Historical telemetry:',e.message);
    }
  }
  async function loadCurrent(){
    if(!state.live||state.currentPending)return;
    state.currentPending=true;
    const oldGPU=state.gpu;
    try{
      const snapshot=await json('/api/current');
      if(!state.live)return;
      state.current=snapshot;updateGpuOptions(snapshot);updateCards(snapshot);renderLive();
      if(oldGPU!==state.gpu)loadHistory();
      connection(age(snapshot)<8,age(snapshot)<8?'Collector online · 1s sampling':'Collector appears stale');
    }catch(e){connection(false,'Collector disconnected');console.warn('Current telemetry:',e.message);}
    finally{state.currentPending=false;}
  }
  function chooseRange(value){
    if(![15,60,1800,3600,21600,86400,604800].includes(value))return;
    state.range=value;savePrefs();
    document.querySelectorAll('[data-range]').forEach(button=>{
      const active=Number(button.dataset.range)===value;
      button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    });
    // Keep current selected app, but invalidate its existing time range.
    state.processHistory=[];
    drawHistory();loadHistory();
  }
  function exportCsv(){
    const columns=['ts','cpu_percent','cpu_percent_peak','ram_percent','ram_percent_peak','ram_used_bytes','ram_used_bytes_peak',
      'ram_total_bytes','cpu_temp_c','cpu_temp_c_peak','gpu_percent','gpu_percent_peak','gpu_temp_c','gpu_temp_c_peak',
      'vram_used_bytes','vram_used_bytes_peak','vram_total_bytes','gpu_mem_percent','video_encode_percent',
      'video_encode_percent_peak','video_decode_percent','video_decode_percent_peak','sample_count'];
    const escape=x=>{
      let s=String(x??'').replace(/[\u0000-\u001F]/g,' ');
      if(/^[=+@\-\t\r]/.test(s))s="'"+s; // spreadsheet formula injection prevention
      return '"'+s.replaceAll('"','""')+'"';
    };
    const table=[['FACO Resource Watch','All-component history',`Window: ${state.range}s`,`Bucket: ${state.bucketSeconds}s`,`GPU: ${state.gpu}`],
      columns,...state.history.map(row=>columns.map(k=>row[k]??'')),[],
      ['Historical NVIDIA GPU processes (visible selected window)'],
      ['App','PID','Start ticks','GPU','Context','Avg SM %','Peak SM %','Peak VRAM bytes','Samples','First seen','Last seen'],
      ...state.historicalProcesses.map(p=>[p.name,p.pid,p.start_ticks,p.gpu_index,p.kind,p.avg_sm_percent,p.peak_sm_percent,p.peak_vram_bytes,p.observations,p.first_seen,p.last_seen])];
    const blob=new Blob([table.map(row=>row.map(escape).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=make('a');a.href=url;
    a.download=`FACO_All_Components_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  document.querySelectorAll('[data-metric]').forEach(button=>button.addEventListener('click',()=>selectMetric(button.dataset.metric)));
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>chooseRange(Number(button.dataset.range))));
  document.querySelectorAll('[data-history-sort]').forEach(button=>button.addEventListener('click',()=>{
    const key=button.dataset.historySort;
    state.pastDescending=state.pastSortBy===key?!state.pastDescending:key!=='name';
    state.pastSortBy=key;renderPastProcesses();
  }));
  $('filterLive').addEventListener('input',renderLive);
  $('filterHistory').addEventListener('input',renderPastProcesses);
  $('moreLiveBtn').addEventListener('click',()=>{state.expanded=!state.expanded;renderLive();});
  $('exportBtn').addEventListener('click',exportCsv);
  $('gpuSelect').addEventListener('change',()=>{
    state.gpu=Number($('gpuSelect').value);savePrefs();
    state.selected=null;$('inspect').hidden=true;
    state.historicalProcesses=[];if(state.current)updateCards(state.current);
    renderLive();loadHistory();
  });
  $('pauseBtn').addEventListener('click',()=>{
    state.live=!state.live;
    $('pauseBtn').setAttribute('aria-pressed',String(!state.live));
    $('pauseBtn').querySelector('span').textContent=state.live?'Pause display':'Resume display';
    connection(state.live,state.live?'Collector online':'Display paused · logging continues');
    if(state.live){loadCurrent();loadHistory();}
  });
  $('closeInspect').addEventListener('click',()=>{
    state.selected=null;state.processHistory=[];state.processSerial++;
    $('inspect').hidden=true;renderPastProcesses();
  });
  // Redraw on size changes, never create a second interval/listener set.
  if('ResizeObserver' in window){
    let pending=false;
    const observer=new ResizeObserver(()=>{
      if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;drawHistory();drawProcess();});
    });
    document.querySelectorAll('.canvas-wrap').forEach(n=>observer.observe(n));
  }else window.addEventListener('resize',()=>{drawHistory();drawProcess();});
  chooseRange(state.range);
  metricDetails();
  loadCurrent();
  setInterval(()=>{
    if(!state.live)return;
    loadCurrent();
    // 1s and 1m windows really update every second. Long spans are cached
    // longer to avoid 7-day database scans 86,400 times per day.
    const cadence=state.range<=60?1:state.range<=3600?5:state.range<=21600?10:30;
    if(nowSec()%cadence===0)loadHistory();
  },1000);
})();
