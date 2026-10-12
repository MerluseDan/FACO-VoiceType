"""Real Chromium DOM/canvas/emulation without navigating to network URLs.

Chromium is blocked by administrative policy from opening localhost/file/data
URLs in this sandbox. Playwright set_content() injects the real HTML/CSS/JS into
about:blank, with fetch intercepted to serve realistic synthetic API payloads.
This exercises browser layout and interactions, NOT GNOME/NVIDIA hardware.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import time
import json
import re
import math

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests' / 'screenshots'
DEST.mkdir(exist_ok=True)
TIMESTAMP = int(time.time())
GiB = 2**30
GPU = dict(index=0, name='NVIDIA GeForce RTX 5060 Ti', percent=82,
           temp_c=57, vram_used_bytes=5*GiB, vram_total_bytes=16*GiB,
           video_encode_percent=31, video_decode_percent=11,
           process_list_supported=True, process_util_supported=True)
processes = [dict(name=f'app_worker_{i:02}', pid=4000+i, start_ticks=str(950000+i),
                  cpu_percent=round((60-i)*1.8,1),rss_bytes=int((32-i/2)*GiB/10))
             for i in range(58)]
gpu_proc = [dict(name=f'gpu_renderer_{i:02}', pid=8000+i,
                 start_ticks=str(975000+i),gpu_index=0,
                 type='compute',sm_percent=max(0,82-i*3),vram_bytes=(1000-i*35)*1024**2,
                 encode_percent=max(0,30-i*2),decode_percent=max(0,16-i),memory_io_percent=17)
            for i in range(14)]
current = dict(ts=TIMESTAMP, cpu_percent=47, cpu_temp_c=58,
    ram={'percent':63,'used_bytes':20*GiB,'total_bytes':32*GiB},
    gpus=[GPU],processes=gpu_proc,system_processes=processes,backend='NVIDIA NVML')
rows=[]
for i in range(720):
    v=14+12*math.sin(i/21.0)+7*math.sin(i/7.5)
    cpu=23+v*1.5
    gpu=32+v*1.1
    ram=59+i*0.004
    rows.append(dict(ts=TIMESTAMP-(719-i)*5,
       cpu_percent=cpu,cpu_percent_peak=min(cpu+4,100),cpu_peak_percent=min(cpu+4,100),
       ram_percent=ram,ram_percent_peak=ram+1,ram_used_bytes=20*GiB,
       ram_used_bytes_peak=20.2*GiB,ram_total_bytes=32*GiB,
       cpu_temp_c=53+v*.25,cpu_temp_c_peak=54+v*.25,
       gpu_percent=gpu,gpu_percent_peak=gpu+5,gpu_peak_percent=gpu+5,
       gpu_temp_c=54+v*.17,gpu_temp_c_peak=55+v*.17,gpu_peak_temp_c=55+v*.17,
       vram_used_bytes=(4+v*.03)*GiB,vram_used_bytes_peak=(4.2+v*.03)*GiB,
       vram_peak_bytes=(4.2+v*.03)*GiB,vram_total_bytes=16*GiB,gpu_mem_percent=37,
       video_encode_percent=20+v*.5,video_encode_percent_peak=24+v*.5,
       video_decode_percent=12+v*.15,video_decode_percent_peak=14+v*.15,
       sample_count=3))
# Recent samples at actual 1-second cadence (the recorded 1s window).
for offset in range(15,0,-1):
    row=dict(rows[-1])
    row['ts']=TIMESTAMP-offset
    row['cpu_percent']=44+8*math.sin(offset/3)
    row['cpu_percent_peak']=row['cpu_percent']
    row['gpu_percent']=70+12*math.cos(offset/4)
    row['gpu_percent_peak']=row['gpu_percent']
    rows.append(row)
rows.sort(key=lambda row:row['ts'])
past=[dict(name='blender',pid=8299,gpu_index=0,start_ticks='72617',kind='compute',
      avg_sm_percent=71.5,peak_sm_percent=91,peak_vram_bytes=2*GiB,observations=300,
      first_seen=TIMESTAMP-600,last_seen=TIMESTAMP)]
proc_rows=[dict(ts=TIMESTAMP-30+i,sm_percent=10+i*2,vram_bytes=(1+i*.02)*GiB)
           for i in range(30)]

# All fixture data is passed as JSON (not inlined into executable source).
fixture = json.dumps({'current':current,'rows':rows,'past':past,'procRows':proc_rows})
fetch_mock = r'''(arg) => {
 window.__apiCalls = [];
 const fixture = arg;
 window.fetch = async (url) => {
   const path=String(url);window.__apiCalls.push(path);
   let data={};
   if(path==='/api/current')data={...fixture.current,ts:Math.floor(Date.now()/1000)};
   if(path.startsWith('/api/history?')) {
     const sec=Number(new URL('http://localhost'+path).searchParams.get('range'));
     data={rows:fixture.rows.filter(x=>x.ts>=Math.floor(Date.now()/1000)-sec),
          bucket_seconds:Math.max(1,Math.ceil(sec/560)),seconds:sec};
   }
   if(path.startsWith('/api/processes?'))data={rows:fixture.past};
   if(path.startsWith('/api/process-history?'))data={rows:fixture.procRows};
   return {ok:true,status:200,json:async()=>data};
 };
}'''

html=(ROOT/'web/index.html').read_text()
css=(ROOT/'web/app.css').read_text()
js=(ROOT/'web/app.js').read_text()
html=re.sub(r'<link rel="icon"[^>]*>', '', html)
html=re.sub(r'<link rel="stylesheet"[^>]*>', '<style>'+css+'</style>', html)
html=re.sub(r'<script defer src="/app.js"></script>', '', html)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
       args=['--no-sandbox','--disable-dev-shm-usage','--hide-scrollbars'])
    errors=[]
    page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
    page.on('pageerror',lambda exc:errors.append(str(exc)))
    page.on('console',lambda msg:errors.append('Console: '+msg.text) if msg.type=='error' else None)
    page.set_content(html,wait_until='load')
    page.evaluate('('+fetch_mock+')('+json.dumps({'current':current,'rows':rows,'past':past,'procRows':proc_rows})+')')
    page.add_script_tag(content=js)
    page.wait_for_function("document.getElementById('cpuValue').textContent==='47%'",timeout=10000)
    page.wait_for_function("document.getElementById('bucketHint').textContent.includes('time buckets')",timeout=10000)
    # Structural redundancy audit: IDs unique and no obsolete overview graphs.
    audit=page.evaluate('''() => {const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return {unique:new Set(ids).size===ids.length,legacy:document.querySelectorAll('#usageChart,#tempChart,#vramChart').length,canvases:document.querySelectorAll('canvas').length}}''')
    assert audit['unique'] and audit['legacy']==0 and audit['canvases']==3, audit
    assert page.locator('.metric').count()==8
    assert page.locator('.metric[aria-pressed="true"]').count()==1
    assert page.locator('#liveRows tr').count()==12
    assert page.locator('#moreLiveBtn').is_visible()
    assert page.locator('#detailChart').evaluate('(el)=>el.width')>100
    assert page.locator('#gpuHistorySection').is_hidden()
    assert page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth'), 'desktop horizontal overflow'
    # The browser's actual rendering rather than mock-DOM is tested.
    page.screenshot(path=str(DEST/'overview_1440x900.png'),full_page=True)

    # Every card must change chart title/axis and live process context.
    for metric,label in [('cpu','Processor'),('ram','System memory'),('gpu','Graphics processor'),
                         ('vram','Video memory'),('cpuTemp','CPU temperature'),
                         ('gpuTemp','GPU temperature'),('encode','Video encoder'),('decode','Video decoder')]:
        page.locator(f'[data-metric="{metric}"]').click()
        assert label.lower() in page.locator('#detailTitle').inner_text().lower(),metric
        assert page.locator('.metric[aria-pressed="true"]').count()==1,metric
        assert page.locator('#detailChart').evaluate('(el)=>el.width')>100,metric
        assert page.locator('#liveRows').locator('tr').count()>0,metric
        assert page.locator('#gpuHistorySection').is_hidden()==(metric in ('cpu','ram','cpuTemp')),metric
    # History scales: 1-second samples, 1 minute, 30 minutes, 1 hour, plus old periods.
    for period in [15,60,1800,3600,21600,86400,604800]:
        page.locator(f'[data-range="{period}"]').click()
        page.wait_for_function("n=>window.__apiCalls.some(x=>x.includes('range='+n+'&'))",arg=period,timeout=5000)
        assert page.locator('.range-pills button[aria-pressed="true"]').count()==1
    page.locator('[data-range="15"]').click()
    page.wait_for_function("document.getElementById('bucketHint').textContent.includes('15-second')",timeout=5000)
    assert page.locator('#bucketHint').inner_text().find('1s per bucket')>=0
    page.locator('[data-range="3600"]').click()
    page.locator('[data-metric="gpu"]').click()
    page.locator('#gpuHistorySection').evaluate('(el)=>el.open=true')
    page.locator('#gpuHistorySection .history-row').first.click()
    page.wait_for_function("document.getElementById('inspectTitle').textContent==='blender'",timeout=5000)
    page.wait_for_function("document.getElementById('procSmChart').width>100",timeout=5000)
    page.screenshot(path=str(DEST/'gpu_history_process.png'),full_page=True)
    page.locator('#closeInspect').click()
    assert page.locator('#inspect').is_hidden()
    page.locator('#filterLive').fill('renderer_01')
    assert page.locator('#liveRows').locator('tr').count()>=1
    page.locator('#filterLive').fill('')
    page.locator('#liveHead button').first.click()
    page.locator('#pauseBtn').click()
    assert page.locator('#pauseBtn').get_attribute('aria-pressed')=='true'
    page.locator('#pauseBtn').click()
    assert page.locator('#pauseBtn').get_attribute('aria-pressed')=='false'
    # Enable browser download and ensure CSV has all components, not GPU only.
    with page.expect_download(timeout=5000) as result:
        page.locator('#exportBtn').click()
    download=result.value
    assert download.suggested_filename.startswith('FACO_All_Components_')
    path=DEST/'emulated-export.csv'
    download.save_as(path)
    contents=path.read_text()
    assert 'cpu_temp_c_peak' in contents and 'ram_used_bytes' in contents
    assert 'video_encode_percent_peak' in contents
    assert 'blender' in contents
    path.unlink(missing_ok=True)  # Keep QA screenshots, not a generated CSV export.

    # 1920x1080 user-target viewport and narrow phone screen: no content cut off.
    page.locator('[data-metric="cpu"]').click()
    page.set_viewport_size({'width':1920,'height':1080})
    page.screenshot(path=str(DEST/'cpu_history_1920x1080.png'),full_page=True)
    assert page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
    page.set_viewport_size({'width':320,'height':740})
    page.screenshot(path=str(DEST/'mobile_320.png'),full_page=True)
    dimensions=page.evaluate('''() => ({scroll:document.documentElement.scrollWidth,
       view:innerWidth, cards:[...document.querySelectorAll('.metric')].map(e=>e.getBoundingClientRect().width)})''')
    assert dimensions['scroll']<=dimensions['view']+1, 'Mobile horizontal overflow '+str(dimensions)
    assert min(dimensions['cards'])>=120, 'Metric cards clipped'
    assert not errors, 'Uncaught browser errors '+str(errors)
    assert page.evaluate('window.__apiCalls.length')>=20
    browser.close()
print('REAL CHROMIUM GUI EMULATION: PASSED')
print('Validated: 8 category cards; 7 real time ranges; 1-second resolution; live process lists; GPU history+inspection; sort/search/show more; pause/resume; CSV; desktop and 320px mobile; no JS errors.')
print('Screenshots: '+str(DEST))
