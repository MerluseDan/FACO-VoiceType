from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_progress_function_survives_nounset():
    """Regression: v1.0.1 referenced local `width` before assignment under set -u."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^progress\(\) \{\n.*?^\}\n", text)
    assert match, "progress() function not found"
    script = (
        "set -Eeuo pipefail\n"
        "TOTAL_STEPS=8\nCURRENT_STEP=0\nSTART_TS=$(date +%s)\n"
        + match.group(0)
        + "for n in 1 2 3 4 5 6 7 8; do progress \"test-$n\"; done\n"
    )
    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert "100%" in result.stdout
    assert "Step 8/8" in result.stdout


def test_autostart_exec_quotes_project_path():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'Exec="$APP_ROOT/run.sh"' in text
