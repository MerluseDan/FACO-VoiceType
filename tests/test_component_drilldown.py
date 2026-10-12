"""1-Hz CPU/RAM attribution, independent histories and v1.0.x compatibility."""
import os
from pathlib import Path
import tempfile
import time
import threading
import unittest
from faco_watch.collector import ProcessSampler
from faco_watch import storage
from faco_watch.service import SamplerThread
from test_core import fake_snapshot


def stat(pid,name,start,utime=0,stime=0,rss=0):
    fields=['S']+['0']*49
    fields[11]=str(utime);fields[12]=str(stime)
    fields[19]=str(start);fields[21]=str(rss)
    return f'{pid} ({name}) '+ ' '.join(fields)+'\n'


class ProcessReaderTests(unittest.TestCase):
    def test_cpu_per_core_rss_pid_reuse_and_parentheses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);p=path/'115';p.mkdir()
            (p/'stat').write_text(stat(115,'Worker (renderer)',754,100,rss=1000))
            clock=[1.0]
            sampler=ProcessSampler(path,clock=lambda:clock[0],ticks=100,page_size=4096)
            first=sampler.sample()
            self.assertEqual(first[0]['start_ticks'],'754')
            self.assertEqual(first[0]['rss_bytes'],4096000)
            self.assertIsNone(first[0]['cpu_percent'])
            clock[0]=2.0
            (p/'stat').write_text(stat(115,'Worker (renderer)',754,260,rss=1500))
            next_=sampler.sample()[0]
            self.assertEqual(next_['cpu_percent'],160.0) # 1.6 cores
            self.assertEqual(next_['name'],'Worker (renderer)')
            clock[0]=3.0
            (p/'stat').write_text(stat(115,'Replacement',900,10,rss=800))
            new=sampler.sample()[0]
            self.assertIsNone(new['cpu_percent'],'new process must not inherit old PID usage')
            self.assertEqual(new['name'],'Replacement')

    def test_top_cpu_union_top_memory_and_unreadable_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc=Path(tmp)
            for pid in range(100,130):
                folder=proc/str(pid);folder.mkdir()
                (folder/'stat').write_text(stat(pid,f'process_{pid}',pid,0,0,pid*100))
            (proc/'130').mkdir()  # permissions/racing disappearance should not crash
            sampler=ProcessSampler(proc,maximum=10,clock=lambda:1.0,ticks=100)
            first=sampler.sample()
            self.assertGreaterEqual(len(first),5)
            self.assertLessEqual(len(first),10) # bounded CPU/RAM union
            self.assertIn(129,{row['pid'] for row in first})
            self.assertTrue(all('rss_bytes' in row for row in first))


class IndependentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.conn=storage.connect(Path(self.tmp.name)/'history.sqlite3')
        self.now=int(time.time())

    def tearDown(self):
        self.conn.close();self.tmp.cleanup()

    def test_continuous_system_history_across_nvidia_failure_and_recovery(self):
        for i in range(20):
            snap=fake_snapshot(self.now-20+i,activity=i*4,with_gpu=i<7 or i>=13)
            snap['cpu_percent']=20+i
            snap['ram']['percent']=30+i
            snap['cpu_temp_c']=40+i
            storage.save(self.conn,snap)
        result=storage.query_history(self.conn,60,0,self.now)
        self.assertEqual(result['bucket_seconds'],1)
        self.assertEqual(len(result['rows']),20)
        self.assertEqual([r['cpu_percent'] for r in result['rows']],[20+i for i in range(20)])
        self.assertTrue(all(r['gpu_percent'] is None for r in result['rows'][7:13]))
        self.assertEqual(result['rows'][-1]['gpu_percent'],76)
        self.assertEqual(result['rows'][9]['ram_percent'],39)
        self.assertEqual(result['rows'][9]['cpu_temp_c'],49)
        self.assertEqual(len(storage.query_history(self.conn,60,-1,self.now)['rows']),20)

    def test_legacy_gpu_only_sqlite_rows_remain_visible(self):
        old=fake_snapshot(self.now-2)
        storage.save(self.conn,old)
        # Simulate the v1.0.1 file containing no dedicated -1 system row.
        self.conn.execute('DELETE FROM samples WHERE gpu_index=-1')
        self.conn.commit()
        earlier=storage.query_history(self.conn,15,0,self.now)['rows']
        self.assertEqual(len(earlier),1)
        self.assertEqual(earlier[0]['cpu_percent'],32)
        self.assertEqual(earlier[0]['gpu_percent'],71)
        self.assertEqual(earlier[0]['ram_percent'],45)
        storage.save(self.conn,fake_snapshot(self.now-1,activity=82))
        merged=storage.query_history(self.conn,15,0,self.now)['rows']
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[-1]['gpu_percent'],82)

    def test_all_component_peak_columns_and_bucketed_series(self):
        for i in range(30):
            snap=fake_snapshot(self.now-30+i,activity=99 if i==12 else 30)
            snap['cpu_percent']=100 if i==12 else 35
            snap['cpu_temp_c']=93 if i==12 else 55
            snap['gpus'][0]['video_encode_percent']=91 if i==12 else 5
            snap['gpus'][0]['video_decode_percent']=80 if i==12 else 4
            storage.save(self.conn,snap)
        buckets=storage.query_history(self.conn,1800,0,self.now)
        self.assertGreater(buckets['bucket_seconds'],1)
        row=max(buckets['rows'],key=lambda x:x['cpu_percent_peak'])
        self.assertEqual(row['cpu_percent_peak'],100)
        self.assertEqual(row['cpu_temp_c_peak'],93)
        self.assertEqual(row['gpu_percent_peak'],99)
        self.assertEqual(row['video_encode_percent_peak'],91)
        self.assertEqual(row['video_decode_percent_peak'],80)
        self.assertEqual(storage.group_step(15),1)
        self.assertEqual(storage.group_step(60),1)
        self.assertEqual(storage.clamp_range(1),15)

    def test_all_metrics_and_live_process_data_in_one_snapshot(self):
        class FakeCPU:
            def sample(self):return 44
        class FakeGPU:
            def sample(self):
                s=fake_snapshot(1)
                return {key:s[key] for key in ('gpus','processes','backend','error')}
        class FakeProcess:
            def sample(self):return [{'name':'program','pid':17,'start_ticks':'111',
                                     'rss_bytes':1000,'cpu_percent':25.0}]
        with tempfile.TemporaryDirectory() as tmp:
            database=storage.connect(Path(tmp)/'history.sqlite3')
            sampler=SamplerThread(threading.Event(),db=database,
               cpu_reader=FakeCPU(),gpu_reader=FakeGPU(),process_reader=FakeProcess(),
               latest_file=Path(tmp)/'latest.json')
            result=sampler.collect_once(database)
            self.assertEqual(result['system_processes'][0]['name'],'program')
            self.assertEqual(result['gpus'][0]['video_encode_percent'],12)
            self.assertEqual(database.execute('select count(*) from samples').fetchone()[0],2)
            self.assertEqual(database.execute('select count(*) from process_samples').fetchone()[0],1)
            import json
            exported=json.loads((Path(tmp)/'latest.json').read_text())
            self.assertEqual(exported['system_processes'][0]['pid'],17)
            database.close()


if __name__=='__main__':unittest.main()
