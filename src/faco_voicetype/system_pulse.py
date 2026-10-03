from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

import psutil

log = logging.getLogger(__name__)


@dataclass
class PulseSnapshot:
    cpu_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    app_ram_gb: float = 0.0
    gpu_util: float | None = None
    vram_used_gb: float | None = None
    vram_total_gb: float | None = None
    gpu_temp_c: float | None = None
    gpu_processes: list[str] = field(default_factory=list)
    input_name: str = "unknown"
    output_name: str = "unknown"

    def compact(self) -> str:
        parts = [
            f"CPU {self.cpu_percent:.0f}%",
            f"RAM {self.ram_used_gb:.1f}/{self.ram_total_gb:.1f} GB",
            f"App {self.app_ram_gb:.2f} GB",
        ]
        if self.gpu_util is not None:
            gpu = f"GPU {self.gpu_util:.0f}%"
            if self.vram_used_gb is not None and self.vram_total_gb is not None:
                gpu += f" • VRAM {self.vram_used_gb:.1f}/{self.vram_total_gb:.1f} GB"
            if self.gpu_temp_c is not None:
                gpu += f" • {self.gpu_temp_c:.0f}°C"
            parts.append(gpu)
        parts.append(f"Mic {self.input_name}")
        parts.append(f"Out {self.output_name}")
        return "  |  ".join(parts)

    def details(self) -> str:
        gpu_procs = ", ".join(self.gpu_processes[:8]) if self.gpu_processes else "none reported"
        return self.compact() + f"\nGPU processes: {gpu_procs}"


def _run_text(cmd: list[str], timeout: float = 1.5) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _default_audio(kind: str) -> str:
    if not shutil.which("pactl"):
        return "unknown"
    cmd = ["pactl", "get-default-source" if kind == "input" else "get-default-sink"]
    value = _run_text(cmd)
    return value or "unknown"


def _gpu_data(snapshot: PulseSnapshot) -> None:
    if not shutil.which("nvidia-smi"):
        return
    out = _run_text([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    if out:
        first = out.splitlines()[0]
        fields = [x.strip() for x in first.split(",")]
        if len(fields) >= 4:
            snapshot.gpu_util = float(fields[0])
            snapshot.vram_used_gb = float(fields[1]) / 1024.0
            snapshot.vram_total_gb = float(fields[2]) / 1024.0
            snapshot.gpu_temp_c = float(fields[3])
    procs = _run_text([
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ])
    if procs:
        snapshot.gpu_processes = [line.strip() for line in procs.splitlines() if line.strip()]


def collect() -> PulseSnapshot:
    mem = psutil.virtual_memory()
    proc = psutil.Process(os.getpid())
    snap = PulseSnapshot(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_used_gb=(mem.total - mem.available) / (1024 ** 3),
        ram_total_gb=mem.total / (1024 ** 3),
        app_ram_gb=proc.memory_info().rss / (1024 ** 3),
        input_name=_default_audio("input"),
        output_name=_default_audio("output"),
    )
    try:
        _gpu_data(snap)
    except Exception:
        log.debug("GPU telemetry failed", exc_info=True)
    return snap


class PulseGuard:
    """Logs meaningful resource pressure without spamming every sample."""
    def __init__(self):
        self._latched: set[str] = set()

    def evaluate(self, snap: PulseSnapshot) -> None:
        checks = {
            "ram_pressure": snap.ram_total_gb > 0 and snap.ram_used_gb / snap.ram_total_gb >= 0.90,
            "gpu_busy": snap.gpu_util is not None and snap.gpu_util >= 95,
            "vram_pressure": snap.vram_total_gb not in (None, 0) and snap.vram_used_gb is not None and snap.vram_used_gb / snap.vram_total_gb >= 0.90,
            "gpu_hot": snap.gpu_temp_c is not None and snap.gpu_temp_c >= 85,
        }
        for key, active in checks.items():
            if active and key not in self._latched:
                log.warning("System Pulse warning %s: %s", key, snap.details())
                self._latched.add(key)
            elif not active:
                self._latched.discard(key)
