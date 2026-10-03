## What changed

Describe the problem and the solution.

## Validation

- [ ] `PYTHONPATH=src pytest -q`
- [ ] Python compilation passed
- [ ] Bash syntax passed
- [ ] Installer/canonical-layout tests were added or updated when relevant
- [ ] Host-specific checks are listed below when relevant

## Canonical and reuse guarantees

- [ ] Source/state/data/runtime/model boundaries remain intact
- [ ] Existing dependencies and shared resources are checked before downloads
- [ ] No credentials, runtime state, models, recordings, logs, or personal data are included
- [ ] User-facing changes are documented in `CHANGELOG.md`

## Host-specific notes

List any microphone, mouse, X11/Wayland, uinput, tray, or GPU checks that still need a real workstation.
