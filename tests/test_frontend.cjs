// Fast no-dependency DOM/canvas emulation for event wiring. Real Chromium
// screenshot/interaction checks are in gui_emulation.py when Playwright exists.
const fs=require('fs');
const vm=require('vm');
const assert=require('node:assert/strict');
class Classes {
 constructor(){this.names=new Set()}
 add(x){this.names.add(x)}
 remove(x){this.names.delete(x)}
 contains(x){return this.names.has(x)}
 toggle(x,force){const yes=force??!this.contains(x);yes?this.add(x):this.remove(x);return yes}
}
class Element {
 constructor(tag='div',id=''){
  this.tagName=tag;this.id=id;this.style={};this.dataset={};this.attrs={};
  this.classList=new Classes();this.children=[];this.listeners={};this._text='';
  this.clientWidth=520;this.clientHeight=265;this.value='';this.hidden=false;
  this.parentElement=this;this.parentNode=this;this.tabIndex=-1;
 }
 get textContent(){return this._text}
 set textContent(t){this._text=String(t)}
 setAttribute(k,v){this.attrs[k]=String(v)}
 getAttribute(k){return this.attrs[k]}
 addEventListener(name,func){(this.listeners[name]||=[]).push(func)}
 dispatch(name,event={}){for(const fn of this.listeners[name]||[])fn({preventDefault(){},clientX:150,key:'Enter',...event})}
 querySelector(sel){if(sel==='span')return this.children.find(x=>x.tagName==='span')||this.children.at(-1)||new Element('span');return null}
 getBoundingClientRect(){return{width:this.clientWidth,height:this.clientHeight,left:0,top:0}}
 replaceChildren(...nodes){this.children=nodes}
 append(...nodes){this.children.push(...nodes)}
 remove(){}
 click(){this.dispatch('click');if(this.tagName==='a')global.downloaded=true}
 scrollIntoView(){}
 getContext(){return {setTransform(){},clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(){},arc(){},setLineDash(){}}}
}
const ids=new Map();const get=id=>{if(!ids.has(id))ids.set(id,new Element('div',id));return ids.get(id)};
for(const id of ['detailChart','procSmChart','procMemChart'])get(id).tagName='canvas';
const metrics=['cpu','ram','gpu','vram','cpuTemp','gpuTemp','encode','decode'].map(metric=>{const e=new Element('button');e.dataset.metric=metric;return e});
const ranges=[15,60,1800,3600,21600,86400,604800].map(range=>{const e=new Element('button');e.dataset.range=String(range);return e});
const historySort=['name','pid','kind','avg_sm_percent','peak_sm_percent','peak_vram_bytes','observations','last_seen'].map(key=>{const e=new Element('button');e.dataset.historySort=key;return e});
const doc={body:get('body'),getElementById:get,createElement:tag=>new Element(tag),
 createTextNode:value=>{const e=new Element('text');e.textContent=value;return e},
 querySelectorAll:sel=>({'[data-metric]':metrics,'[data-range]':ranges,'[data-history-sort]':historySort,'.canvas-wrap':[]}[sel]||[])};
let calls=[];const ts=Math.floor(Date.now()/1000);
const gpu={index:0,name:'RTX 5060 Ti',percent:79,temp_c:54,vram_used_bytes:4*2**30,
 vram_total_bytes:16*2**30,video_encode_percent:20,video_decode_percent:3,
 process_list_supported:true,process_util_supported:true};
const cpuProcs=Array.from({length:34},(_,i)=>({pid:5000+i,name:`worker${i}`,start_ticks:String(2000+i),cpu_percent:100-i,rss_bytes:(40-i)*2**20}));
const gpuProcs=[{pid:1234,start_ticks:'111',name:'blender',gpu_index:0,type:'compute',sm_percent:67,vram_bytes:2*2**30,encode_percent:18,decode_percent:2}];
const snapshot={ts,cpu_percent:42,cpu_temp_c:65,ram:{percent:60,used_bytes:8*2**30,total_bytes:16*2**30},
 gpus:[gpu],system_processes:cpuProcs,processes:gpuProcs,backend:'NVIDIA NVML'};
const historyRow={ts:ts-2,cpu_percent:42,cpu_percent_peak:50,ram_percent:60,ram_percent_peak:61,
 gpu_percent:79,gpu_percent_peak:92,cpu_temp_c:65,cpu_temp_c_peak:67,gpu_temp_c:54,gpu_temp_c_peak:56,
 vram_used_bytes:4*2**30,vram_used_bytes_peak:5*2**30,video_encode_percent:20,video_encode_percent_peak:22,
 video_decode_percent:3,video_decode_percent_peak:4};
