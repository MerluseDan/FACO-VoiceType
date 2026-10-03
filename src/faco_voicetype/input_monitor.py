from __future__ import annotations

import logging
import select
import threading
import time
from dataclasses import asdict
from typing import Callable

from evdev import InputDevice, UInput, ecodes, list_devices

from .config import MouseBinding

log = logging.getLogger(__name__)
VIRTUAL_PREFIX = "FACO VoiceType Virtual"
MOUSE_BUTTON_MIN = ecodes.BTN_MISC
MOUSE_BUTTON_MAX = ecodes.BTN_TASK


def code_name(code: int) -> str:
    value = ecodes.BTN.get(code) or ecodes.KEY.get(code)
    if isinstance(value, list):
        return "/".join(value)
    return str(value or f"CODE_{code}")


def device_descriptor(dev: InputDevice) -> dict:
    return {
        "path": dev.path,
        "name": dev.name or "",
        "phys": dev.phys or "",
        "uniq": dev.uniq or "",
        "vendor": int(dev.info.vendor),
        "product": int(dev.info.product),
    }


def is_mouse_like(dev: InputDevice) -> bool:
    name = (dev.name or "").lower()
    if name.startswith(VIRTUAL_PREFIX.lower()) or "ydotoold virtual" in name or "keyd virtual" in name or "input-remapper" in name:
        return False
    try:
        caps = dev.capabilities(absinfo=False)
    except OSError:
        return False
    keys = set(caps.get(ecodes.EV_KEY, []))
    has_button = any(MOUSE_BUTTON_MIN <= int(code) <= MOUSE_BUTTON_MAX for code in keys)
    has_motion = ecodes.EV_REL in caps
    return has_button or has_motion


def list_mouse_devices() -> list[dict]:
    result: list[dict] = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            if is_mouse_like(dev):
                item = device_descriptor(dev)
                item["display"] = f"{item['name']}  [{item['path']}]"
                result.append(item)
            dev.close()
        except (PermissionError, OSError):
            continue
    return result


def binding_matches(dev: InputDevice, binding: MouseBinding) -> bool:
    if not binding.button_code:
        return False
    if binding.uniq and dev.uniq and binding.uniq == dev.uniq:
        return True
    if binding.phys and dev.phys and binding.phys == dev.phys and binding.name == (dev.name or ""):
        return True
    if binding.vendor and binding.product and binding.vendor == dev.info.vendor and binding.product == dev.info.product and binding.name == (dev.name or ""):
        return True
    return bool(binding.path and binding.path == dev.path)


def find_bound_device(binding: MouseBinding) -> InputDevice | None:
    for path in list_devices():
        try:
            dev = InputDevice(path)
            if is_mouse_like(dev) and binding_matches(dev, binding):
                return dev
            dev.close()
        except (PermissionError, OSError):
            continue
    return None


class ButtonLearner:
    def __init__(self, callback: Callable[[dict | None, str | None], None]):
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 15.0) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(timeout,), daemon=True, name="button-learner")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self, timeout: float) -> None:
        devices: list[InputDevice] = []
        try:
            for path in list_devices():
                try:
                    dev = InputDevice(path)
                    if is_mouse_like(dev):
                        devices.append(dev)
                    else:
                        dev.close()
                except PermissionError:
                    continue
            if not devices:
                self.callback(None, "No readable mouse devices. Re-run install.sh to repair input permissions.")
                return
            deadline = time.monotonic() + timeout
            fdmap = {d.fd: d for d in devices}
            while not self._stop.is_set() and time.monotonic() < deadline:
                ready, _, _ = select.select(list(fdmap), [], [], 0.25)
                for fd in ready:
                    dev = fdmap[fd]
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.value == 1 and MOUSE_BUTTON_MIN <= event.code <= MOUSE_BUTTON_MAX:
                            item = device_descriptor(dev)
                            item["button_code"] = int(event.code)
                            item["button_name"] = code_name(event.code)
                            self.callback(item, None)
                            return
            if not self._stop.is_set():
                self.callback(None, "Timed out waiting for a mouse button.")
        except Exception as exc:
            log.exception("Button learn failed")
            self.callback(None, str(exc))
        finally:
            for dev in devices:
                try:
                    dev.close()
                except Exception:
                    pass


