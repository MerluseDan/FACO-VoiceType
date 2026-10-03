from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

fake = types.ModuleType("evdev")
class E:
    BTN_MISC=0x100; BTN_MOUSE=0x110; BTN_TASK=0x117; EV_KEY=1; EV_REL=2
    BTN={0x116:"BTN_BACK",0x117:"BTN_TASK"}; KEY={}
fake.ecodes=E
fake.InputDevice=object
fake.UInput=object
fake.list_devices=lambda: []
sys.modules["evdev"] = fake

from faco_voicetype.config import MouseBinding
from faco_voicetype.input_monitor import binding_matches, code_name

class Info:
    vendor=123
    product=456
class Dev:
    path="/dev/input/event9"
    name="Test Mouse"
    phys="usb-1"
    uniq="abc"
    info=Info()

def test_binding_by_uniq():
    b=MouseBinding(uniq="abc", button_code=0x116)
    assert binding_matches(Dev(), b)
    assert code_name(0x116) == "BTN_BACK"


def test_monitor_stop_releases_grab_without_mouse_event(monkeypatch):
    import time
    import faco_voicetype.input_monitor as im

    state = {"grab": 0, "ungrab": 0, "closed": 0, "ui_closed": 0}
    class FakeDevice:
        fd = 42
        name = "Idle Test Mouse"
        path = "/dev/input/event42"
        def grab(self): state["grab"] += 1
        def ungrab(self): state["ungrab"] += 1
        def close(self): state["closed"] += 1
        def read(self): return []

    class FakeUIObj:
        def write_event(self, _event): pass
        def close(self): state["ui_closed"] += 1
    class FakeUI:
        @staticmethod
        def from_device(_dev, name=None):
            return FakeUIObj()

    dev = FakeDevice()
    monkeypatch.setattr(im, "find_bound_device", lambda _binding: dev)
    monkeypatch.setattr(im, "UInput", FakeUI)
    def idle_select(_r, _w, _x, timeout):
        time.sleep(min(timeout, 0.01))
        return [], [], []
    monkeypatch.setattr(im.select, "select", idle_select)

    monitor = im.MouseMonitor(MouseBinding(button_code=0x116), lambda _v: None, suppress_original=True)
    monitor.start()
    time.sleep(0.04)
    monitor.stop()
    assert state["grab"] == 1
    assert state["ungrab"] == 1
    assert state["closed"] >= 1
    assert state["ui_closed"] == 1
