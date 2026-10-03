from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_explicit_faco_root_is_authoritative(tmp_path, monkeypatch):
    monkeypatch.setenv("FACO_RESOURCE_ROOT", str(tmp_path))
    import faco_voicetype.resources as resources
    assert [root.resolve() for root in resources.faco_roots()] == [tmp_path.resolve()]


def test_shared_model_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("FACO_RESOURCE_ROOT", str(tmp_path))
    model = tmp_path / "_shared" / "models" / "faster-whisper-small"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.bin").write_bytes(b"x")
    import faco_voicetype.resources as resources
    resources.discover_local_whisper_models.cache_clear()
    assert resources.find_local_model("small") == str(model.resolve())


def test_transcriber_resolves_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("FACO_RESOURCE_ROOT", str(tmp_path))
    model = tmp_path / "_shared" / "models" / "faster-whisper-small"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.bin").write_bytes(b"x")
    import faco_voicetype.resources as resources
    resources.discover_local_whisper_models.cache_clear()
    from faco_voicetype.transcriber import Transcriber
    t = Transcriber()
    monkeypatch.setattr(t, "cuda_available", lambda: False)
    spec = t._resolve("small", "auto", "auto")
    assert spec.model == str(model.resolve())
    assert spec.device == "cpu"
    assert spec.compute_type == "int8"


def test_wayland_injection_uses_symbolic_ydotool(monkeypatch):
    import faco_voicetype.injector as inj
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(inj.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(inj.os.path, "exists", lambda _p: False)
    calls = []

    def fake_run(cmd, *, input_bytes=None, timeout=4.0, env=None):
        calls.append((cmd, input_bytes, env))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(inj, "_run", fake_run)
    result = inj.inject_text("hello", preserve_clipboard=False)
    assert result.ok
    assert any(cmd == ["ydotool", "key", "ctrl+v"] for cmd, _input, _env in calls)
    assert any(cmd[:1] == ["wl-copy"] and payload == b"hello" for cmd, payload, _env in calls)


def test_audio_resampler_without_sounddevice_dependency(monkeypatch):
    # Import audio with a minimal fake sounddevice module; only the pure resampler is exercised here.
    class FakeSoundDevice:
        class InputStream:
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice())
    sys.modules.pop("faco_voicetype.audio", None)
    audio = importlib.import_module("faco_voicetype.audio")
    src = np.linspace(-1, 1, 48000, dtype=np.float32)
    out = audio._resample_linear(src, 48000, 16000)
    assert out.dtype == np.float32
    assert len(out) == 16000
    assert np.isfinite(out).all()


def test_system_pulse_compact_text():
    from faco_voicetype.system_pulse import PulseSnapshot
    snap = PulseSnapshot(cpu_percent=12, ram_used_gb=3, ram_total_gb=8, app_ram_gb=.2,
                         gpu_util=40, vram_used_gb=2, vram_total_gb=16, gpu_temp_c=55,
                         input_name="mic", output_name="speakers")
    text = snap.compact()
    assert "CPU 12%" in text
    assert "VRAM 2.0/16.0 GB" in text
    assert "Mic mic" in text


def test_x11_xclip_owner_is_not_waited_on(monkeypatch):
    """Regression: xclip input mode stays alive as the X11 selection owner."""
    import faco_voicetype.injector as inj

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(inj.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(inj.time, "sleep", lambda _s: None)

    run_calls = []
    def fake_run(cmd, *, input_bytes=None, timeout=4.0, env=None):
        run_calls.append((cmd, input_bytes, timeout, env))
        if cmd[:4] == ["xclip", "-selection", "clipboard", "-o"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"previous", stderr=b"")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
    monkeypatch.setattr(inj, "_run", fake_run)

    popen_payloads = []
    class FakeStdin:
        def __init__(self): self.data = b""
        def write(self, data): self.data += data; return len(data)
        def flush(self): pass
        def close(self): popen_payloads.append(self.data)
    class FakePopen:
        def __init__(self, cmd, **kwargs):
            assert cmd == ["xclip", "-selection", "clipboard", "-i"]
            self.stdin = FakeStdin()
        def poll(self):
            # Healthy xclip may still be alive because it owns the selection.
            return None
    monkeypatch.setattr(inj.subprocess, "Popen", FakePopen)

    result = inj.inject_text("hello", preserve_clipboard=True, restore_delay_ms=100)
    assert result.ok
    assert result.method == "xclip + xdotool"
    assert popen_payloads == [b"hello", b"previous"]
    assert not any(cmd[:4] == ["xclip", "-selection", "clipboard", "-i"] for cmd, *_ in run_calls)


def test_x11_injector_with_long_lived_fake_xclip_process(tmp_path, monkeypatch):
    """Process-level regression: a healthy long-lived clipboard owner must not block injection."""
    import signal
    import time
    import faco_voicetype.injector as inj

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload_file = tmp_path / "payload"
    pid_file = tmp_path / "pid"
    xclip = bin_dir / "xclip"
    xclip.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *\" -o \"*) printf previous; exit 0;;\n"
        "esac\n"
        f"cat > '{payload_file}'\n"
        f"echo $$ > '{pid_file}'\n"
        "exec sleep 30\n",
        encoding="utf-8",
    )
    xdotool = bin_dir / "xdotool"
    xdotool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    xclip.chmod(0o755)
    xdotool.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH','')}")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    started = time.monotonic()
    result = inj.inject_text("field test", preserve_clipboard=False)
    elapsed = time.monotonic() - started
    try:
        assert result.ok, result.message
        assert elapsed < 1.0
        assert payload_file.read_bytes() == b"field test"
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