class MouseMonitor:
    def __init__(
        self,
        binding: MouseBinding,
        event_callback: Callable[[int], None],
        status_callback: Callable[[str], None] | None = None,
        suppress_original: bool = False,
        paused_callback: Callable[[], bool] | None = None,
    ):
        self.binding = binding
        self.event_callback = event_callback
        self.status_callback = status_callback or (lambda _msg: None)
        self.suppress_original = suppress_original
        self.paused_callback = paused_callback or (lambda: False)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mouse-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            dev: InputDevice | None = None
            ui: UInput | None = None
            grabbed = False
            try:
                dev = find_bound_device(self.binding)
                if dev is None:
                    self.status_callback("Mapped mouse not available")
                    self._stop.wait(2.0)
                    continue
                self.status_callback(f"Listening: {dev.name}")
                if self.suppress_original:
                    try:
                        ui = UInput.from_device(dev, name=f"{VIRTUAL_PREFIX} {dev.name}")
                        dev.grab()
                        grabbed = True
                        log.info("Mouse grabbed for mapped-button suppression: %s", dev.path)
                    except Exception:
                        log.exception("Could not enable button suppression; continuing without suppression")
                        if ui:
                            ui.close()
                        ui = None
                # Do not use evdev.read_loop() here: it can block forever while idle,
                # preventing stop() from releasing EVIOCGRAB before a settings restart.
                # A short select timeout makes shutdown deterministic and avoids the
                # "Device or resource busy" race seen in the v1.0.0 field logs.
                while not self._stop.is_set():
                    ready, _, _ = select.select([dev.fd], [], [], 0.20)
                    if not ready:
                        continue
                    for event in dev.read():
                        mapped = event.type == ecodes.EV_KEY and event.code == self.binding.button_code
                        if mapped and event.value in (0, 1):
                            self.event_callback(int(event.value))
                        should_swallow = bool(mapped and ui is not None and not self.paused_callback())
                        if ui is not None and not should_swallow:
                            ui.write_event(event)
            except (OSError, PermissionError) as exc:
                log.warning("Mouse monitor reconnecting after error: %s", exc)
                self.status_callback(f"Mouse reconnecting: {exc}")
                self._stop.wait(1.0)
            except Exception:
                log.exception("Mouse monitor failure")
                self._stop.wait(1.0)
            finally:
                if dev is not None:
                    if grabbed:
                        try:
                            dev.ungrab()
                        except Exception:
                            pass
                    try:
                        dev.close()
                    except Exception:
                        pass
                if ui is not None:
                    try:
                        ui.close()
                    except Exception:
                        pass


def same_button_binding(left: MouseBinding, right: MouseBinding) -> bool:
    if left.button_code is None or right.button_code is None or left.button_code != right.button_code:
        return False
    if left.uniq and right.uniq:
        return left.uniq == right.uniq
    if left.phys and right.phys:
        return left.phys == right.phys and left.name == right.name
    if left.vendor and left.product and right.vendor and right.product:
        return (left.vendor, left.product, left.name) == (right.vendor, right.product, right.name)
    return bool(left.path and right.path and left.path == right.path)


