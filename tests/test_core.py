import json
import ctypes
import shutil
import subprocess
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from faco_watch import collector, storage
from faco_watch.server import make_server
from faco_watch.service import SamplerThread, atomic_json
from faco_watch.gpu import GpuSampler, _smi_fallback, NVML


def fake_snapshot(ts, activity=71, with_gpu=True):
    gpu = {
        'index':0,'name':'NVIDIA GeForce RTX 5060 Ti', 'percent':activity,
        'memory_controller_percent':28, 'temp_c':49, 'vram_used_bytes':3221225472,
        'vram_total_bytes':17179869184, 'video_encode_percent':12,
        'video_decode_percent':4,'process_list_supported':True,
        'process_util_supported':True,
    }
    p = {'gpu_index':0,'pid':1234,'start_ticks':'67291', 'name':'blender',
         'type':'compute + graphics','vram_bytes':2147483648,
         'sm_percent':65,'memory_io_percent':33,'encode_percent':0,'decode_percent':0}
    return {'ts':ts,'cpu_percent':32,'cpu_temp_c':57,
            'ram':{'percent':45,'used_bytes':8053063680,'total_bytes':17179869184},
            'gpus':[gpu] if with_gpu else [],'processes':[p] if with_gpu else [],
            'backend':'fake-qa', 'error':None}