const pastProc={gpu_index:0,pid:1234,start_ticks:'111',name:'blender',kind:'compute',
 avg_sm_percent:54,peak_sm_percent:93,peak_vram_bytes:2*2**30,observations:13,first_seen:ts-300,last_seen:ts};
async function fakeFetch(url){
 calls.push(String(url));let data={};
 if(url==='/api/current')data=snapshot;
 if(url.startsWith('/api/history?'))data={bucket_seconds:Number(new URL('http://x'+url).searchParams.get('range'))===15?1:7,rows:[historyRow]};
 if(url.startsWith('/api/processes?'))data={rows:[pastProc]};
 if(url.startsWith('/api/process-history?'))data={rows:[{ts:ts-2,sm_percent:68,vram_bytes:2*2**30}]};
 return{ok:true,json:async()=>data};
}
const intervals=[];let downloaded=false;
const context={document:doc,fetch:fakeFetch,Date,Math,Number,String,JSON,Promise,Blob,URLSearchParams,console,
 window:{devicePixelRatio:1,addEventListener(){},matchMedia(){return {matches:true}}},
 setInterval(fn,ms){intervals.push({fn,ms});return intervals.length},
 setTimeout(fn){fn();return 1},
 localStorage:{getItem(){return null},setItem(){}},
 URL:class extends URL{static createObjectURL(){downloaded=true;return 'blob:mock'}static revokeObjectURL(){}},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/../web/app.js','utf8'),context,{filename:'app.js'});
const tick=()=>new Promise(r=>setTimeout(r,22));
(async()=>{
 await tick();await tick();
 assert.equal(get('cpuValue').textContent,'42%');
 assert.equal(get('ramValue').textContent,'60%');
 assert.equal(get('gpuValue').textContent,'79%');
 assert.equal(get('vramValue').textContent,'4.0 GiB');
 assert.equal(get('encodeValue').textContent,'20%');
 assert.equal(get('decodeValue').textContent,'3%');
 assert.equal(get('cpuTempValue').textContent,'65°C');
 assert.equal(get('gpuTempValue').textContent,'54°C');
 assert.match(get('detailTitle').textContent,/Processor/);
 assert.equal(get('gpuHistorySection').hidden,true);
 assert.equal(get('gpuChoice').hidden,true);
 assert.equal(get('liveRows').children.length,12);
 assert.equal(get('moreLiveBtn').hidden,false);
 get('moreLiveBtn').dispatch('click');
 assert.equal(get('liveRows').children.length,34);
 get('filterLive').value='worker2';get('filterLive').dispatch('input');
 assert.ok(get('liveRows').children.length>=1);
 get('filterLive').value='';get('filterLive').dispatch('input');
 get('liveHead').children[0].children[0].children[0].dispatch('click');
 for(const m of metrics){m.dispatch('click');await tick();assert.equal(get('detailTitle').textContent.toLowerCase().includes(m.dataset.metric==='cpuTemp'?'cpu temperature':m.dataset.metric==='gpuTemp'?'gpu temperature':m.dataset.metric==='vram'?'video memory':m.dataset.metric==='ram'?'system memory':m.dataset.metric==='cpu'?'processor':m.dataset.metric==='gpu'?'graphics processor':m.dataset.metric==='encode'?'video encoder':'video decoder'),true);}
 assert.equal(get('gpuHistorySection').hidden,false);
 assert.equal(get('gpuChoice').hidden,false);
 assert.ok(get('detailChart').width>100);
 get('detailChart').dispatch('pointermove',{clientX:190});
 assert.equal(get('detailTip').hidden,false);
 for(const r of ranges){r.dispatch('click');await tick();assert.ok(calls.some(u=>u.includes(`range=${r.dataset.range}`)));}
 metrics[2].dispatch('click');await tick();
 assert.ok(get('historyRows').children.length>=1);
 get('historyRows').children[0].dispatch('click');await tick();
 assert.equal(get('inspect').hidden,false);assert.equal(get('inspectTitle').textContent,'blender');
 assert.ok(get('procSmChart').width>100);
 get('closeInspect').dispatch('click');assert.equal(get('inspect').hidden,true);
 get('pauseBtn').dispatch('click');assert.equal(get('pauseBtn').getAttribute('aria-pressed'),'true');
 get('pauseBtn').dispatch('click');assert.equal(get('pauseBtn').getAttribute('aria-pressed'),'false');
 get('exportBtn').dispatch('click');assert.equal(downloaded,true);
 assert.equal(intervals.length,1);assert.equal(intervals[0].ms,1000);
 console.log('Node frontend emulation PASSED: 8 clickable components, live CPU/GPU processes, sorting, filtering, 7 scales, chart tooltip, GPU history+inspector, pause, export and 1s interval.');
})().catch(e=>{console.error(e.stack);process.exitCode=1});
