from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class InjectionResult:
    ok: bool
    method: str
    message: str = ""


def session_type() -> str:
    value = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if value in {"wayland", "x11"}:
        return value
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _run(cmd: list[str], *, input_bytes: bytes | None = None, timeout: float = 4.0, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False, env=env)


def _ydotool_env() -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("YDOTOOL_SOCKET"):
        candidates = [f"/run/user/{os.getuid()}/.ydotool_socket", "/tmp/.ydotool_socket"]
        for candidate in candidates:
            if os.path.exists(candidate):
                env["YDOTOOL_SOCKET"] = candidate
                break
    return env




def _ydotool_is_legacy_symbolic() -> bool:
    """Ubuntu 24.04 ships ydotool 0.1.x, whose key syntax is symbolic.

    ydotool 1.x switched to raw Linux keycodes. Prefer package metadata when
    available so we never send numeric tokens to 0.1.x, which can type garbage
    while still exiting successfully.
    """
    if shutil.which("dpkg-query"):
        try:
            proc = _run(["dpkg-query", "-W", "-f=${Version}", "ydotool"], timeout=2.0)
            if proc.returncode == 0:
                version = proc.stdout.decode("utf-8", "replace").strip().split("-")[0]
                if version.startswith("0.1.") or version == "0.1":
                    return True
                if version and version[0].isdigit():
                    return False
        except Exception:
            pass
    # Ubuntu Noble is the primary target and 0.1.8 is common there. If package
    # metadata is unavailable, prefer symbolic for paste because the installed
    # VoiceType path has already validated it on Noble. Dedicated Enter falls
    # back to xdotool on X11 before ydotool is needed.
    return True


def _ydotool_key(symbolic: str, raw_codes: list[str]) -> tuple[bool, str]:
    if not shutil.which("ydotool"):
        return False, "ydotool is not installed"
    env = _ydotool_env()
    args = ["ydotool", "key", symbolic] if _ydotool_is_legacy_symbolic() else ["ydotool", "key", *raw_codes]
    proc = _run(args, env=env)
    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"


def _ydotool_paste() -> tuple[bool, str]:
    return _ydotool_key("ctrl+v", ["29:1", "47:1", "47:0", "29:0"])


def _xclip_set(payload: bytes) -> tuple[bool, str]:
    """Take ownership of the X11 clipboard without waiting for xclip to exit.

    xclip is an X selection owner. In input mode it is *supposed* to stay alive
    until another process takes the clipboard. Waiting on it with
    subprocess.run/communicate therefore deadlocks or times out on a healthy
    X11 desktop. Feed stdin, detach stdio, and let the selection owner live.
    """
    if not shutil.which("xclip"):
        return False, "xclip is not installed"
    try:
        proc = subprocess.Popen(
            ["xclip", "-selection", "clipboard", "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if proc.stdin is None:
            return False, "xclip stdin was unavailable"
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        finally:
            proc.stdin.close()
        # Give xclip a moment to acquire the X selection. It may fork and the
        # parent may exit 0, or it may remain the owner itself. Both are valid.
        time.sleep(0.045)
        rc = proc.poll()
        if rc not in (None, 0):
            return False, f"xclip exited with code {rc}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _x11_paste() -> tuple[bool, str, str]:
    if shutil.which("xdotool"):
        pasted = _run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        if pasted.returncode == 0:
            return True, "xdotool", ""
        xdotool_err = pasted.stderr.decode("utf-8", "replace").strip() or f"exit {pasted.returncode}"
        log.warning("xdotool paste failed; trying ydotool fallback: %s", xdotool_err)
    else:
        xdotool_err = "xdotool is not installed"

    ok, err = _ydotool_paste()
    if ok:
        return True, "ydotool", ""
    return False, "x11", f"xdotool: {xdotool_err}; ydotool: {err}"


def inject_text(text: str, preserve_clipboard: bool = True, restore_delay_ms: int = 650) -> InjectionResult:
    if not text:
        return InjectionResult(False, "none", "No text to inject")
    session = session_type()
    old: bytes | None = None
    try:
        if session == "wayland":
            if not shutil.which("wl-copy"):
                return InjectionResult(False, "wayland", "wl-copy is missing")
            if preserve_clipboard and shutil.which("wl-paste"):
                previous = _run(["wl-paste", "--no-newline"], timeout=2.0)
                if previous.returncode == 0:
                    old = previous.stdout
            copied = _run(["wl-copy", "--type", "text/plain;charset=utf-8"], input_bytes=text.encode("utf-8"))
            if copied.returncode != 0:
                return InjectionResult(False, "wl-copy", copied.stderr.decode("utf-8", "replace").strip())
            ok, err = _ydotool_paste()
            if not ok:
                return InjectionResult(False, "ydotool", err)
            method = "wl-copy + ydotool"
        else:
            if not shutil.which("xclip"):
                return InjectionResult(False, "x11", "xclip is missing")
            if preserve_clipboard:
                previous = _run(["xclip", "-selection", "clipboard", "-o"], timeout=2.0)
                if previous.returncode == 0:
                    old = previous.stdout
            copied, copy_err = _xclip_set(text.encode("utf-8"))
            if not copied:
                return InjectionResult(False, "xclip", copy_err)
            ok, paste_backend, paste_err = _x11_paste()
            if not ok:
                return InjectionResult(False, paste_backend, paste_err)
            method = f"xclip + {paste_backend}"

        if old is not None:
            time.sleep(max(0.1, restore_delay_ms / 1000.0))
            if session == "wayland":
                restored = _run(["wl-copy"], input_bytes=old)
                if restored.returncode != 0:
                    log.warning("Could not restore Wayland clipboard: %s", restored.stderr.decode("utf-8", "replace").strip())
            else:
                restored, restore_err = _xclip_set(old)
                if not restored:
                    log.warning("Could not restore X11 clipboard: %s", restore_err)

        log.info("Injected %s chars via %s", len(text), method)
        return InjectionResult(True, method)
    except subprocess.TimeoutExpired as exc:
        return InjectionResult(False, "timeout", str(exc))
    except Exception as exc:
        log.exception("Text injection failed")
        return InjectionResult(False, "exception", str(exc))


def inject_key(key: str) -> InjectionResult:
    """Inject a real keyboard key into the focused application.

    Enter is intentionally a key event rather than a pasted newline so it can
    submit chat boxes/forms exactly like the physical keyboard Enter key.
    """
    normalized = key.strip().lower()
    if normalized not in {"enter", "return"}:
        return InjectionResult(False, "key", f"Unsupported key: {key}")
    session = session_type()
    try:
        if session != "wayland" and shutil.which("xdotool"):
            proc = _run(["xdotool", "key", "--clearmodifiers", "Return"])
            if proc.returncode == 0:
                log.info("Injected Enter via xdotool")
                return InjectionResult(True, "xdotool")
            err = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            log.warning("xdotool Enter failed; trying ydotool: %s", err)
        ok, err = _ydotool_key("enter", ["28:1", "28:0"])
        if ok:
            log.info("Injected Enter via ydotool")
            return InjectionResult(True, "ydotool")
        return InjectionResult(False, "ydotool", err)
    except subprocess.TimeoutExpired as exc:
        return InjectionResult(False, "timeout", str(exc))
    except Exception as exc:
        log.exception("Key injection failed")
        return InjectionResult(False, "exception", str(exc))
