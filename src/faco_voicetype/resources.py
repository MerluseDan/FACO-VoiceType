from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .paths import faco_root as canonical_faco_root, shared_root


def faco_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("FACO_RESOURCE_ROOT", "").strip()
    if env:
        # An explicit root is authoritative. Falling through to the production
        # mount can select a model outside an isolated/test installation.
        roots.append(Path(env).expanduser())
    else:
        roots.append(canonical_faco_root())
        preferred = Path("/media/owner/Faco Resources1")
        if preferred not in roots and preferred.exists():
            roots.append(preferred)
        user = os.environ.get("USER", "")
        if user:
            media_root = Path("/media") / user
            if media_root.exists():
                roots.extend(media_root.glob("Faco Resources1"))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key not in seen:
            unique.append(root)
            seen.add(key)
    return unique


def shared_model_download_root() -> Path:
    for root in faco_roots():
        if root.exists() and os.access(root, os.W_OK):
            target = root / "_shared" / "models" / "faster-whisper"
            target.mkdir(parents=True, exist_ok=True)
            return target
    target = Path.home() / ".cache" / "faco-voicetype" / "models"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for faco in faco_roots():
        shared = faco / "_shared"
        for name in ("models", "stt", "speech", "whisper", "speech-runtime"):
            p = shared / name
            if p.exists():
                roots.append(p)
        if shared.exists() and not roots:
            roots.append(shared)
    hf = Path.home() / ".cache" / "huggingface" / "hub"
    if hf.exists():
        roots.append(hf)
    return roots


def _walk_limited(root: Path, max_depth: int):
    base_depth = len(root.parts)
    for current, dirs, files in os.walk(root, onerror=lambda _e: None):
        current_path = Path(current)
        depth = len(current_path.parts) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        # Avoid obvious non-model/cache junk trees.
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "venv"}]
        yield current_path, files


def _friendly_model_name(path: Path) -> str:
    for parent in (path, *path.parents):
        name = parent.name
        if name.startswith("models--"):
            return name.replace("models--", "").replace("--", "/")
    return path.name


@lru_cache(maxsize=1)
def discover_local_whisper_models(max_depth: int = 6) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in _candidate_roots():
        try:
            for current, files in _walk_limited(root, max_depth):
                names = set(files)
                if "config.json" not in names or "model.bin" not in names:
                    continue
                try:
                    resolved = str(current.resolve())
                except OSError:
                    resolved = str(current)
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append((_friendly_model_name(current), resolved))
        except (PermissionError, OSError):
            continue
    return sorted(found, key=lambda x: x[0].lower())


def find_local_model(requested: str) -> str | None:
    p = Path(requested).expanduser()
    if p.exists() and p.is_dir() and (p / "model.bin").exists() and (p / "config.json").exists():
        return str(p.resolve())
    normalized = re.sub(r"[^a-z0-9]+", "", requested.lower().replace("faster-whisper", ""))
    if not normalized:
        return None
    scored: list[tuple[int, str]] = []
    for label, path in discover_local_whisper_models():
        hay = re.sub(r"[^a-z0-9]+", "", (label + " " + path).lower().replace("faster-whisper", ""))
        if normalized in hay:
            # Prefer shortest matching descriptor: usually the exact model rather than a derivative.
            scored.append((len(hay), path))
    return min(scored)[1] if scored else None