class CpuTests(unittest.TestCase):
    def test_cpu_delta_and_iowait(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'stat').write_text('cpu  100 0 50 850 0 0 0 0 0 0\n')
            reader=collector.CpuSampler(root)
            self.assertIsNone(reader.sample())
            (root/'stat').write_text('cpu  120 0 70 910 0 0 0 0 0 0\n')
            self.assertEqual(reader.sample(), 40.0)
            (root/'stat').write_text('invalid')
            self.assertIsNone(reader.sample())

    def test_memavailable(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 200 kB\nMemFree: 1 kB\n')
            r=collector.memory_stats(Path(d))
            self.assertEqual(r['percent'],80)
            self.assertEqual(r['used_bytes'],800*1024)

    def test_temperature_selects_cpu_package_not_nvme(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=root/'hwmon';t=root/'thermal'
            t.mkdir();(h/'hwmon0').mkdir(parents=True)
            (h/'hwmon0'/'name').write_text('coretemp')
            (h/'hwmon0'/'temp1_label').write_text('Package id 0')
            (h/'hwmon0'/'temp1_input').write_text('65000')
            (h/'hwmon0'/'temp2_label').write_text('Core 0')
            (h/'hwmon0'/'temp2_input').write_text('72000')
            (h/'hwmon1').mkdir()
            (h/'hwmon1'/'name').write_text('nvme')
            (h/'hwmon1'/'temp1_input').write_text('83000')
            self.assertEqual(collector.cpu_temperature(h,t),65)

    def test_cpu_temperature_when_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(collector.cpu_temperature(Path(d),Path(d)))

    def test_proc_identity_starttime(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'123';p.mkdir()
            # Fields after comm begin at field 3. starttime=field 22=index 19.
            post=['S'] + ['0']*18 + ['998877']+['0']*6
            (p/'stat').write_text('123 (my (renderer)) '+' '.join(post))
            (p/'comm').write_text('blender\n')
            self.assertEqual(collector.process_identity(123,root),('blender','998877'))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'history.sqlite3'
        self.conn=storage.connect(self.path)
        self.now=int(time.time())

    def tearDown(self):
        self.conn.close();self.temp.cleanup()

    def test_write_gpu_per_app_and_history(self):
        storage.save(self.conn,fake_snapshot(self.now-6,20))
        storage.save(self.conn,fake_snapshot(self.now-4,97))
        storage.save(self.conn,fake_snapshot(self.now-2,55))
        h=storage.query_history(self.conn,60,0,now=self.now)
        self.assertTrue(h['rows'])
        self.assertGreaterEqual(max(r['gpu_peak_percent'] for r in h['rows']),97)
        self.assertGreaterEqual(max(r['cpu_percent'] for r in h['rows']),32)
        processes=storage.query_process_summary(self.conn,60,0,now=self.now)['rows']
        self.assertEqual(len(processes),1)
        self.assertEqual(processes[0]['name'],'blender')
        self.assertEqual(processes[0]['peak_sm_percent'],65)
        proc=storage.query_process_history(self.conn,60,0,1234,'67291',self.now)
        self.assertTrue(proc['rows'])
        self.assertFalse(storage.query_process_history(self.conn,60,0,1234,'other',self.now)['rows'])

    def test_pid_reuse_keeps_history_separate(self):
        s=fake_snapshot(self.now)
        storage.save(self.conn,s)
        s['ts']+=1;s['processes'][0]['start_ticks']='67999';s['processes'][0]['name']='other_app'
        storage.save(self.conn,s)
        procs=storage.query_process_summary(self.conn,60,0,now=self.now+1)['rows']
        self.assertEqual(len(procs),2)

    def test_missing_gpu_still_records_cpu(self):
        storage.save(self.conn, fake_snapshot(self.now,with_gpu=False))
        h=storage.query_history(self.conn,60,-1,now=self.now)
        self.assertEqual(len(h['rows']),1)
        self.assertIsNone(h['rows'][0]['gpu_percent'])

    def test_seven_day_retention(self):
        storage.save(self.conn, fake_snapshot(self.now-9*86400))
        storage.save(self.conn, fake_snapshot(self.now))
        storage.prune(self.conn,self.now)
        self.assertEqual(self.conn.execute('select count(*) from samples').fetchone()[0],2)
        self.assertEqual(self.conn.execute('select count(*) from process_samples').fetchone()[0],1)

    def test_limits_and_large_history_buckets(self):
        self.assertEqual(storage.clamp_range(-100),15)
        self.assertEqual(storage.clamp_range('oops'),3600)
        self.assertEqual(storage.clamp_range(999999999),604800)
        self.assertLessEqual(604800/storage.group_step(604800),560)
        self.assertEqual(storage.gpu_option('x'),0)

    def test_missing_external_mount_does_not_create_path(self):
        target=Path('/media/faco-test/FACO_WATCH_UnitTest_NotMounted/Apps/history.sqlite3')
        with self.assertRaises(OSError):
            storage.connect(target)
        self.assertFalse(target.exists())

    def test_wal_multi_connection(self):
        storage.save(self.conn, fake_snapshot(self.now))
        second=storage.connect(self.path)
        try:self.assertEqual(second.execute('SELECT COUNT(*) FROM samples').fetchone()[0],2)
        finally:second.close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbpath=Path(self.tmp.name)/'history.sqlite3'
        self.curr=Path(self.tmp.name)/'latest.json'
        con=storage.connect(self.dbpath)
        storage.save(con, fake_snapshot(int(time.time())))
        con.close()
        atomic_json(self.curr,fake_snapshot(int(time.time())))
        self.patch_db=mock.patch('faco_watch.storage.db_path',return_value=self.dbpath)
        self.patch_live=mock.patch('faco_watch.server.current_path',return_value=self.curr)
        self.patch_db.start();self.patch_live.start()
        self.server=make_server(0)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        self.patch_db.stop();self.patch_live.stop();self.tmp.cleanup()

    def fetch(self,url='/',headers=None,method='GET'):
        return urlopen(Request(f'http://127.0.0.1:{self.port}{url}',headers=headers or {},method=method),timeout=3)

    def test_live_history_app_and_security_headers(self):
        with self.fetch('/') as r:
            self.assertIn(b'Resource Watch',r.read())
            self.assertIn('default-src',r.headers['Content-Security-Policy'])
        with self.fetch('/app.js') as r:self.assertIn(b'plot(',r.read())
        with self.fetch('/api/health') as r:self.assertTrue(json.load(r)['ok'])
        with self.fetch('/api/current') as r:self.assertEqual(json.load(r)['gpus'][0]['percent'],71)
        with self.fetch('/api/history?range=3600&gpu=0') as r:self.assertTrue(json.load(r)['rows'])
        with self.fetch('/api/processes?range=3600&gpu=0') as r:self.assertEqual(len(json.load(r)['rows']),1)
        with self.fetch('/api/process-history?range=3600&gpu=0&pid=1234&start=67291') as r:
            self.assertTrue(json.load(r)['rows'])

    def test_deny_bad_host_and_foreign_origin(self):
        for headers in ({'Host':'malicious.example'}, {'Origin':'https://malicious.example'},
                        {'Sec-Fetch-Site':'cross-site'}):
            with self.assertRaises(HTTPError) as cm:self.fetch('/api/current',headers)
            self.assertEqual(cm.exception.code,403)
        with self.assertRaises(HTTPError) as cm:self.fetch('/api/current',method='POST')
        self.assertEqual(cm.exception.code,405)
        with self.assertRaises(HTTPError) as cm:self.fetch('/../etc/passwd')
        self.assertEqual(cm.exception.code,404)


class CollectorTests(unittest.TestCase):
    def test_real_ctypes_nvml_abi_with_synthetic_library(self):
        if not shutil.which('gcc'):
            self.skipTest('C compiler unavailable')
        source=Path(__file__).parent / 'native' / 'fake_nvml.c'
        with tempfile.TemporaryDirectory() as d:
            lib=Path(d) / 'libnvidia-ml.so.1'
            subprocess.run(['gcc','-shared','-fPIC','-O2',str(source),'-o',str(lib)],check=True)
            nv=NVML(ctypes.CDLL(str(lib)))
            result=nv.read()
            g=result['gpus'][0]
            self.assertEqual(g['percent'],78)
            self.assertEqual(g['temp_c'],53)
            self.assertEqual(g['vram_used_bytes'],3*1024**3)
            self.assertEqual(g['video_encode_percent'],24)
            self.assertTrue(g['process_list_supported'])
            self.assertTrue(g['process_util_supported'])
            p=result['processes'][0]
            self.assertEqual(p['pid'],os.getpid())
            self.assertEqual(p['vram_bytes'],2*1024**3)
            self.assertEqual(p['sm_percent'],69)
            self.assertEqual(p['type'],'compute + graphics')
            # A second polling cycle must not recycle stale utilization as new data.
            later=nv.read()
            self.assertIsNone(later['processes'][0]['sm_percent'])

    def test_gpu_fallback_without_device(self):
        with mock.patch('faco_watch.gpu.shutil.which',return_value=None):
            result=_smi_fallback()
        self.assertEqual(result['gpus'],[])
        self.assertTrue(result['error'])

    def test_smi_parser(self):
        line='0, NVIDIA GeForce RTX 5060 Ti, 73, 18, 4096, 16384, 54\n'
        with mock.patch('faco_watch.gpu.shutil.which',return_value='/usr/bin/nvidia-smi'):
            with mock.patch('faco_watch.gpu.subprocess.run',return_value=mock.Mock(stdout=line)):
                result=_smi_fallback()
        self.assertEqual(result['gpus'][0]['percent'],73)
        self.assertEqual(result['gpus'][0]['vram_used_bytes'],4096*1048576)
        self.assertFalse(result['gpus'][0]['process_util_supported'])

    def test_sampler_recovers_when_storage_becomes_available(self):
        class StubCpu:
            def sample(self):return 20
        class StubGPU:
            def sample(self):
                s=fake_snapshot(1)
                return {k:s[k] for k in ('gpus','processes','backend','error')}
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'history.sqlite3'
            now_file=Path(d)/'latest.json'
            original=storage.connect
            attempts=[0]
            def delayed_storage():
                attempts[0]+=1
                if attempts[0]==1:
                    raise OSError('External volume not mounted yet')
                return original(target)
            stop=threading.Event()
            runner=SamplerThread(stop,period=.03,retry_period=.02,
                                 cpu_reader=StubCpu(),gpu_reader=StubGPU(),latest_file=now_file)
            with mock.patch('faco_watch.service.storage.connect', side_effect=delayed_storage):
                runner.start()
                for _ in range(100):
                    if now_file.exists():break
                    time.sleep(.01)
                stop.set();runner.join(timeout=2)
            self.assertFalse(runner.is_alive())
            self.assertGreaterEqual(attempts[0],2)
            self.assertTrue(now_file.exists())
            self.assertEqual(json.loads(now_file.read_text())['gpus'][0]['percent'],71)

    def test_sampler_records_to_file_and_database(self):
        class StubCpu:
            def sample(self):return 40
        class StubGPU:
            def sample(self):
                s=fake_snapshot(1)
                return {k:s[k] for k in ('gpus','processes','backend','error')}
        with tempfile.TemporaryDirectory() as d:
            db=storage.connect(Path(d)/'history.sqlite3')
            snapper=SamplerThread(threading.Event(),cpu_reader=StubCpu(),
                                 gpu_reader=StubGPU(), db=db, latest_file=Path(d)/'latest.json')
            snap=snapper.collect_once(db)
            self.assertTrue((Path(d)/'latest.json').exists())
            self.assertEqual(json.loads((Path(d)/'latest.json').read_text())['gpus'][0]['percent'],71)
            self.assertTrue(storage.query_history(db,60,0,now=int(time.time()))['rows'])
            db.close()


if __name__=='__main__':unittest.main()
