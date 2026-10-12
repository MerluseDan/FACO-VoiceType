# FACO Resource Watch v1.0.3: Portable Linux Release

FACO Resource Watch is a free, open-source Linux desktop monitor with one-second sampling, CPU/RAM/GPU/VRAM/thermal tracking, and process-attributed GPU history.

### Release highlights

- Fresh installs now default to Linux XDG locations. **No private developer drive is assumed or scanned.**
- Optional custom install/history directories require explicit selection, validation, and mount checks.
- Previous v1.0.0–v1.0.2 history is migrated using SQLite backup without overwriting existing destination data.
- Persistent user-level systemd collector with optional boot-before-login service activation.
- Existing eight-card dashboard, seven time ranges, and GPU history/process inspection retained.
- MIT-licensed source code and verified portable installation tests.

### Install

Extract the ZIP and run `./install.sh`. Python 3.9+ and Linux are required. GNOME is needed for the clock-side extension; NVIDIA hardware/drivers are needed for GPU metrics. No third-party Python dependencies.

### Compatibility and verification

Primary target: Ubuntu 24.04, GNOME 46. Automated tests cover synthetic hardware and Chromium UI emulation. Real GNOME/driver testing must still occur on actual Ubuntu/NVIDIA systems.
