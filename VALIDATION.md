# FACO VoiceType v1.2.1 validation

Release validation covers both feature regressions and the new FACO canonical deployment architecture.

- Python bytecode compilation across application source, tests, and self-test.
- Bash syntax validation for installer, launcher, canonical migration/hotfix, diagnostics, and uninstall scripts.
- 36 automated tests covering existing VoiceType behavior plus canonical app/state/data/runtime path resolution, canonical config persistence, explicit path overrides, FACO manifest layout, canonical autostart, shared runtime launch, migration routing, and installer progress-step accounting.
- Existing regressions remain covered: X11 long-lived xclip ownership, deterministic evdev shutdown, same-mouse Voice + Enter dispatch, Wayland/ydotool variants, real Return-key injection, audio resampling, shared Whisper-model reuse, CUDA inference selection, expressive pause/question/exclamation behavior, and old configuration migration.
- An explicit `FACO_RESOURCE_ROOT` is verified as authoritative so isolated or alternate-root installs cannot silently select a model from the default production mount.
- The complete installer was simulated end-to-end as a disposable non-root Linux user from paths containing spaces.
- The simulation started from a legacy autostart-managed install with its own `.venv` and `~/.config/faco-voicetype` state.
- The installer migrated the legacy runtime into `_shared/environments/faco-voicetype`, migrated state into `_state/apps/voicetype`, created the compatibility symlink, deployed source into `FACO/apps/voicetype`, created FACO registry entries, validated the canonical runtime, removed the old duplicate `.venv`, wrote canonical autostart, and exercised both Enter prompts.
- The installer dependency path was verified to check installed Debian packages before apt and to test Python requirements with `--no-index` before any network fallback.
- Progress accounting is regression-tested so declared installer steps and actual progress calls cannot drift into the previous 110% display bug.

Host-only checks remain necessary for the workstation's real `/dev/input` nodes, microphone/PipeWire graph, desktop tray, ydotool socket, X11/Wayland focused-window behavior, and NVIDIA driver. These are surfaced through the application logs, `selftest.py`, and `diagnose.sh`; they are not falsely reported as exercised inside the build container.