class MultiButtonMouseMonitor:
    """Listen for multiple actions, including two buttons on the same mouse.

    A single evdev grab/uinput clone is used per physical device, avoiding the
    EVIOCGRAB collision that two independent listeners would cause.
    """
    def __init__(
        self,
        bindings: dict[str, MouseBinding],
        event_callback: Callable[[str, int], None],
        status_callback: Callable[[str], None] | None = None,
        suppress_actions: dict[str, bool] | None = None,
        paused_callback: Callable[[], bool] | None = None,
    ):
        self.bindings = {k: v for k, v in bindings.items() if v.button_code is not None}
        self.event_callback = event_callback
        self.status_callback = status_callback or (lambda _msg: None)
        self.suppress_actions = dict(suppress_actions or {})
        self.paused_callback = paused_callback or (lambda: False)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="multi-mouse-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.8)
        self._thread = None

    def _open_groups(self) -> tuple[dict[int, dict], list[str]]:
        groups_by_path: dict[str, dict] = {}
        missing: list[str] = []
        for action, binding in self.bindings.items():
            dev = find_bound_device(binding)
            if dev is None:
                missing.append(action)
                continue
            path = dev.path
            if path not in groups_by_path:
                groups_by_path[path] = {"dev": dev, "actions": {}}
            else:
                try:
                    dev.close()
                except Exception:
                    pass
            groups_by_path[path]["actions"].setdefault(int(binding.button_code), []).append(action)
        return {group["dev"].fd: group for group in groups_by_path.values()}, missing

    def _run(self) -> None:
        while not self._stop.is_set():
            groups: dict[int, dict] = {}
            try:
                groups, missing = self._open_groups()
                if not groups:
                    self.status_callback("Mapped mouse buttons not available")
                    self._stop.wait(2.0)
                    continue
                if missing:
                    self.status_callback("Waiting for mapped action(s): " + ", ".join(sorted(missing)))
                else:
                    names = sorted({group["dev"].name for group in groups.values()})
                    self.status_callback("Listening: " + ", ".join(names))

                for group in groups.values():
                    group["ui"] = None
                    group["grabbed"] = False
                    actions_on_device = {a for values in group["actions"].values() for a in values}
                    needs_suppression = any(self.suppress_actions.get(a, False) for a in actions_on_device)
                    if not needs_suppression:
                        continue
                    try:
                        group["ui"] = UInput.from_device(group["dev"], name=f"{VIRTUAL_PREFIX} {group['dev'].name}")
                        group["dev"].grab()
                        group["grabbed"] = True
                        log.info("Mouse grabbed for multi-button suppression: %s", group["dev"].path)
                    except Exception:
                        log.exception("Could not enable multi-button suppression; continuing without suppression")
                        if group.get("ui"):
                            try:
                                group["ui"].close()
                            except Exception:
                                pass
                        group["ui"] = None

                while not self._stop.is_set():
                    ready, _, _ = select.select(list(groups), [], [], 0.20)
                    for fd in ready:
                        group = groups.get(fd)
                        if group is None:
                            continue
                        dev = group["dev"]
                        for event in dev.read():
                            actions = []
                            if event.type == ecodes.EV_KEY:
                                actions = list(group["actions"].get(int(event.code), []))
                            if actions and event.value in (0, 1):
                                for action in actions:
                                    self.event_callback(action, int(event.value))
                            ui = group.get("ui")
                            should_swallow = bool(
                                actions
                                and ui is not None
                                and not self.paused_callback()
                                and any(self.suppress_actions.get(a, False) for a in actions)
                            )
                            if ui is not None and not should_swallow:
                                ui.write_event(event)
            except (OSError, PermissionError) as exc:
                log.warning("Multi-button mouse monitor reconnecting after error: %s", exc)
                self.status_callback(f"Mouse reconnecting: {exc}")
                self._stop.wait(1.0)
            except Exception:
                log.exception("Multi-button mouse monitor failure")
                self._stop.wait(1.0)
            finally:
                for group in groups.values():
                    dev = group.get("dev")
                    ui = group.get("ui")
                    if dev is not None:
                        if group.get("grabbed"):
                            try:
                                dev.ungrab()
                            except Exception:
                                pass
                        try:
                            dev.close()
                        except Exception:
                            pass
                    if ui is not None:
                        try:
                            ui.close()
                        except Exception:
                            pass
