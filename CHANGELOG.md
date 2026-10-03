# Changelog

All notable changes to FACO VoiceType are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.1] - 2026-10-03

### Added

- Public repository documentation, community health files, issue forms, and continuous integration.

### Fixed

- Treat an explicit `FACO_RESOURCE_ROOT` as authoritative during model discovery instead of falling through to the default production mount.

## 1.2.0 - 2026-09-13

### Added

- Canonical FACO application, state, data, shared-runtime, model, and registry layout.
- Environment-variable overrides for controlled testing and alternate FACO resource roots.
- FACO app and capability registry manifests.
- Offline-first dependency verification and shared CUDA/runtime discovery.
- Canonical deployment, migration, path-resolution, and installer-progress regression coverage.

### Changed

- Existing Python environments are migrated and validated before any replacement download.
- Legacy state is moved to `_state/apps/voicetype` with a compatibility symlink.
- Extracted launchers redirect to the canonical installation.
- Obsolete heavyweight runtime copies are removed only after canonical validation succeeds.

## 1.1.0

### Added

- Independent mouse mapping for a real Enter/Return key event.
- Same-device Voice and Enter dispatch through one evdev grab.
- Expressive punctuation based on word timing, pauses, pitch movement, and vocal energy.
- Conservative, Balanced, and Expressive sensitivity levels.

## 1.0.0

### Added

- Initial Linux mouse-button voice typing daemon.
- Hold-to-talk and toggle recording modes.
- Local Faster-Whisper transcription with CUDA and CPU paths.
- X11 and Wayland focused-text injection.
- Tray controls, autostart, diagnostics, and local logging.

[Unreleased]: https://github.com/MerluseDan/FACO-VoiceType/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/MerluseDan/FACO-VoiceType/releases/tag/v1.2.1
