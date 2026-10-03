from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import state_root


@dataclass
class MouseBinding:
    path: str = ""
    name: str = ""
    phys: str = ""
    uniq: str = ""
    vendor: int = 0
    product: int = 0
    button_code: int | None = None
    button_name: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "MouseBinding":
        if not isinstance(value, dict):
            return cls()
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: value[k] for k in allowed if k in value})


@dataclass
class Settings:
    enabled: bool = True
    mouse: MouseBinding = field(default_factory=MouseBinding)
    enter_mouse: MouseBinding = field(default_factory=MouseBinding)
    trigger_mode: str = "hold"  # hold | toggle
    suppress_original_button: bool = True
    suppress_enter_button: bool = True
    microphone_name: str = ""
    sample_rate: int = 16000
    model: str = "small"
    language: str = "auto"
    inference_device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"
    beam_size: int = 1
    vad_filter: bool = True
    append_space: bool = True
    expressive_punctuation: bool = True
    expression_level: str = "balanced"  # conservative | balanced | expressive
    preserve_clipboard_text: bool = True
    clipboard_restore_delay_ms: int = 650
    start_minimized: bool = True
    show_notifications: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "Settings":
        if not isinstance(value, dict):
            return cls()
        data: dict[str, Any] = {}
        for key in cls.__dataclass_fields__.keys():
            if key in {"mouse", "enter_mouse"}:
                continue
            if key in value:
                data[key] = value[key]
        data["mouse"] = MouseBinding.from_dict(value.get("mouse"))
        data["enter_mouse"] = MouseBinding.from_dict(value.get("enter_mouse"))
        obj = cls(**data)
        obj.trigger_mode = obj.trigger_mode if obj.trigger_mode in {"hold", "toggle"} else "hold"
        obj.inference_device = obj.inference_device if obj.inference_device in {"auto", "cuda", "cpu"} else "auto"
        obj.expression_level = obj.expression_level if obj.expression_level in {"conservative", "balanced", "expressive"} else "balanced"
        obj.sample_rate = max(8000, min(48000, int(obj.sample_rate)))
        obj.beam_size = max(1, min(10, int(obj.beam_size)))
        obj.clipboard_restore_delay_ms = max(100, min(5000, int(obj.clipboard_restore_delay_ms)))
        return obj


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (state_root() / "config.json")

    def load(self) -> Settings:
        try:
            return Settings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return Settings()
        except Exception:
            return Settings()

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
