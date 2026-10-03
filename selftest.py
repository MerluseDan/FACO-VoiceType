#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(SRC))

failures = []

def check(name, fn):
    try:
        value = fn()
        print(f"[PASS] {name}: {value}")
    except Exception as exc:
        failures.append((name, str(exc)))
        print(f"[FAIL] {name}: {exc}")

check("Python", lambda: sys.version.split()[0])
check("PySide6", lambda: __import__("PySide6").__version__)
check("numpy", lambda: __import__("numpy").__version__)
check("sounddevice", lambda: __import__("sounddevice").__version__)
check("evdev", lambda: __import__("evdev").__version__ if hasattr(__import__("evdev"), "__version__") else "imported")
check("faster_whisper", lambda: getattr(__import__("faster_whisper"), "__version__", "imported"))
check("ydotool", lambda: shutil.which("ydotool") or (_ for _ in ()).throw(RuntimeError("missing")))
check("wl-copy", lambda: shutil.which("wl-copy") or (_ for _ in ()).throw(RuntimeError("missing")))
check("xdotool", lambda: shutil.which("xdotool") or (_ for _ in ()).throw(RuntimeError("missing")))

from faco_voicetype.config import ConfigStore, Settings
from faco_voicetype.injector import session_type
from faco_voicetype.prosody import enhance_expression
from faco_voicetype.resources import shared_model_download_root
from faco_voicetype.paths import app_root, state_root, data_root, environment_root
from faco_voicetype.transcriber import Transcriber

check("Session detector", session_type)
check("Canonical app root", lambda: str(app_root()))
check("Canonical state root", lambda: str(state_root()))
check("Canonical data root", lambda: str(data_root()))
check("Canonical runtime root", lambda: str(environment_root()))
check("Model storage", lambda: str(shared_model_download_root()))
check("CTranslate2 CUDA detection", lambda: f"cuda_devices={int(Transcriber.cuda_available())}")

def expression_smoke():
    import numpy as np
    text, _ = enhance_expression("Can you hear me.", np.zeros(16000, dtype=np.float32), 16000, level="balanced")
    if text != "Can you hear me?":
        raise RuntimeError(f"unexpected punctuation result: {text!r}")
    return text

check("Expressive punctuation", expression_smoke)

if failures:
    print("\nSelf-test completed with failures:")
    for name, err in failures:
        print(f" - {name}: {err}")
    raise SystemExit(1)
print("\nSelf-test PASS")
