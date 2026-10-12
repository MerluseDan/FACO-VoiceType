# FACO Resource Watch

Free, open-source Linux resource monitoring. **Release v1.0.3: portable Linux source distribution.**

Monitor CPU, RAM, NVIDIA GPU, VRAM, temperatures, and video encode/decode use from a compact GNOME Shell indicator to the **left of the top-panel clock**. Click the readout to open live and historical performance charts. The background collector remains active after the dashboard closes.

**Primary target:** Ubuntu 24.04 and GNOME 46. Other recent GNOME Shell versions are supported where the included extension APIs remain compatible; actual version-specific desktop tests are needed. **Required:** Linux and Python 3.9+. **Recommended:** GNOME Shell, systemd user services, NVIDIA drivers for GPU telemetry. No pip dependencies, cloud account, or `sudo` for normal login-time operation.

## Preview

Screenshots are included in the downloadable complete release package, not this source-only staging tree.

*Chromium interface test with simulated readings, not a screenshot of a physical NVIDIA GPU test.*

## Install

Download and extract the release ZIP, then from the extracted folder:

```bash
./install.sh
```

That's it. The installer sets up a user-level background service, application launcher, and GNOME Shell extension. If the indicator doesn't appear immediately, sign out and back in and run:

```bash
gnome-extensions enable faco-resource-watch@faco.local
```

Click the indicator, launch **FACO Resource Watch** in the application menu, or run:

```bash
~/.local/bin/faco-resource-watch open
```

### Default Linux locations

| Component | Default path |
|---|---|
| Application code | `$XDG_DATA_HOME/faco-resource-watch/app` (`~/.local/share/faco-resource-watch/app`) |
| Seven-day SQLite history | `$XDG_DATA_HOME/faco-resource-watch/data/history.sqlite3` |
| Settings | `$XDG_CONFIG_HOME/faco-resource-watch` (`~/.config/faco-resource-watch`) |
| Logs | `$XDG_STATE_HOME/faco-resource-watch/logs` (`~/.local/state/faco-resource-watch/logs`) |
| Launcher | `~/.local/bin/faco-resource-watch` |
| User service | `$XDG_CONFIG_HOME/systemd/user/faco-resource-watch.service` |
| Panel extension | `$XDG_DATA_HOME/gnome-shell/extensions/faco-resource-watch@faco.local` |

**No private, removable, or developer-specific drive is scanned or selected for fresh installs.** Paths follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/0.8/). External locations are strictly opt-in:

```bash
FACO_WATCH_INSTALL_DIR='/your/actual/mounted/path/faco-watch-app' ./install.sh
# Optionally store history on a separate mounted volume:
FACO_WATCH_DATA_DIR='/your/actual/mounted/path/faco-watch-data' ./install.sh
```

Custom destinations require an existing, writable parent directory. Destinations under `/media`, `/run/media` or `/mnt` must have a real mounted ancestor. If a custom location or a **previous installation's configured drive** is unavailable, the installer explicitly offers **Use OS Default Location** or **Cancel Installation**. Noninteractive installs cancel in that situation unless `FACO_WATCH_MISSING_CUSTOM=default` is set to choose the OS default explicitly.

## Upgrade from v1.0.0–v1.0.2

Run the new `./install.sh` directly, **without uninstalling**. The installer stops the old collector, uses SQLite's online backup API to copy the previous history database safely into the default XDG data directory, and switches the service to the new code. Existing destination history is never overwritten. Legacy log files are copied once when available. The old application directory remains untouched when upgrading between different paths, so you can inspect it later. If previous storage is missing, installation refuses to claim the history was preserved and asks you to choose between starting with OS defaults or cancelling.

If you previously chose a custom location and want to keep using it, set `FACO_WATCH_INSTALL_DIR` and, if needed, `FACO_WATCH_DATA_DIR` explicitly when upgrading. **The public installer never inserts machine-specific paths into its defaults.**

## Features

- Eight clickable metric cards: **CPU, RAM, GPU, VRAM, CPU temperature, GPU temperature, NVIDIA video encoder, NVIDIA video decoder**.
- One dedicated historical chart per selected component and a sortable table of **current** processes consuming the related resources.
- Chart scales: **1-second live** (rolling 15 seconds), **1 minute**, **30 minutes**, **1 hour**, **6 hours**, **24 hours**, and **7 days**.
- Independent one-second history of CPU/RAM/thermal metrics and NVIDIA GPU/video metrics, with SQLite seven-day retention.
- Historical GPU process use (including per-process VRAM and SM where NVML can supply them), historical GPU process charts, and CSV export.
- Automatically starts at login; optional pre-login boot startup using `loginctl enable-linger`. The service continues logging if the dashboard is closed and is configured to restart on failures.
- Fully local monitoring: localhost-only read API (`127.0.0.1:18777`), without telemetry uploads, external trackers, or remote dependencies.

### What the application does **not** pretend to measure

CPU process percentages are normalized to one logical CPU core, while system CPU is across all cores. Shared RAM pages can appear in multiple process RSS readings. GPU process SM/video utilization depends on NVIDIA driver capabilities and permissions; the monitor displays `—` when unavailable rather than inventing numbers. CPU and GPU temperatures are device sensors and cannot be assigned to individual programs. Current CPU and RAM per-process snapshots are *not* retained historically; total CPU/RAM history and NVIDIA historical process samples are retained. Actual GPU sensors require supported NVIDIA hardware.

## Background service

```bash
systemctl --user status faco-resource-watch.service
systemctl --user is-enabled faco-resource-watch.service
~/.local/bin/faco-resource-watch doctor
~/.local/bin/faco-resource-watch open
```

The service normally starts at login. To enable before-login startup and persistence after logout, if allowed by your system's administrator:

```bash
sudo loginctl enable-linger "$(id -un)"
```

This setting is user-wide, so the uninstaller **does not** disable it automatically.

## Uninstall

From the installed application directory or extracted ZIP:

```bash
./uninstall.sh                  # Remove app + service + indicator, keep history
./uninstall.sh --purge-data     # Also delete the app's SQLite history and collector logs
```

The uninstaller does not recursively delete arbitrary custom data directories or change loginctl linger settings. Any leftover legacy folder from an earlier release can be removed separately after confirming your data migrated.

## Developer tests

The release contains deterministic collector, database, install/upgrade, GNU/Linux service, and dashboard tests. On Linux:

```bash
python3 -m unittest discover -s tests -q
node tests/test_frontend.cjs
node tests/test_gnome_extension.cjs
./verify.sh
```

Optional GUI emulation uses Playwright/Chromium from the developer's own environment; it is not required by end users. See `QA_REPORT.md` for exact tests and unverified platform items.

## Security and license

Resource collection operates without root privileges; process names and resource data stay on the local machine. Dashboard API rejects non-loopback origins/hosts and doesn't offer data-changing endpoints. History and logs may contain local process names and should not be shared casually. This project is provided under the **[MIT License](LICENSE)**.

### Publishing (maintainer only)

This is a **temporary public source mirror branch** for Resource Watch, isolated from the unrelated VoiceType main branch. The dedicated public `MerluseDan/FACO-Resource-Watch` repository is not created yet. The installed software does not require GitHub CLI or a GitHub account.
