from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

log = logging.getLogger(__name__)

_END_PUNCT = ".?!"
_ANY_PUNCT = ",.;:?!"


@dataclass(frozen=True)
class WordTiming:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class ProsodyFeatures:
    voiced_frames: int = 0
    pitch_median_hz: float = 0.0
    pitch_rise_ratio: float = 0.0
    pitch_spread_ratio: float = 0.0
    emphasis_ratio: float = 1.0
    peak: float = 0.0


def _finite_percentile(values: Sequence[float], q: float, default: float = 0.0) -> float:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return default
    return float(np.percentile(arr, q))


def analyze_prosody(audio: np.ndarray, sample_rate: int = 16000) -> ProsodyFeatures:
    """Estimate lightweight speech prosody without an extra ML model.

    The estimator intentionally uses only NumPy. It is not an emotion classifier;
    it measures timing, pitch movement and emphasis strongly enough to improve
    punctuation while keeping VoiceType offline and dependency-light.
    """
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    if data.size < max(400, int(sample_rate * 0.20)) or sample_rate < 4000:
        return ProsodyFeatures(peak=float(np.max(np.abs(data))) if data.size else 0.0)

    data = np.nan_to_num(data, copy=False)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    frame_len = max(128, int(round(sample_rate * 0.040)))
    hop = max(64, int(round(sample_rate * 0.020)))
    nfft = 1
    while nfft < frame_len:
        nfft <<= 1
    nfft = max(1024, nfft)
    window = np.hanning(frame_len).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / sample_rate)
    band = np.flatnonzero((freqs >= 70.0) & (freqs <= 380.0))
    if band.size == 0:
        return ProsodyFeatures(peak=peak)

    rms_values: list[float] = []
    pitches: list[float] = []
    pitch_times: list[float] = []
    frames: list[np.ndarray] = []
    for start in range(0, max(1, data.size - frame_len + 1), hop):
        frame = data[start:start + frame_len]
        if frame.size != frame_len:
            break
        rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
        rms_values.append(rms)
        frames.append(frame)

    if not rms_values:
        return ProsodyFeatures(peak=peak)

    # Dynamic speech threshold avoids treating fan noise as voiced audio.
    rms_arr = np.asarray(rms_values, dtype=np.float64)
    noise = float(np.percentile(rms_arr, 20))
    speech_ref = float(np.percentile(rms_arr, 75))
    voiced_threshold = max(0.004, min(noise * 2.0, speech_ref * 0.35))

    for index, (frame, rms) in enumerate(zip(frames, rms_values)):
        if rms < voiced_threshold:
            continue
        centered = frame - float(np.mean(frame))
        spectrum = np.abs(np.fft.rfft(centered * window, n=nfft))
        local = spectrum[band]
        if local.size == 0:
            continue
        peak_idx = int(band[int(np.argmax(local))])
        dominant = float(freqs[peak_idx])
        if not math.isfinite(dominant) or dominant <= 0:
            continue
        pitches.append(dominant)
        pitch_times.append((index * hop + frame_len * 0.5) / sample_rate)

    voiced_rms = rms_arr[rms_arr >= voiced_threshold]
    emphasis = 1.0
    if voiced_rms.size:
        med = max(1e-6, float(np.median(voiced_rms)))
        emphasis = float(np.percentile(voiced_rms, 90) / med)

    if len(pitches) < 4:
        return ProsodyFeatures(
            voiced_frames=len(pitches),
            emphasis_ratio=emphasis,
            peak=peak,
        )

    p = np.asarray(pitches, dtype=np.float64)
    median = max(1.0, float(np.median(p)))
    spread = max(0.0, (_finite_percentile(p, 90) - _finite_percentile(p, 10)) / median)

    # Compare the last voiced third with the preceding voiced third. This is
    # intentionally relative so it works across different natural voice ranges.
    n = len(p)
    chunk = max(2, n // 3)
    end_med = float(np.median(p[-chunk:]))
    prev_start = max(0, n - 2 * chunk)
    prev = p[prev_start:n - chunk]
    prev_med = float(np.median(prev)) if prev.size else median
    rise = (end_med - prev_med) / max(prev_med, 1.0)

    return ProsodyFeatures(
        voiced_frames=len(p),
        pitch_median_hz=median,
        pitch_rise_ratio=float(rise),
        pitch_spread_ratio=float(spread),
        emphasis_ratio=float(emphasis),
        peak=peak,
    )


def _lexical_question(text: str) -> bool:
    clean = re.sub(r"^[\s\"'“‘([{]+", "", text.strip().lower())
    starters = (
        "who ", "what ", "when ", "where ", "why ", "how ", "which ", "whose ",
        "is ", "are ", "am ", "was ", "were ", "do ", "does ", "did ",
        "can ", "could ", "will ", "would ", "should ", "shall ", "may ", "might ",
        "have ", "has ", "had ", "isn't ", "aren't ", "wasn't ", "weren't ",
        "don't ", "doesn't ", "didn't ", "can't ", "couldn't ", "won't ", "wouldn't ",
    )
    if clean.startswith(starters):
        return True
    return bool(re.search(r"\b(can|could|would|will|do|did|are|is)\s+(you|we|they|he|she|it)\b", clean[:90]))


def _strong_exclamation_language(text: str) -> bool:
    clean = text.lower()
    return bool(re.search(
        r"\b(wow|amazing|awesome|fantastic|incredible|perfect|excellent|hell yes|fuck yes|damn|stop|watch out|no way|holy)\b",
        clean,
    ))


def _capitalize_first_alpha(token: str) -> str:
    chars = list(token)
    for i, ch in enumerate(chars):
        if ch.isalpha():
            chars[i] = ch.upper()
            break
    return "".join(chars)


def insert_pause_punctuation(text: str, words: Iterable[WordTiming], level: str = "balanced") -> str:
    items = [w for w in words if w.text]
    if len(items) < 2:
        return text.strip()
    thresholds = {
        "conservative": (0.58, 1.05),
        "balanced": (0.43, 0.88),
        "expressive": (0.32, 0.72),
    }
    comma_gap, sentence_gap = thresholds.get(level, thresholds["balanced"])

    pieces = [w.text for w in items]
    changed = False
    for i in range(len(items) - 1):
        gap = max(0.0, float(items[i + 1].start) - float(items[i].end))
        current = pieces[i].rstrip()
        if not current or current[-1] in _ANY_PUNCT:
            continue
        if gap >= sentence_gap:
            pieces[i] = current + "."
            pieces[i + 1] = _capitalize_first_alpha(pieces[i + 1])
            changed = True
        elif gap >= comma_gap:
            pieces[i] = current + ","
            changed = True

    rebuilt = "".join(pieces).strip()
    # Word timing text from Faster-Whisper normally recreates the transcript.
    # If a backend returns malformed spacing, keep Whisper's original instead.
    if not rebuilt or (text and len(rebuilt) < max(3, int(len(text) * 0.55))):
        return text.strip()
    return rebuilt if changed or rebuilt else text.strip()


def enhance_expression(
    text: str,
    audio: np.ndarray,
    sample_rate: int = 16000,
    words: Iterable[WordTiming] = (),
    level: str = "balanced",
) -> tuple[str, ProsodyFeatures]:
    """Improve punctuation using Whisper word timing + acoustic prosody.

    Returns the enhanced text and measured features for logging/testing.
    """
    clean = text.strip()
    if not clean:
        return clean, ProsodyFeatures()
    level = level if level in {"conservative", "balanced", "expressive"} else "balanced"
    clean = insert_pause_punctuation(clean, words, level)
    features = analyze_prosody(audio, sample_rate)

    # Preserve an explicit question/exclamation from Whisper. Otherwise choose
    # a final mark from lexical structure and voice contour.
    if clean.endswith(("?", "!")):
        return clean, features

    lexical_q = _lexical_question(clean)
    rise_threshold = {"conservative": 0.14, "balanced": 0.10, "expressive": 0.075}[level]
    emph_threshold = {"conservative": 2.15, "balanced": 1.85, "expressive": 1.60}[level]
    spread_threshold = {"conservative": 0.62, "balanced": 0.48, "expressive": 0.38}[level]

    is_question = lexical_q or (features.voiced_frames >= 6 and features.pitch_rise_ratio >= rise_threshold)
    emphatic = (
        features.voiced_frames >= 6
        and features.emphasis_ratio >= emph_threshold
        and features.pitch_spread_ratio >= spread_threshold
    )
    if _strong_exclamation_language(clean) and features.emphasis_ratio >= max(1.35, emph_threshold - 0.35):
        emphatic = True

    base = clean.rstrip(". ")
    if is_question:
        clean = base + "?"
    elif emphatic:
        clean = base + "!"
    elif clean[-1] not in _END_PUNCT:
        clean += "."

    log.info(
        "Expressive punctuation level=%s question=%s emphatic=%s rise=%.3f spread=%.3f emphasis=%.3f",
        level, is_question, emphatic, features.pitch_rise_ratio, features.pitch_spread_ratio, features.emphasis_ratio,
    )
    return clean, features
