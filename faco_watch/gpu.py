"""NVML collector, stdlib ctypes. Gracefully handles missing/broken GPU drivers."""
import ctypes as C
import shutil
import subprocess
import time
from .collector import process_identity


class Util(C.Structure):
    _fields_ = [('gpu', C.c_uint), ('memory', C.c_uint)]


class Memory(C.Structure):
    _fields_ = [('total', C.c_ulonglong), ('free', C.c_ulonglong), ('used', C.c_ulonglong)]


class ProcV2(C.Structure):
    _fields_ = [
        ('pid', C.c_uint), ('usedGpuMemory', C.c_ulonglong),
        ('gpuInstanceId', C.c_uint), ('computeInstanceId', C.c_uint),
    ]


class ProcV1(C.Structure):
    _fields_ = [('pid', C.c_uint), ('usedGpuMemory', C.c_ulonglong)]


class ProcUtil(C.Structure):
    _fields_ = [
        ('pid', C.c_uint), ('timeStamp', C.c_ulonglong), ('smUtil', C.c_uint),
        ('memUtil', C.c_uint), ('encUtil', C.c_uint), ('decUtil', C.c_uint),
    ]


class NVML:
    OK = 0
    NOT_SUPPORTED = 3
    NOT_FOUND = 6
    SMALL = 7

    def __init__(self, library=None):
        self.lib = library or C.CDLL('libnvidia-ml.so.1')
        self._last_seen = {}
        rc = self._call('nvmlInit_v2', [])
        if rc != self.OK:
            raise OSError(f'NVML driver initialization returned {rc}')

    def _call(self, name, argtypes, *args):
        fn = getattr(self.lib, name, None)
        if fn is None:
            return self.NOT_SUPPORTED
        fn.argtypes = argtypes
        fn.restype = C.c_int
        return fn(*args)

    def _query_process_list(self, handle, kind):
        for version, struct in ((2, ProcV2), (1, ProcV1)):
            suffix = '_v2' if version == 2 else ''
            fn = f'nvmlDeviceGet{kind}RunningProcesses{suffix}'
            if getattr(self.lib, fn, None) is None:
                continue
            cnt = C.c_uint(0)
            rc = self._call(fn, [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(struct)],
                            handle, C.byref(cnt), None)
            if rc == self.NOT_SUPPORTED:
                continue
            if rc == self.OK and cnt.value == 0:
                return [], True
            if rc not in (self.SMALL, self.OK) or cnt.value > 4096:
                return [], False
            for _ in range(3):
                array = (struct * max(1, cnt.value + 16))()
                available = C.c_uint(len(array))
                rc = self._call(fn, [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(struct)],
                                handle, C.byref(available), array)
                if rc == self.SMALL and available.value <= 4096:
                    cnt.value = available.value
                    continue
                if rc == self.OK:
                    return [
                        {'pid': int(p.pid), 'vram_bytes': None if p.usedGpuMemory == (2**64 - 1)
                         else int(p.usedGpuMemory), 'type': kind.lower()}
                        for p in array[:available.value]
                    ], True
                break
            return [], False
        return [], False

    def _process_utilization(self, handle, gpu_index):
        fn = 'nvmlDeviceGetProcessUtilization'
        if getattr(self.lib, fn, None) is None:
            return {}, False
        last = self._last_seen.get(gpu_index, 0)
        cnt = C.c_uint(0)
        argtypes = [C.c_void_p, C.POINTER(ProcUtil), C.POINTER(C.c_uint), C.c_ulonglong]
        rc = self._call(fn, argtypes, handle, None, C.byref(cnt), last)
        if rc in (self.NOT_FOUND, self.OK) and cnt.value == 0:
            return {}, True
        if rc in (self.NOT_SUPPORTED,):
            return {}, False
        if rc not in (self.SMALL, self.OK) or cnt.value > 4096:
            return {}, False
        for _ in range(3):
            arr = (ProcUtil * max(1, cnt.value + 16))()
            available = C.c_uint(len(arr))
            rc = self._call(fn, argtypes, handle, arr, C.byref(available), last)
            if rc == self.SMALL and available.value <= 4096:
                cnt.value = available.value
                continue
            if rc in (self.NOT_FOUND,):
                return {}, True
            if rc != self.OK:
                return {}, False
            by_pid = {}
            newest = last
            for x in arr[:available.value]:
                newest = max(newest, x.timeStamp)
                # SM is an NVML per-process sample, not fractional ownership of
                # the system-wide GPU utilization percentage.
                prior = by_pid.get(int(x.pid))
                if prior is None or x.timeStamp >= prior['timestamp']:
                    by_pid[int(x.pid)] = {
                        'timestamp': int(x.timeStamp),
                        'sm_percent': min(100, int(x.smUtil)),
                        'mem_percent': min(100, int(x.memUtil)),
                        'encode_percent': min(100, int(x.encUtil)),
                        'decode_percent': min(100, int(x.decUtil)),
                    }
            self._last_seen[gpu_index] = newest
            return by_pid, True
        return {}, False

    def read(self):
        cnt = C.c_uint()
        rc = self._call('nvmlDeviceGetCount_v2', [C.POINTER(C.c_uint)], C.byref(cnt))
        if rc != self.OK:
            raise OSError(f'NVML device enumeration returned {rc}')
        gpus, processes = [], []
        for i in range(min(cnt.value, 16)):
            dev = C.c_void_p()
            if self._call('nvmlDeviceGetHandleByIndex_v2', [C.c_uint, C.POINTER(C.c_void_p)],
                          i, C.byref(dev)) != self.OK:
                continue
            name_buf = C.create_string_buffer(128)
            self._call('nvmlDeviceGetName', [C.c_void_p, C.c_char_p, C.c_uint],
                       dev, name_buf, len(name_buf))
            v = Util()
            r_util = self._call('nvmlDeviceGetUtilizationRates', [C.c_void_p, C.POINTER(Util)],
                                dev, C.byref(v))
            mem = Memory()
            r_mem = self._call('nvmlDeviceGetMemoryInfo', [C.c_void_p, C.POINTER(Memory)],
                               dev, C.byref(mem))
            temp = C.c_uint(0)
            r_temp = self._call('nvmlDeviceGetTemperature',
                                [C.c_void_p, C.c_uint, C.POINTER(C.c_uint)],
                                dev, 0, C.byref(temp))
            enc = C.c_uint(0)
            enc_time = C.c_uint(0)
            r_enc = self._call('nvmlDeviceGetEncoderUtilization',
                               [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(C.c_uint)],
                               dev, C.byref(enc), C.byref(enc_time))
            dec = C.c_uint(0)
            dec_time = C.c_uint(0)
            r_dec = self._call('nvmlDeviceGetDecoderUtilization',
                               [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(C.c_uint)],
                               dev, C.byref(dec), C.byref(dec_time))
            gpus.append({
                'index': i,
                'name': name_buf.value.decode('utf-8', 'replace') or f'NVIDIA GPU {i}',
                'percent': int(v.gpu) if r_util == 0 else None,
                'memory_controller_percent': int(v.memory) if r_util == 0 else None,
                'temp_c': int(temp.value) if r_temp == 0 else None,
                'vram_used_bytes': int(mem.used) if r_mem == 0 else None,
                'vram_total_bytes': int(mem.total) if r_mem == 0 else None,
                'video_encode_percent': int(enc.value) if r_enc == 0 else None,
                'video_decode_percent': int(dec.value) if r_dec == 0 else None,
            })
            procs = {}
            tracked = False
            for kind in ('Compute', 'Graphics'):
                res, supported = self._query_process_list(dev, kind)
                tracked = tracked or supported
                for p in res:
                    if not p['pid']:
                        continue
                    if p['pid'] not in procs:
                        procs[p['pid']] = p
                    else:
                        earlier = procs[p['pid']]
                        earlier['type'] = 'compute + graphics'
                        if earlier['vram_bytes'] is None:
                            earlier['vram_bytes'] = p['vram_bytes']
                        elif p['vram_bytes'] is not None:
                            earlier['vram_bytes'] = max(earlier['vram_bytes'], p['vram_bytes'])
            util, util_supported = self._process_utilization(dev, i)
            # A process with activity might not have a visible VRAM context
            # at the precise instant the query ran.
            for pid in util:
                procs.setdefault(pid, {'pid': pid, 'vram_bytes': None, 'type': 'sampled'})
            for pid, p in procs.items():
                name, start = process_identity(pid)
                p.update({'gpu_index': i, 'name': name, 'start_ticks': start,
                          'sm_percent': util.get(pid, {}).get('sm_percent'),
                          'memory_io_percent': util.get(pid, {}).get('mem_percent'),
                          'encode_percent': util.get(pid, {}).get('encode_percent'),
                          'decode_percent': util.get(pid, {}).get('decode_percent')})
                processes.append(p)
            gpus[-1]['process_list_supported'] = tracked
            gpus[-1]['process_util_supported'] = util_supported
        return {'gpus': gpus, 'processes': processes,
                'backend': 'NVIDIA NVML', 'error': None}


