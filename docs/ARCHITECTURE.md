# Architecture

FACO VoiceType is a local Linux desktop daemon with four main paths through the application:

1. `input_monitor.py` captures configured mouse-button events with one evdev grab per device.
2. `audio.py` records and normalizes microphone audio.
3. `transcriber.py` runs Faster-Whisper and passes word timing to `prosody.py`.
4. `injector.py` writes text or a real Return key event into the focused X11 or Wayland application.

`app.py` coordinates these components, `ui.py` provides settings and tray controls, and `system_pulse.py` monitors resource pressure. Configuration is persisted through `config.py`.

## Canonical storage boundaries

The installation deliberately separates mutable and heavyweight resources from source code:

```text
${FACO_RESOURCE_ROOT}/
├── FACO/apps/voicetype/                  # deployed source
├── _state/apps/voicetype/                # persistent settings and state
├── _data/apps/voicetype/                 # application data
└── _shared/
    ├── environments/faco-voicetype/       # Python runtime
    ├── models/faster-whisper/             # shared model cache
    └── registry/
        ├── apps/voicetype.json
        └── capabilities/voicetype.json
```

The default `FACO_RESOURCE_ROOT` is `/media/owner/Faco Resources1`. Tests and alternate installations may override it without changing the internal layout.

## Injection strategy

- X11 uses clipboard ownership and desktop input helpers.
- Wayland uses available compositor-compatible clipboard tools and ydotool/uinput paths.
- Enter mapping emits a real key event rather than inserting a newline character.

The application validates available helpers at runtime and reports missing integration through diagnostics rather than silently claiming success.

## Resource reuse

The installer treats existing runtimes and models as assets. It validates local packages with networking disabled, checks shared caches and compatible CUDA locations, and only then permits network fallback. This keeps large downloads explicit and prevents multiple heavyweight copies from accumulating.
