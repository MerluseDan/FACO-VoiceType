"""Artificial load test. Does NOT measure performance on a real NVIDIA GPU."""
import json
from pathlib import Path
import tempfile
import time
from faco_watch import storage

COUNT = 30000
start = time.perf_counter()
with tempfile.TemporaryDirectory() as d:
    conn=storage.connect(Path(d)/'performance.sqlite3')
    now=int(time.time())
    with conn:
        for i in range(COUNT):
            ts=now-(COUNT-i)
            conn.execute('''INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (ts,0,33,52,8*2**30,16*2**30,55,round(i % 100),28,48,
                          3*2**30,16*2**30,12,4))
            conn.execute('''INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (ts,-1,33,52,8*2**30,16*2**30,55,None,None,None,
                          None,None,None,None))
            conn.execute('''INSERT INTO process_samples VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                         (ts,0,600,'99551','blender','compute',2*2**30,i%100,23,0,0))
    populate_ms=round((time.perf_counter()-start)*1000)
    def timed(name,callback):
        t=time.perf_counter();result=callback()
        return {'milliseconds':round((time.perf_counter()-t)*1000,2),'rows':len(result['rows'])}
    h7=timed('7day',lambda:storage.query_history(conn,604800,0))
    h1=timed('1hour',lambda:storage.query_history(conn,3600,0))
    apps=timed('processes',lambda:storage.query_process_summary(conn,604800,0))
    proc=timed('process-history',lambda:storage.query_process_history(conn,604800,0,600,'99551'))
    sz=Path(d,'performance.sqlite3').stat().st_size
    conn.close()
    print(json.dumps({'synthetic_input':{'sample_rows':COUNT*2,'process_rows':COUNT},
                      'write_ms':populate_ms,'database_megabytes':round(sz/(2**20),2),
                      'history_7d':h7,'history_1h':h1,'process_summary':apps,
                      'process_history':proc},indent=2))