def _smi_fallback():
    smi = shutil.which('nvidia-smi')
    if not smi:
        return {'gpus': [], 'processes': [], 'backend': 'unavailable',
                'error': 'NVIDIA NVML/nvidia-smi unavailable (or no NVIDIA driver).'}
    fields = 'index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu'
    try:
        result = subprocess.run([smi, f'--query-gpu={fields}', '--format=csv,noheader,nounits'],
                                text=True, capture_output=True, timeout=3, check=True)
        gpus = []
        for row in result.stdout.splitlines():
            parts = [p.strip() for p in row.split(',')]
            if len(parts) != 7:
                continue
            def val(x):
                try:
                    return float(x) if x not in ('[N/A]', 'N/A', 'Not Supported') else None
                except ValueError:
                    return None
            i = int(parts[0])
            gpus.append({'index': i, 'name': parts[1],
                         'percent': val(parts[2]), 'memory_controller_percent': val(parts[3]),
                         'vram_used_bytes': int(val(parts[4]) * 1024**2) if val(parts[4]) is not None else None,
                         'vram_total_bytes': int(val(parts[5]) * 1024**2) if val(parts[5]) is not None else None,
                         'temp_c': val(parts[6]), 'video_encode_percent': None,
                         'video_decode_percent': None, 'process_list_supported': False,
                         'process_util_supported': False})
        return {'gpus': gpus, 'processes': [], 'backend': 'nvidia-smi (limited)', 'error': None}
    except (subprocess.TimeoutExpired, OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {'gpus': [], 'processes': [], 'backend': 'unavailable',
                'error': f'NVIDIA driver unavailable: {str(exc)[:160]}'}


class GpuSampler:
    def __init__(self):
        self.nvml = None
        self.reason = None
        self._last_nvml_attempt = 0.0
        self._last_fallback = 0.0
        self._fallback_cache = None
        self._try_init()

    def _try_init(self):
        self._last_nvml_attempt = time.monotonic()
        try:
            self.nvml = NVML()
            self.reason = None
        except (OSError, AttributeError) as exc:
            self.nvml = None
            self.reason = str(exc)

    def sample(self):
        now = time.monotonic()
        # Recover automatically if NVIDIA driver is installed/restarted later.
        if self.nvml is None and now - self._last_nvml_attempt >= 30:
            self._try_init()
        if self.nvml is not None:
            try:
                return self.nvml.read()
            except (OSError, C.ArgumentError, ValueError, AttributeError) as exc:
                self.reason = str(exc)
                self.nvml = None
                self._last_nvml_attempt = now
        # NVIDIA CLI is more costly than direct NVML, so limit it to once per
        # 10 seconds rather than subprocess-spawning on every 1-second tick.
        if self._fallback_cache is None or now - self._last_fallback >= 10:
            self._fallback_cache = _smi_fallback()
            self._last_fallback = now
        return self._fallback_cache
