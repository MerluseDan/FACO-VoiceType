# FACO Resource Watch v1.0.3 · Public Linux Portability and Release QA

**Date:** October 12, 2026  
**Delivery:** Source-ready and portable ZIP. **GitHub status:** Source mirrored on a public branch of an existing repository; a standalone Resource Watch repository is still unavailable to create via the connected GitHub tool. The original release ZIP included a GitHub CLI helper; this source-only staging tree omits it.

## Scope and compatibility

This release replaces the old first-preference removable-drive installation with **XDG Linux defaults for all fresh installations**. It also provides explicit, validated custom storage, safe historical database migration, mount-aware background operation, and a public MIT license. The existing 1.0.2 visual dashboard, component charts, seven time scales, and background collector are retained.

The test host is a Linux container with Python 3.13, Node 22, and Chromium via Playwright. The test environment has no active GNOME Shell session, physical NVIDIA GPU, or actual workstation systemd user manager. Chrome navigation to localhost is restricted; Chromium GUI tests inject real HTML/CSS/JS into a blank page and intercept API fetches with synthetic samples. **Physical GPU/driver performance, clock-side indicator placement on actual GNOME, boot persistence across a real reboot, and external-drive removal under live hardware remain host verification items.**

## Component status

| Component | Status |
|---|---|
| ★ Fresh-install XDG application, data, config, state/logs paths | Passed Sandboxed Install and Path Assertions |
| ★ Hardcoded developer storage preference removed | Passed Static Source Inspection |
| ★ Optional custom install/data paths with mount validation | Passed Custom-Path Tests |
| ★ Explicit OS Default / Cancel choice on missing custom storage | Passed Noninteractive and Recovery Cases |
| ★ Protection when custom data volume disappears after boot | Passed Mount-Guard Regression Tests |
| ★ SQLite history migration (including committed WAL pages) | Passed Database Backup Verification |
| ★ Actual v1.0.2 → v1.0.3 installer upgrade and history preservation | Passed End-to-End Linux Integration |
| ★ Clean install, reinstall, uninstall, purge and unrelated-path protections | Passed Automated Installer Tests |
| ★ MIT license, publish helper, README and GitHub QA workflow | Passed Package/Syntax Checks; GitHub Publication Not Yet Performed |
| │ Background collector with restart and boot agent | Passed Live Service and Unit Tests; Needs Actual Reboot Test |
| │ CPU/RAM/thermal SQLite history and active process attribution | Passed Local Service and Regression Tests |
| │ NVIDIA GPU/VRAM/video and process history | Passed Synthetic NVML Regression; Needs Physical NVIDIA Test |
| │ Eight category charts and seven history scales | Passed Chromium GUI Emulation |
| │ GNOME clock-side extension | Passed JavaScript Simulation; Needs Live GNOME Testing |
| │ CSV export, app filtering/sorting and UI redundancy audit | Passed Chromium Interaction Tests |

## Tests actually executed

1. **45 Python automated regression tests: Passed.** Includes installer portability, XDG override support, history migration from an open SQLite WAL database, unavailable custom-drive choices, permission-safe uninstall, unrelated launcher protection, storage mount-guard checks, boot agent behavior, CPU/GPU sampling and local API restrictions.
2. **Node dashboard interface simulation: Passed.** Eight clickable component cards; seven scales (1s/1m/30m/1h/6h/24h/7d); current process tables; GPU process history; filtering and sorting; CSV; pause/resume.
3. **Node GNOME extension simulation: Passed.** Indicator placement attempt immediately before the clock, 1-second updates, startup/unavailable sensor UI, dashboard launch and timer cleanup.
4. **Real Chromium GUI emulation: Passed.** `tests/gui_emulation.py` checked every component and time-scale button, process history inspector, pause/resume, CSV download, 1920×1080 layout, 320px layout, no horizontal clipping and no browser JavaScript errors. Screenshots contain **synthetic telemetry**.
5. **Full legacy upgrade + live service integration: Passed.** Installed the real v1.0.2 archive in a sandboxed home, wrote a real SQLite historical record, upgraded via the new v1.0.3 installer, verified preservation of historical data in the new XDG directory and unmodified legacy database, launched the newly installed collector, queried `/api/health`, `/api/current` and `/api/history`, and confirmed multiple new one-second CPU/RAM history rows.
6. **Systemd and startup configuration:** User service syntax checked with `systemd-analyze verify` during installer tests; service enable commands simulated. Actual user-session activation at a desktop login and restart after a physical reboot remain untested.
7. **Static and release checks:** Bash syntax, Python compilation, JavaScript tests, SHA-256 manifest check and extracted ZIP installation checks. The GitHub workflow is authored but has not run in GitHub Actions yet.

