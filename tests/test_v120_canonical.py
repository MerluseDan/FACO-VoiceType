from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_canonical_paths_follow_faco_resource_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FACO_RESOURCE_ROOT", str(tmp_path))
    for key in (
        "FACO_VOICETYPE_APP_ROOT",
        "FACO_VOICETYPE_STATE_ROOT",
        "FACO_VOICETYPE_DATA_ROOT",
        "FACO_VOICETYPE_ENV_ROOT",
        "FACO_SHARED_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    from faco_voicetype.paths import app_root, data_root, environment_root, shared_root, state_root
    assert app_root() == tmp_path / "FACO" / "apps" / "voicetype"
    assert state_root() == tmp_path / "_state" / "apps" / "voicetype"
    assert data_root() == tmp_path / "_data" / "apps" / "voicetype"
    assert shared_root() == tmp_path / "_shared"
    assert environment_root() == tmp_path / "_shared" / "environments" / "faco-voicetype"


def test_config_default_uses_canonical_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FACO_RESOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("FACO_VOICETYPE_STATE_ROOT", raising=False)
    from faco_voicetype.config import ConfigStore, Settings
    store = ConfigStore()
    store.save(Settings(model="small"))
    expected = tmp_path / "_state" / "apps" / "voicetype" / "config.json"
    assert store.path == expected
    assert expected.exists()


def test_explicit_state_override_wins(tmp_path, monkeypatch):
    override = tmp_path / "custom-state"
    monkeypatch.setenv("FACO_VOICETYPE_STATE_ROOT", str(override))
    from faco_voicetype.config import ConfigStore, Settings
    store = ConfigStore()
    store.save(Settings())
    assert store.path == override / "config.json"


def test_module_manifest_declares_canonical_layout():
    data = json.loads((ROOT / "faco_module.json").read_text(encoding="utf-8"))
    paths = data["canonical_paths"]
    assert data["version"] == "1.2.1"
    assert data["module_type"] == "desktop_daemon"
    assert paths["app"].endswith("/FACO/apps/voicetype")
    assert paths["state"].endswith("/_state/apps/voicetype")
    assert paths["data"].endswith("/_data/apps/voicetype")
    assert paths["runtime"].endswith("/_shared/environments/faco-voicetype")


def test_installer_deploys_to_canonical_tree_and_not_payload_venv():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'APP_ROOT="$FACO_ROOT/FACO/apps/voicetype"' in text
    assert 'STATE_ROOT="$FACO_ROOT/_state/apps/voicetype"' in text
    assert 'DATA_ROOT="$FACO_ROOT/_data/apps/voicetype"' in text
    assert 'ENV_ROOT="$SHARED_ROOT/environments/faco-voicetype"' in text
    assert "--exclude '.venv/'" in text
    assert 'Exec="$APP_ROOT/run.sh"' in text


def test_hotfix_routes_through_canonical_migration_without_its_own_download_logic():
    text = (ROOT / "hotfix_existing.sh").read_text(encoding="utf-8")
    assert 'exec "$HERE/install.sh"' in text
    assert "pip install" not in text
    assert "nvidia-cudnn" not in text
    assert "nvidia-cublas" not in text


def test_run_script_uses_canonical_shared_environment():
    text = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert 'ENV_ROOT="${FACO_VOICETYPE_ENV_ROOT:-$SHARED_ROOT/environments/faco-voicetype}"' in text
    assert 'exec "$ENV_ROOT/bin/python" -m faco_voicetype' in text
    assert 'CUDA_PATH_FILE="$STATE_ROOT/cuda_lib_paths"' in text


def test_installer_progress_step_count_matches_declared_total():
    import re
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    declared = int(re.search(r"^TOTAL_STEPS=(\d+)$", text, re.M).group(1))
    calls = len(re.findall(r'^progress "', text, re.M))
    assert declared == calls, f"declared {declared} steps but found {calls} progress calls"


def test_voice_type_has_no_manual_release_declaration_gate():
    ui = (ROOT / "src" / "faco_voicetype" / "ui.py").read_text(encoding="utf-8")
    controller = (ROOT / "src" / "faco_voicetype" / "app.py").read_text(encoding="utf-8")
    assert "Declare Tested" not in ui
    assert "declare_tested_requested" not in ui
    assert "set_tested_state" not in ui
    assert "tested_marker_path" not in controller
    assert "declare_tested" not in controller
    assert 'self.save_button = QPushButton("Save settings")' in ui
