# FACO VoiceType

[![Tests](https://github.com/MerluseDan/FACO-VoiceType/actions/workflows/tests.yml/badge.svg)](https://github.com/MerluseDan/FACO-VoiceType/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/MerluseDan/FACO-VoiceType)](https://github.com/MerluseDan/FACO-VoiceType/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local, global voice typing for Linux. Hold or toggle a mapped mouse button, speak, and FACO VoiceType transcribes into the focused application. A second mouse button can emit a real Enter/Return key event.

VoiceType runs Faster-Whisper locally, supports X11 and Wayland injection paths, and adds punctuation using word timing plus local pause, pitch, and energy analysis. Audio is not sent to a hosted transcription service.

Current release: **v1.2.1**

## Highlights

- Map separate mouse buttons to Voice and Enter/Submit, including two buttons on one physical mouse.
- Choose hold-to-talk or toggle recording.
- Type into the currently focused application on X11 or Wayland.
- Use CUDA when available, with an explicit CPU fallback.
- Add commas, sentence boundaries, questions, and exclamation marks with adjustable expression sensitivity.
- Reuse existing FACO runtimes, models, wheel caches, and CUDA libraries before downloading anything.
- Pause from the tray to unload Whisper and release VRAM/RAM.
- Start automatically with the graphical desktop session.
- Keep source, state, data, models, runtime, registry entries, and logs in separate canonical locations.

## Platform and requirements

VoiceType targets Debian/Ubuntu-family desktop Linux with Python 3.10 or newer. The installer configures the required microphone, input-device, tray, clipboard, and keyboard-injection packages.

The default installation expects the FACO resource volume at:

```text
/media/owner/Faco Resources1
```

To use another mounted root while preserving the same layout beneath it, set `FACO_RESOURCE_ROOT` before running the installer.

## Install

Clone the repository or download a release archive, then run the installer as your normal desktop user:

```bash
git clone https://github.com/MerluseDan/FACO-VoiceType.git
cd FACO-VoiceType
./install.sh
```

Do **not** run the whole installer with `sudo`. It requests elevation only for system packages, udev rules, uinput, and ownership repair.

For a different mounted FACO root:

```bash
FACO_RESOURCE_ROOT="/path/to/FACO-root" ./install.sh
```

The installer stays open on failure so its diagnostic output remains visible. On success, press Enter to launch VoiceType from the canonical installation; after the app exits, press Enter again to close the installer.

### Upgrade an existing v1.0 or v1.1 installation

From the extracted v1.2.1 release:

```bash
./hotfix_existing.sh
```

The updater uses the same canonical migration engine as the installer. It preserves settings, model caches, CUDA configuration, autostart integration, and the existing working Python runtime whenever they pass validation.

## First run

1. Open VoiceType from the application menu or run the canonical launcher.
2. Choose **Map Voice button**, then press the desired mouse button.
3. Optionally choose **Map Enter button**, then press a different mouse button.
4. Select hold-to-talk or toggle mode and save settings.
5. Focus a text field, activate Voice, speak, and release or toggle Voice off.

Expressive punctuation is enabled by default at the Balanced sensitivity level.

## Canonical FACO layout

| Purpose | Default location |
| --- | --- |
| Application source | `/media/owner/Faco Resources1/FACO/apps/voicetype` |
| Persistent state | `/media/owner/Faco Resources1/_state/apps/voicetype` |
| Application data | `/media/owner/Faco Resources1/_data/apps/voicetype` |
| Python runtime | `/media/owner/Faco Resources1/_shared/environments/faco-voicetype` |
| Whisper models | `/media/owner/Faco Resources1/_shared/models/faster-whisper` |
| App registry | `/media/owner/Faco Resources1/_shared/registry/apps/voicetype.json` |
| Capability registry | `/media/owner/Faco Resources1/_shared/registry/capabilities/voicetype.json` |
| Logs | `~/Desktop/Logs/FACO VoiceType/` |

The compatibility path `~/.config/faco-voicetype` points to canonical state so older tooling retains access to settings.

## Dependency-reuse rules

The installer follows a strict reuse-first policy:

1. Check installed system packages before running `apt`.
2. Migrate a working legacy `.venv` into the canonical shared environment instead of rebuilding it.
3. Verify Python requirements offline first with `--no-index` and local FACO caches.
4. Search system, FACO shared, cached-wheel, and migrated-runtime locations for CUDA/cuDNN/cuBLAS.
5. Explain any unavoidable large download, why it is needed, and where it will be stored before it starts.
6. Remove the legacy heavyweight runtime only after the canonical runtime passes validation.

These rules are release invariants. Contributions must not replace them with unconditional downloads or duplicate installations.

## Run and diagnose

After installation:

```bash
'/media/owner/Faco Resources1/FACO/apps/voicetype/run.sh'
```

Run diagnostics:

```bash
'/media/owner/Faco Resources1/FACO/apps/voicetype/diagnose.sh'
```

If you use a custom `FACO_RESOURCE_ROOT`, export it for these commands as well.

Diagnostics report canonical paths, runtime/state/data availability, injection helpers, ydotoold, mouse/uinput access, NVIDIA status, the compatibility bridge, and the Python self-test.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest
PYTHONPATH=src pytest -q
```

Also run the release-level checks:

```bash
python -m compileall -q src tests selftest.py
for script in *.sh scripts/*.sh; do bash -n "$script"; done
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [the architecture notes](docs/ARCHITECTURE.md), and [the release checklist](docs/RELEASING.md).

## Validation scope

The automated suite covers the core behavior, installer rules, migration paths, expressive punctuation, same-mouse dual-button dispatch, X11/Wayland injection variants, audio resampling, resource reuse, and canonical path resolution.

Real mouse buttons, the microphone/PipeWire graph, desktop tray, focused-window injection, the ydotool socket, and the NVIDIA driver remain host-specific. Run `selftest.py` and `diagnose.sh` on the target workstation after installation. See [VALIDATION.md](VALIDATION.md) for the full boundary.

## License

FACO VoiceType is released under the [MIT License](LICENSE).
