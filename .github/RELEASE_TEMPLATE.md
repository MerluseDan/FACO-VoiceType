# FACO VoiceType v1.2.1

Local global voice typing for Linux with mouse-mapped Voice and Enter/Submit, expressive punctuation, X11/Wayland injection, and reuse-first FACO deployment.

## Install or upgrade

Download `FACO_VoiceType_1.2.1.tar.gz` and its `.sha256` file. Verify, extract, and run:

```bash
sha256sum -c FACO_VoiceType_1.2.1.tar.gz.sha256
tar -xzf FACO_VoiceType_1.2.1.tar.gz
cd FACO_VoiceType_1.2.1
./install.sh
```

Existing v1.0/v1.1 users may run `./hotfix_existing.sh`; it uses the same canonical migration engine.

Do not run the whole installer with `sudo`.

## Highlights

- Canonical FACO source/state/data/runtime/model/registry layout.
- Reuse-first dependency and CUDA discovery before any network fallback.
- Local Faster-Whisper transcription with optional CUDA acceleration.
- Separate mouse mappings for Voice and real Enter/Return events.
- Expressive punctuation based on timing, pause, pitch, and energy.
- X11 and Wayland support.
- Correct isolation for explicit alternate `FACO_RESOURCE_ROOT` model discovery.

## Validation

- 36 automated tests, three consecutive passes.
- Python compilation and Bash syntax validation.
- Fresh-archive extraction and test pass.
- Isolated canonical migration simulation with legacy runtime/state, paths containing spaces, compatibility link, registry entries, and post-validation cleanup.

Hardware- and desktop-specific checks remain the responsibility of `selftest.py` and `diagnose.sh` on the target workstation.

See [CHANGELOG.md](CHANGELOG.md) and [VALIDATION.md](VALIDATION.md) for details.
