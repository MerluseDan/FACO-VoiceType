# Contributing to FACO VoiceType

Thanks for helping improve local voice typing on Linux.

## Before opening a change

- Search existing issues and pull requests.
- Use a bug report for reproducible failures and a feature request for proposed behavior.
- Keep changes focused. Separate unrelated refactors from fixes.
- Never commit model files, virtual environments, recorded audio, runtime state, logs, credentials, or machine-specific configuration.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest
PYTHONPATH=src pytest -q
```

The application targets Python 3.10 or newer on Debian/Ubuntu-family desktop Linux.

## Required checks

Run these before submitting a pull request:

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src tests selftest.py
for script in *.sh scripts/*.sh; do bash -n "$script"; done
```

Changes to the installer or launcher should also be exercised with an isolated `FACO_RESOURCE_ROOT` whose path contains spaces. Do not point installer tests at a real production FACO root.

## Canonical-layout contract

The following are project invariants:

- Source, persistent state, data, Python runtime, models, registry metadata, and logs stay separated.
- The default FACO root remains `/media/owner/Faco Resources1`; alternate roots use `FACO_RESOURCE_ROOT`.
- Installed system packages are checked before `apt` runs.
- Python requirements are checked offline before package-index fallback.
- Existing environments, caches, models, and compatible CUDA libraries are reused before downloads.
- Large unavoidable downloads are announced with reason and destination.
- A legacy runtime is deleted only after the canonical replacement passes validation.
- Installer failures remain visible and actionable.

Pull requests that alter these rules need matching tests and documentation.

## Pull requests

Describe the problem, the approach, the validation performed, and any remaining host-specific checks. Add or update tests for behavior changes and update `CHANGELOG.md` when users will notice the change.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
