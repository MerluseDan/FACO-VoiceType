"""Low-overhead Linux CPU/RAM/temperature readers without pip dependencies."""
from pathlib import Path
import time

PROC = Path('/proc')
HWMON = Path('/sys/class/hwmon')
THERMAL = Path('/sys/class/thermal')


def safe_read(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except (OSError, ValueError):
        return ''


def _proc_stat(proc=PROC):
    line = safe_read(proc / 'stat').splitlines()
    if not line or not line[0].startswith('cpu '):
        return None
    try:
        values = [int(x) for x in line[0].split()[1:]]
        # Idle + iowait is idle time. Exclude guest/guest_nice, which are
        # already included in the user/nice accounting counters.
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values[:8]), idle
    except (ValueError, IndexError):
        return None


class CpuSampler:
    def __init__(self, proc=PROC):
        self.proc = proc
        self.previous = None

    def sample(self):
        now = _proc_stat(self.proc)
        if now is None:
            return None
        if self.previous is None:
            self.previous = now
            return None
        delta_all = now[0] - self.previous[0]
        delta_idle = now[1] - self.previous[1]
        self.previous = now
        if delta_all <= 0:
            return None
        return round(max(0.0, min(100.0, 100 * (1 - delta_idle / delta_all))), 1)


def memory_stats(proc=PROC):
    mem = {}
    for line in safe_read(proc / 'meminfo').splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        try:
            mem[key] = int(value.strip().split()[0]) * 1024
        except (IndexError, ValueError):
            pass
    total = mem.get('MemTotal', 0)
    available = mem.get('MemAvailable', mem.get('MemFree', 0))
    if total <= 0:
        return {'percent': None, 'used_bytes': None, 'total_bytes': None}
    used = max(0, total - available)
    return {
        'percent': round(100 * used / total, 1),
        'used_bytes': used,
        'total_bytes': total,
    }


def cpu_temperature(hwmon=HWMON, thermal=THERMAL):
    """Choose actual CPU package/die sensor, not ambient/NVMe/ACPI."""
    candidates = []
    for hw in sorted(hwmon.glob('hwmon*')):
        chip = safe_read(hw / 'name').lower()
        if chip not in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'fam15h_power'):
            continue
        for temp_file in hw.glob('temp*_input'):
            label = safe_read(temp_file.with_name(temp_file.name.replace('_input', '_label'))).lower()
            try:
                cel = float(safe_read(temp_file)) / 1000
            except ValueError:
                continue
            if cel < -10 or cel > 125:
                continue
            priority = 0 if 'package id' in label or label == 'tdie' else (
                1 if label == 'tctl' or label == '' else 2)
            candidates.append((priority, -cel, cel))
    if candidates:
        candidates.sort()
        return round(candidates[0][2], 1)
    for zone in sorted(thermal.glob('thermal_zone*')):
        sensor_type = safe_read(zone / 'type').lower()
        if 'x86_pkg_temp' not in sensor_type and 'cpu-thermal' not in sensor_type:
            continue
        try:
            v = float(safe_read(zone / 'temp')) / 1000
            if -10 < v < 125:
                return round(v, 1)
        except ValueError:
            pass
    return None


def process_identity(pid, proc=PROC):
    """PID + kernel start ticks prevents confusing reused PIDs in history."""
    try:
        proc_dir = proc / str(int(pid))
        stat = safe_read(proc_dir / 'stat')
        post = stat.rsplit(')', 1)[1].split()
        start_ticks = post[19]
        comm = safe_read(proc_dir / 'comm')
        if not comm:
            comm = stat.split('(', 1)[1].rsplit(')', 1)[0]
        return comm[:160] or 'Unknown', str(start_ticks)
    except (OSError, ValueError, IndexError):
        return f'PID {pid}', 'unknown'


def system_sample(cpu):
    return {
        'ts': int(time.time()),
        'cpu_percent': cpu.sample(),
        'cpu_temp_c': cpu_temperature(),
        'ram': memory_stats(),
    }


class ProcessSampler:
    """Read live CPU/RSS users from procfs; no psutil, privileged access or argv logs.

    CPU percentage follows top: 100% represents one *logical* CPU core.
    This is not directly comparable to the system-wide CPU percentage,
    which is normalized across all logical processors.
    """

    def __init__(self, proc=PROC, maximum=60, clock=None, ticks=None, page_size=None):
        import os
        self.proc = Path(proc)
        self.maximum = max(5, min(int(maximum), 200))
        self.clock = clock or time.monotonic
        self.ticks = ticks or os.sysconf('SC_CLK_TCK')
        self.page_size = page_size or os.sysconf('SC_PAGE_SIZE')
        self.previous = {}
        self.previous_time = None

    def sample(self):
        import os
        now = self.clock()
        elapsed = None if self.previous_time is None else now - self.previous_time
        next_previous, found = {}, []
        try:
            entries = os.scandir(self.proc)
        except OSError:
            return []
        with entries:
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                pid = int(entry.name)
                # Fields after the final ')' start with kernel field 3 (state).
                raw = safe_read(self.proc / entry.name / 'stat')
                try:
                    rest = raw.rsplit(')', 1)[1].split()
                    if len(rest) < 22:
                        continue
                    start = str(rest[19])
                    total_ticks = int(rest[11]) + int(rest[12])
                    rss_bytes = max(0, int(rest[21])) * self.page_size
                    if rss_bytes == 0 and total_ticks == 0:
                        continue
                    comm = raw.split('(', 1)[1].rsplit(')', 1)[0]
                except (ValueError, IndexError):
                    continue
                ident = (pid, start)
                next_previous[ident] = total_ticks
                prior = self.previous.get(ident)
                usage = None
                if prior is not None and elapsed is not None and elapsed > 0:
                    # Report percentage of one logical core. Multithreaded
                    # processes can legitimately exceed 100%.
                    usage = round(max(0., (total_ticks - prior) * 100. / (self.ticks * elapsed)), 1)
                # /proc/[pid]/comm is short (15 chars). The exe's basename
                # helps distinguish applications without collecting arguments.
                name = comm
                try:
                    executable = os.readlink(self.proc / entry.name / 'exe')
                    name = Path(executable.removesuffix(' (deleted)')).name or comm
                except OSError:
                    pass
                found.append({'pid': pid, 'start_ticks': start,
                              'name': name[:160], 'cpu_percent': usage,
                              'rss_bytes': rss_bytes})
        self.previous = next_previous
        self.previous_time = now
        # Include both CPU consumers and RAM residents. Top CPU alone can
        # exclude a dormant 15 GiB model; top RAM alone can miss a hot thread.
        cpu = sorted(found, key=lambda p: (p['cpu_percent'] or 0), reverse=True)
        mem = sorted(found, key=lambda p: p['rss_bytes'], reverse=True)
        selected = {p['pid']: p for p in cpu[:self.maximum // 2]}
        selected.update({p['pid']: p for p in mem[:self.maximum // 2]})
        return sorted(selected.values(), key=lambda p: (-max(0, p['cpu_percent'] or 0),
                                                        -p['rss_bytes'], p['pid']))
