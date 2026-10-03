from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from faco_voicetype.config import MouseBinding, Settings
from faco_voicetype.prosody import WordTiming, enhance_expression, insert_pause_punctuation


def test_enter_binding_and_expression_defaults_roundtrip_shape():
    s = Settings(
        enter_mouse=MouseBinding(name="Mouse", uniq="abc", button_code=277, button_name="BTN_FORWARD"),
        expressive_punctuation=True,
        expression_level="expressive",
    )
    payload = s.__dict__.copy()
    payload["mouse"] = s.mouse.__dict__.copy()
    payload["enter_mouse"] = s.enter_mouse.__dict__.copy()
    loaded = Settings.from_dict(payload)
    assert loaded.enter_mouse.button_code == 277
    assert loaded.enter_mouse.uniq == "abc"
    assert loaded.expressive_punctuation is True
    assert loaded.expression_level == "expressive"


def test_pause_timing_adds_comma_and_sentence_break():
    words = [
        WordTiming("Hello", 0.00, 0.20),
        WordTiming(" there", 0.70, 0.95),  # 0.50 sec -> comma in balanced mode
        WordTiming(" this", 1.95, 2.15),   # 1.00 sec -> sentence break
        WordTiming(" works", 2.20, 2.45),
    ]
    out = insert_pause_punctuation("Hello there this works", words, "balanced")
    assert out == "Hello, there. This works"


def test_lexical_question_becomes_question_mark_without_extra_model():
    audio = np.zeros(16000, dtype=np.float32)
    out, _features = enhance_expression("Can you open the file.", audio, 16000, level="balanced")
    assert out == "Can you open the file?"


def test_rising_final_pitch_can_mark_question():
    sr = 16000
    first_n = int(sr * 1.4)
    final_n = int(sr * 0.6)
    first = 0.2 * np.sin(2 * np.pi * 150 * np.arange(first_n) / sr)
    final = 0.2 * np.sin(2 * np.pi * 250 * np.arange(final_n) / sr)
    audio = np.concatenate([first, final]).astype(np.float32)
    out, features = enhance_expression("You finished the install.", audio, sr, level="balanced")
    assert features.pitch_rise_ratio > 0.10
    assert out.endswith("?")


