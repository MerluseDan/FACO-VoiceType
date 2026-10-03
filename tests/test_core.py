from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from faco_voicetype.config import ConfigStore, MouseBinding, Settings
from faco_voicetype.injector import session_type


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    settings = Settings(model="small", mouse=MouseBinding(name="Test Mouse", button_code=276, button_name="BTN_EXTRA"))
    store.save(settings)
    loaded = store.load()
    assert loaded.model == "small"
    assert loaded.mouse.button_code == 276
    assert loaded.mouse.name == "Test Mouse"


def test_config_clamps_invalid(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"trigger_mode":"broken", "sample_rate":1, "clipboard_restore_delay_ms":999999}), encoding="utf-8")
    s = ConfigStore(path).load()
    assert s.trigger_mode == "hold"
    assert s.sample_rate == 8000
    assert s.clipboard_restore_delay_ms == 5000


def test_session_detection_wayland(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert session_type() == "wayland"


def test_session_detection_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert session_type() == "x11"
