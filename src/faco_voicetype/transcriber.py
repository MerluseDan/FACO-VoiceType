from __future__ import annotations

import gc
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .resources import find_local_model, shared_model_download_root
from .prosody import WordTiming, enhance_expression

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    model: str
    device: str
    compute_type: str


class Transcriber:
    def __init__(self):
        self._model = None
        self._spec: ModelSpec | None = None
        self._lock = threading.RLock()

    @staticmethod
    def cuda_available() -> bool:
        try:
            import ctranslate2
            return int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:
            return False

    def _resolve(self, model: str, device: str, compute_type: str) -> ModelSpec:
        local = find_local_model(model)
        resolved_model = local or model
        if local:
            log.info("Reusing local Whisper model for %s: %s", model, local)
        resolved_device = device
        if device == "auto":
            resolved_device = "cuda" if self.cuda_available() else "cpu"
        if compute_type == "auto":
            resolved_compute = "float16" if resolved_device == "cuda" else "int8"
        else:
            resolved_compute = compute_type
        return ModelSpec(model=resolved_model, device=resolved_device, compute_type=resolved_compute)

    def preload(self, model: str, device: str, compute_type: str, progress=None) -> ModelSpec:
        spec = self._resolve(model, device, compute_type)
        with self._lock:
            if self._model is not None and self._spec == spec:
                return spec
            self.unload()
            if progress:
                progress(f"Loading Whisper {Path(spec.model).name} on {spec.device}…")
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                spec.model,
                device=spec.device,
                compute_type=spec.compute_type,
                download_root=str(shared_model_download_root()),
            )
            self._spec = spec
            log.info("Whisper loaded model=%s device=%s compute=%s", spec.model, spec.device, spec.compute_type)
            return spec

    def transcribe(
        self,
        audio: np.ndarray,
        model: str,
        device: str,
        compute_type: str,
        language: str = "auto",
        beam_size: int = 1,
        vad_filter: bool = True,
        progress=None,
        expressive_punctuation: bool = False,
        expression_level: str = "balanced",
        sample_rate: int = 16000,
    ) -> tuple[str, ModelSpec]:
        if audio.ndim != 1:
            audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size < 1600:
            return "", self._resolve(model, device, compute_type)
        spec = self.preload(model, device, compute_type, progress=progress)
        if progress:
            progress("Transcribing…")
        with self._lock:
            segments, info = self._model.transcribe(
                audio.astype(np.float32, copy=False),
                language=None if language == "auto" else language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                condition_on_previous_text=False,
                word_timestamps=expressive_punctuation,
            )
            segment_list = list(segments)
            text = "".join(seg.text for seg in segment_list).strip()
            if expressive_punctuation and text:
                words: list[WordTiming] = []
                for seg in segment_list:
                    for word in (getattr(seg, "words", None) or []):
                        raw = str(getattr(word, "word", "") or "")
                        start = getattr(word, "start", None)
                        end = getattr(word, "end", None)
                        if raw and start is not None and end is not None:
                            words.append(WordTiming(raw, float(start), float(end)))
                text, features = enhance_expression(
                    text, audio, sample_rate=sample_rate, words=words, level=expression_level
                )
                log.info("Prosody features: %s", features)
        log.info("Transcribed chars=%s language=%s probability=%s", len(text), getattr(info, "language", None), getattr(info, "language_probability", None))
        return text, spec

    def unload(self, wait: bool = True) -> bool:
        acquired = self._lock.acquire(blocking=wait)
        if not acquired:
            return False
        try:
            if self._model is not None:
                log.info("Unloading Whisper model")
            self._model = None
            self._spec = None
        finally:
            self._lock.release()
        gc.collect()
        return True