## Linux paths and upgrade contract

- **Application code:** `$XDG_DATA_HOME/faco-resource-watch/app` (default `~/.local/share/faco-resource-watch/app`).
- **History:** `$XDG_DATA_HOME/faco-resource-watch/data/history.sqlite3`.
- **Configuration:** `$XDG_CONFIG_HOME/faco-resource-watch`.
- **Logs:** `$XDG_STATE_HOME/faco-resource-watch/logs`.
- **Launcher:** `~/.local/bin/faco-resource-watch`.
- **Desktop entry:** `$XDG_DATA_HOME/applications/faco-resource-watch.desktop`.
- **User service:** `$XDG_CONFIG_HOME/systemd/user/faco-resource-watch.service`.
- **GNOME extension:** `$XDG_DATA_HOME/gnome-shell/extensions/faco-resource-watch@faco.local`.

No specific user's home directory, mounted drive name, or private development path is required to install or run the public app. New installations never inspect those private paths. A previous installation's saved configuration may specify a removable drive; the upgrade uses this **only as historical migration input**, with an explicit missing-drive choice rather than a silent fallback.

SQLite backup copies committed WAL state into new history and verifies `PRAGMA quick_check` before switching the configured database. An existing destination DB is not overwritten. Legacy code/data are not deleted automatically during cross-location upgrades.

## Safety and known limits

- The application needs Linux and Python 3.9+, with a GNOME Shell session for the top-panel UI and compatible NVIDIA drivers for GPU telemetry. A user-level service does not require root; before-login operation may require `loginctl enable-linger` authorization. The uninstaller does not disable user-wide linger settings.
- If custom storage under `/media`, `/mnt` or `/run/media` is not mounted, installation refuses the path. An unavailable custom path prompts **Use OS Default Location** or **Cancel Installation**; noninteractive runs cancel unless `FACO_WATCH_MISSING_CUSTOM=default` explicitly requests the OS default.
- Only system-level historical CPU/RAM/temperature data and historical GPU processes are recorded. **Per-process historical CPU/RAM usage is not retained**; the CPU/RAM app table shows **current** processes. NVML can omit per-process SM/encoder metrics; missing values are labelled unavailable.
- The browser dashboard is served from loopback on port 18777, has host/origin protections, and does not send telemetry to third parties. Local process names can be sensitive; do not publicly share real history databases or logs.
- A simulated GPU workload, successful Chromium rendering, and passing Linux container tests do not verify performance or correctness on the maintainer's actual Ubuntu/RTX desktop. Final hardware checks must still be performed there.

## Remaining GitHub step

The connected GitHub account (`MerluseDan`) contains a private FACO9000 repository and an unrelated public VoiceType repository, but no standalone `FACO-Resource-Watch` repository. The available connector cannot create a new repository or upload GitHub Releases. To avoid publishing into the wrong repository, this work produces a repository-ready, MIT-licensed ZIP and an opt-in **`scripts/publish_github.sh`** helper. It creates `MerluseDan/FACO-Resource-Watch` as a public repository and uploads this v1.0.3 ZIP after the owner authenticates with the GitHub CLI. No secret credentials are included in any artifact.