def test_x11_enter_uses_real_return_key(monkeypatch):
    import faco_voicetype.injector as inj
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(inj.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(cmd, *, input_bytes=None, timeout=4.0, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(inj, "_run", fake_run)
    result = inj.inject_key("enter")
    assert result.ok
    assert result.method == "xdotool"
    assert calls == [["xdotool", "key", "--clearmodifiers", "Return"]]


def test_ydotool_enter_legacy_and_modern_syntax(monkeypatch):
    import faco_voicetype.injector as inj
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(inj.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(inj, "_ydotool_env", lambda: {})
    calls = []

    def fake_run(cmd, *, input_bytes=None, timeout=4.0, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(inj, "_run", fake_run)
    monkeypatch.setattr(inj, "_ydotool_is_legacy_symbolic", lambda: True)
    assert inj.inject_key("enter").ok
    assert calls[-1] == ["ydotool", "key", "enter"]

    monkeypatch.setattr(inj, "_ydotool_is_legacy_symbolic", lambda: False)
    assert inj.inject_key("enter").ok
    assert calls[-1] == ["ydotool", "key", "28:1", "28:0"]


def test_same_physical_mouse_groups_voice_and_enter_without_double_grab(monkeypatch):
    # input_monitor needs evdev; the main test suite already fakes it in another
    # module, so import it after installing a minimal fake if necessary.
    import types
    if "evdev" not in sys.modules:
        fake = types.ModuleType("evdev")
        class E:
            BTN_MISC=0x100; BTN_TASK=0x117; EV_KEY=1; EV_REL=2; BTN={}; KEY={}
        fake.ecodes=E
        fake.InputDevice=object
        fake.UInput=object
        fake.list_devices=lambda: []
        sys.modules["evdev"] = fake
    import faco_voicetype.input_monitor as im

    closed = []
    class Dev:
        def __init__(self, fd):
            self.fd = fd
            self.path = "/dev/input/event9"
            self.name = "HyperX Mouse"
        def close(self):
            closed.append(self.fd)

    returned = [Dev(50), Dev(51)]
    monkeypatch.setattr(im, "find_bound_device", lambda _binding: returned.pop(0))
    voice = MouseBinding(path="/dev/input/event9", button_code=0x116)
    enter = MouseBinding(path="/dev/input/event9", button_code=0x117)
    monitor = im.MultiButtonMouseMonitor({"voice": voice, "enter": enter}, lambda _a, _v: None)
    groups, missing = monitor._open_groups()
    try:
        assert not missing
        assert len(groups) == 1
        group = next(iter(groups.values()))
        assert group["actions"][0x116] == ["voice"]
        assert group["actions"][0x117] == ["enter"]
        assert 51 in closed  # duplicate handle was closed instead of grabbed twice
    finally:
        for group in groups.values():
            group["dev"].close()


def test_transcriber_expressive_mode_requests_word_timestamps_and_applies_question(monkeypatch):
    from types import SimpleNamespace
    from faco_voicetype.transcriber import ModelSpec, Transcriber

    class FakeModel:
        def __init__(self):
            self.kwargs = None
        def transcribe(self, audio, **kwargs):
            self.kwargs = kwargs
            words = [
                SimpleNamespace(word="Can", start=0.0, end=0.2),
                SimpleNamespace(word=" you", start=0.22, end=0.4),
                SimpleNamespace(word=" test", start=0.42, end=0.6),
                SimpleNamespace(word=" this", start=0.62, end=0.8),
            ]
            seg = SimpleNamespace(text=" Can you test this.", words=words)
            info = SimpleNamespace(language="en", language_probability=0.99)
            return iter([seg]), info

    t = Transcriber()
    model = FakeModel()
    spec = ModelSpec("fake", "cpu", "int8")
    t._model = model
    t._spec = spec
    monkeypatch.setattr(t, "preload", lambda *args, **kwargs: spec)
    audio = np.zeros(16000, dtype=np.float32)
    text, returned = t.transcribe(
        audio,
        model="fake",
        device="cpu",
        compute_type="int8",
        expressive_punctuation=True,
        expression_level="balanced",
        sample_rate=16000,
    )
    assert returned == spec
    assert model.kwargs["word_timestamps"] is True
    assert text == "Can you test this?"


def test_multi_monitor_dispatches_both_same_mouse_actions_with_single_grab(monkeypatch):
    import types
    import time
    if "evdev" not in sys.modules:
        fake = types.ModuleType("evdev")
        class E:
            BTN_MISC=0x100; BTN_TASK=0x117; EV_KEY=1; EV_REL=2; BTN={}; KEY={}
        fake.ecodes=E; fake.InputDevice=object; fake.UInput=object; fake.list_devices=lambda: []
        sys.modules["evdev"] = fake
    import faco_voicetype.input_monitor as im

    state = {"grab": 0, "ungrab": 0, "ui_closed": 0, "forwarded": 0}
    class Dev:
        fd = 77
        path = "/dev/input/event77"
        name = "One Mouse"
        def grab(self): state["grab"] += 1
        def ungrab(self): state["ungrab"] += 1
        def close(self): pass
        def read(self):
            return [
                types.SimpleNamespace(type=im.ecodes.EV_KEY, code=0x116, value=1),
                types.SimpleNamespace(type=im.ecodes.EV_KEY, code=0x117, value=1),
                types.SimpleNamespace(type=im.ecodes.EV_REL, code=0, value=3),
            ]
    class UIObj:
        def write_event(self, _event): state["forwarded"] += 1
        def close(self): state["ui_closed"] += 1
    class UI:
        @staticmethod
        def from_device(_dev, name=None): return UIObj()
    monkeypatch.setattr(im, "UInput", UI)

    actions = []
    monitor = None
    def callback(action, value):
        actions.append((action, value))
        if len(actions) >= 2:
            monitor._stop.set()

    monitor = im.MultiButtonMouseMonitor(
        {
            "voice": MouseBinding(path="/dev/input/event77", button_code=0x116),
            "enter": MouseBinding(path="/dev/input/event77", button_code=0x117),
        },
        callback,
        suppress_actions={"voice": True, "enter": True},
    )
    group = {"dev": Dev(), "actions": {0x116: ["voice"], 0x117: ["enter"]}}
    monkeypatch.setattr(monitor, "_open_groups", lambda: ({77: group}, []))
    monkeypatch.setattr(im.select, "select", lambda r, w, x, timeout: ([77], [], []))
    monitor._stop.clear()
    monitor._run()
    assert actions == [("voice", 1), ("enter", 1)]
    assert state["grab"] == 1
    assert state["ungrab"] == 1
    # Both mapped button events are swallowed; only the unrelated movement is forwarded.
    assert state["forwarded"] == 1
    assert state["ui_closed"] == 1


def test_emphatic_pitch_and_energy_can_create_exclamation():
    sr = 16000
    normal_n = int(sr * 1.7)
    emphatic_n = int(sr * 0.3)
    normal = 0.15 * np.sin(2 * np.pi * 160 * np.arange(normal_n) / sr)
    emphatic = 0.45 * np.sin(2 * np.pi * 260 * np.arange(emphatic_n) / sr)
    audio = np.concatenate([normal, emphatic]).astype(np.float32)
    out, features = enhance_expression("That is fantastic.", audio, sr, level="balanced")
    assert features.emphasis_ratio > 1.8
    assert features.pitch_spread_ratio > 0.45
    assert out == "That is fantastic!"


def test_v102_config_migrates_without_losing_voice_button():
    old = {
        "enabled": True,
        "mouse": {"name": "HyperX Mouse", "uniq": "hx", "button_code": 278, "button_name": "BTN_BACK"},
        "trigger_mode": "hold",
        "model": "small",
        "append_space": True,
    }
    migrated = Settings.from_dict(old)
    assert migrated.mouse.name == "HyperX Mouse"
    assert migrated.mouse.button_code == 278
    assert migrated.enter_mouse.button_code is None
    assert migrated.expressive_punctuation is True
    assert migrated.expression_level == "balanced"


def test_hotfix_does_not_install_dependencies_or_cuda_again():
    text = (ROOT / "hotfix_existing.sh").read_text(encoding="utf-8")
    assert "pip install" not in text
    assert "apt-get" not in text
    assert "nvidia-cudnn" not in text
    assert "nvidia-cublas" not in text
