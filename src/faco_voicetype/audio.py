from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float


def list_input_devices() -> list[AudioDevice]:
    result: list[AudioDevice] = []
    try:
        for i, info in enumerate(sd.query_devices()):
            channels = int(info.get("max_input_channels", 0))
            if channels > 0:
                result.append(AudioDevice(i, str(info.get("name", f"Input {i}")), channels, float(info.get("default_samplerate", 16000))))
    except Exception:
        log.exception("Failed listing audio devices")
    return result


def resolve_input_device(name: str) -> int | None:
    if not name:
        return None
    candidates = list_input_devices()
    for item in candidates:
        if item.name == name:
            return item.index
    lname = name.lower()
    for item in candidates:
        if lname in item.name.lower() or item.name.lower() in lname:
            return item.index
    return None


def _resample_linear(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if data.size == 0 or source_rate == target_rate:
        return data.astype(np.float32, copy=False)
    target_len = max(1, int(round(data.size * target_rate / float(source_rate))))
    old_x = np.linspace(0.0, 1.0, num=data.size, endpoint=False)
    new_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.interp(new_x, old_x, data).astype(np.float32)


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.capture_rate = sample_rate
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self.last_peak = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self, microphone_name: str = "") -> None:
        with self._lock:
            if self._recording:
                return
            self._frames.clear()
            self.last_peak = 0.0
            device = resolve_input_device(microphone_name)
            capture_rate = self.sample_rate
            try:
                sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=capture_rate)
            except Exception:
                info = sd.query_devices(device, "input") if device is not None else sd.query_devices(kind="input")
                capture_rate = int(round(float(info.get("default_samplerate", self.sample_rate))))
                sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=capture_rate)
                log.info("Input device does not accept %s Hz directly; capturing at %s Hz then resampling", self.sample_rate, capture_rate)
            self.capture_rate = capture_rate

            def callback(indata, frames, time_info, status):
                if status:
                    log.warning("Audio status: %s", status)
                block = np.asarray(indata[:, 0], dtype=np.float32).copy()
                with self._lock:
                    if self._recording:
                        self._frames.append(block)
                        if block.size:
                            self.last_peak = max(self.last_peak, float(np.max(np.abs(block))))

            self._stream = sd.InputStream(
                samplerate=self.capture_rate,
                channels=1,
                dtype="float32",
                device=device,
                callback=callback,
                blocksize=0,
            )
            self._recording = True
            self._stream.start()
            log.info("Recording started device=%s capture_rate=%s target_rate=%s", microphone_name or "default", self.capture_rate, self.sample_rate)

    def stop(self) -> np.ndarray:
        with self._lock:
            if not self._recording:
                return np.empty((0,), dtype=np.float32)
            self._recording = False
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        with self._lock:
            data = np.concatenate(self._frames) if self._frames else np.empty((0,), dtype=np.float32)
            self._frames.clear()
        original_size = data.size
        if self.capture_rate != self.sample_rate:
            data = _resample_linear(data, self.capture_rate, self.sample_rate)
        log.info("Recording stopped samples=%s->%s seconds=%.2f peak=%.3f", original_size, data.size, data.size / float(self.sample_rate), self.last_peak)
        return data
