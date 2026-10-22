from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .audio import AudioRecorder
from .config import ConfigStore, MouseBinding, Settings
from .injector import inject_key, inject_text, session_type
from .input_monitor import ButtonLearner, MultiButtonMouseMonitor, same_button_binding
from .logging_setup import setup_logging
from .paths import ensure_runtime_dirs
from .transcriber import Transcriber
from .system_pulse import PulseGuard, collect as collect_pulse
from .ui import SettingsWindow, Tray, make_icon

log = logging.getLogger(__name__)


class Controller(QObject):
    hotkey_signal = Signal(str, int)
    monitor_status_signal = Signal(str)
    learned_signal = Signal(object, object)
    task_status_signal = Signal(str)
    task_done_signal = Signal(object)
    task_error_signal = Signal(str)
    model_test_done_signal = Signal(str)
    enter_done_signal = Signal(object)
    pulse_done_signal = Signal(object)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        ensure_runtime_dirs()
        self.store = ConfigStore()
        self.settings = self.store.load()
        self.window = SettingsWindow()
        self.window.setWindowIcon(make_icon("ready"))
        self.window.load_settings(self.settings)
        self.tray = Tray(self.window, self.set_paused, self.quit)
        self.recorder = AudioRecorder(self.settings.sample_rate)
        self.transcriber = Transcriber()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voicetype-worker")
        self.monitor: MultiButtonMouseMonitor | None = None
        self.learner = ButtonLearner(lambda item, err: self.learned_signal.emit(item, err))
        self.learning_target = "voice"
        self.paused = not self.settings.enabled
        self.pause_event = threading.Event()
        if self.paused:
            self.pause_event.set()
        self._busy = False
        self.pulse_guard = PulseGuard()
        self.pulse_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voicetype-pulse")
        self._pulse_busy = False
        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self.update_system_pulse)
        self.pulse_timer.start(2500)

        self.hotkey_signal.connect(self.on_hotkey)
        self.monitor_status_signal.connect(self._on_monitor_status)
        self.learned_signal.connect(self._on_learned)
        self.task_status_signal.connect(self.set_status)
        self.task_done_signal.connect(self._on_transcription_done)
        self.task_error_signal.connect(self._on_task_error)
        self.model_test_done_signal.connect(self._on_model_test_done)
        self.enter_done_signal.connect(self._on_enter_done)
        self.pulse_done_signal.connect(self._on_pulse_done)
        self.window.save_requested.connect(self.save_settings)
        self.window.learn_voice_requested.connect(self.begin_learning_voice)
        self.window.learn_enter_requested.connect(self.begin_learning_enter)
        self.window.pause_requested.connect(self.set_paused)
        self.window.test_model_requested.connect(self.test_model)

        self.set_paused(self.paused)
        self.restart_monitor()
        self.update_system_pulse()
        QTimer.singleShot(600, self._first_show)


    def update_system_pulse(self) -> None:
        if self._pulse_busy:
            return
        self._pulse_busy = True

        def work():
            try:
                self.pulse_done_signal.emit((collect_pulse(), None))
            except Exception as exc:
                self.pulse_done_signal.emit((None, str(exc)))

        self.pulse_executor.submit(work)

    @Slot(object)
    def _on_pulse_done(self, payload) -> None:
        self._pulse_busy = False
        snap, error = payload
        if error or snap is None:
            log.debug("System Pulse collection failed: %s", error)
            self.window.pulse_label.setText("System Pulse telemetry unavailable")
            return
        self.pulse_guard.evaluate(snap)
        self.window.pulse_label.setText(snap.compact())
        self.window.pulse_label.setToolTip(snap.details())


    def _first_show(self):
        if not self.settings.start_minimized or self.settings.mouse.button_code is None:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def notify(self, title: str, msg: str) -> None:
        if self.settings.show_notifications:
            self.tray.notify(title, msg)

    def set_status(self, msg: str, state: str | None = None) -> None:
        self.window.status_label.setText(msg)
        if state:
            self.tray.state(state, f"FACO VoiceType • {msg}")
        log.info("Status: %s", msg)

    def restart_monitor(self) -> None:
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
        bindings = {}
        suppress = {}
        if self.settings.mouse.button_code is not None:
            bindings["voice"] = self.settings.mouse
            suppress["voice"] = self.settings.suppress_original_button
        if self.settings.enter_mouse.button_code is not None:
            bindings["enter"] = self.settings.enter_mouse
            suppress["enter"] = self.settings.suppress_enter_button
        if not bindings:
            self.set_status("Map a mouse button to activate dictation.", "paused")
            return
        self.monitor = MultiButtonMouseMonitor(
            bindings,
            lambda action, value: self.hotkey_signal.emit(action, value),
            lambda msg: self.monitor_status_signal.emit(msg),
            suppress_actions=suppress,
            paused_callback=lambda: self.paused,
        )
        self.monitor.start()

    @Slot(str)
    def _on_monitor_status(self, msg: str):
        if not self._busy and not self.paused:
            self.set_status(msg, "ready")

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        if self.paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()
        self.settings.enabled = not self.paused
        try:
            self.store.save(self.settings)
        except Exception:
            log.exception("Could not persist pause state")
        self.window.set_paused(self.paused)
        self.tray.set_paused(self.paused)
        if self.paused:
            try:
                if self.recorder.recording:
                    self.recorder.stop()
            except Exception:
                log.exception("Could not stop recorder while pausing")
            unloaded = self.transcriber.unload(wait=False)
            if unloaded:
                self.set_status("Paused; Whisper model unloaded and mapped mouse actions pass through normally.", "paused")
            else:
                self.set_status("Paused; current transcription will finish, then Whisper will unload.", "paused")
        else:
            self.set_status("Ready", "ready")

    @Slot(str, int)
    def on_hotkey(self, action: str, value: int) -> None:
        if self.paused:
            return
        if action == "enter":
            if value == 1 and not self._busy and not self.recorder.recording:
                self.send_enter()
            return
        if action != "voice" or self._busy:
            return
        try:
            if self.settings.trigger_mode == "hold":
                if value == 1 and not self.recorder.recording:
                    self.start_recording()
                elif value == 0 and self.recorder.recording:
                    self.stop_and_transcribe()
            elif self.settings.trigger_mode == "toggle" and value == 1:
                if self.recorder.recording:
                    self.stop_and_transcribe()
                else:
                    self.start_recording()
        except Exception as exc:
            log.exception("Hotkey handling failed")
            self._on_task_error(str(exc))

    def send_enter(self) -> None:
        self.set_status("Sending Enter…", "busy")

        def work():
            result = inject_key("enter")
            self.enter_done_signal.emit(result)

        self.executor.submit(work)

    @Slot(object)
    def _on_enter_done(self, result) -> None:
        if result and result.ok:
            self.set_status(f"Ready • Enter sent via {result.method}", "ready")
        else:
            message = result.message if result else "No key injector result"
            self.set_status(f"Enter failed: {message}", "error")
            self.notify("FACO VoiceType", f"Could not send Enter: {message}")

    def start_recording(self) -> None:
        self.recorder.start(self.settings.microphone_name)
        self.set_status("Listening… release/press again when finished", "recording")

    def stop_and_transcribe(self) -> None:
        audio = self.recorder.stop()
        if audio.size < int(self.settings.sample_rate * 0.12):
            self.set_status("Recording was too short; ignored.", "ready")
            return
        self._busy = True
        self.set_status("Transcribing…", "busy")
        settings = self.settings

        def work():
            try:
                text, spec = self.transcriber.transcribe(
                    audio,
                    model=settings.model,
                    device=settings.inference_device,
                    compute_type=settings.compute_type,
                    language=settings.language,
                    beam_size=settings.beam_size,
                    vad_filter=settings.vad_filter,
                    progress=lambda msg: self.task_status_signal.emit(msg),
                    expressive_punctuation=settings.expressive_punctuation,
                    expression_level=settings.expression_level,
                    sample_rate=settings.sample_rate,
                )
                if text and settings.append_space:
                    text += " "
                result = None
                if text and not self.pause_event.is_set():
                    result = inject_text(
                        text,
                        preserve_clipboard=settings.preserve_clipboard_text,
                        restore_delay_ms=settings.clipboard_restore_delay_ms,
                    )
                self.task_done_signal.emit((text, spec, result))
            except Exception as exc:
                log.exception("Transcription task failed")
                self.task_error_signal.emit(str(exc))

        self.executor.submit(work)

    @Slot(object)
    def _on_transcription_done(self, payload) -> None:
        self._busy = False
        text, spec, result = payload
        if self.paused:
            self.transcriber.unload(wait=False)
            self.set_status("Paused; Whisper model unloaded.", "paused")
            return
        if not text:
            self.set_status("No speech detected.", "ready")
            return
        if result and result.ok:
            self.set_status(f"Ready • {spec.device}/{spec.compute_type} • pasted {len(text.strip())} chars", "ready")
        else:
            message = result.message if result else "No injector result"
            self.set_status(f"Transcribed, but paste failed: {message}", "error")
            self.notify("FACO VoiceType", f"Transcribed but could not paste: {message}")

    @Slot(str)
    def _on_task_error(self, message: str) -> None:
        self._busy = False
        if self.paused:
            self.transcriber.unload(wait=False)
            self.set_status(f"Paused after error: {message}", "paused")
        else:
            self.set_status(f"Error: {message}", "error")
            self.notify("FACO VoiceType error", message)

    @Slot(dict)
    def save_settings(self, values: dict) -> None:
        if self._busy or self.recorder.recording:
            self.set_status("Finish the current dictation before changing settings.", "busy")
            return
        current_enabled = self.settings.enabled
        new = Settings.from_dict({
            **self.settings.__dict__,
            **values,
            "mouse": values.get("mouse", self.settings.mouse.__dict__),
            "enter_mouse": values.get("enter_mouse", self.settings.enter_mouse.__dict__),
        })
        if same_button_binding(new.mouse, new.enter_mouse):
            self.set_status("Voice and Enter cannot use the exact same mouse button. Map a different Enter button.", "error")
            self.notify("FACO VoiceType", "Voice and Enter need different mouse buttons.")
            return
        new.enabled = current_enabled
        self.settings = new
        self.recorder.sample_rate = self.settings.sample_rate
        self.store.save(self.settings)
        self.window.load_settings(self.settings)
        self.transcriber.unload()
        self.restart_monitor()
        self.set_status("Settings saved. Ready.", "ready" if not self.paused else "paused")
        self.notify("FACO VoiceType", "Settings saved")

    @Slot()
    def begin_learning_voice(self) -> None:
        self.begin_learning("voice")

    @Slot()
    def begin_learning_enter(self) -> None:
        self.begin_learning("enter")

    def begin_learning(self, target: str = "voice") -> None:
        if self._busy or self.recorder.recording:
            self.set_status("Finish the current dictation before remapping a mouse button.", "busy")
            return
        self.learning_target = "enter" if target == "enter" else "voice"
        if self.monitor:
            self.monitor.stop()
        self.window.set_learning(True, self.learning_target)
        label = "Enter/submit" if self.learning_target == "enter" else "voice"
        self.set_status(f"Press the mouse button for {label}. You have 15 seconds.", "busy")
        self.learner.start(15.0)

    @Slot(object, object)
    def _on_learned(self, item, error) -> None:
        target = self.learning_target
        self.window.set_learning(False, target)
        if error:
            self.set_status(f"Button mapping failed: {error}", "error")
            self.restart_monitor()
            return
        self.window.set_learned_binding(item, target)
        label = "Enter/submit" if target == "enter" else "voice"
        self.set_status(f"Captured {item['button_name']} on {item['name']} for {label}. Click Save settings.", "ready")

    @Slot()
    def test_model(self) -> None:
        if self._busy:
            return
        self._busy = True
        model = self.window.model_combo.currentData()
        device = self.window.device_combo.currentData()
        compute = self.window.compute_combo.currentData()
        self.set_status("Loading selected Whisper model…", "busy")

        def work():
            try:
                spec = self.transcriber.preload(model, device, compute, progress=lambda msg: self.task_status_signal.emit(msg))
                self.model_test_done_signal.emit(f"Whisper ready: {spec.model} on {spec.device} ({spec.compute_type})")
            except Exception as exc:
                log.exception("Whisper preload failed")
                self.task_error_signal.emit(str(exc))

        self.executor.submit(work)

    @Slot(str)
    def _on_model_test_done(self, message: str) -> None:
        self._busy = False
        self.set_status(message, "ready")
        self.notify("FACO VoiceType", message)

    def quit(self) -> None:
        log.info("Shutdown requested")
        self.learner.stop()
        if self.monitor:
            self.monitor.stop()
        try:
            if self.recorder.recording:
                self.recorder.stop()
        except Exception:
            pass
        self.transcriber.unload()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.pulse_executor.shutdown(wait=False, cancel_futures=True)
        self.app.quit()


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("FACO VoiceType")
    app.setQuitOnLastWindowClosed(False)

    # Single-instance IPC: launching VoiceType again opens the existing settings window.
    server_name = f"faco-voicetype-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(250):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(250)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer(app)
    if not server.listen(server_name):
        log.warning("Could not create single-instance socket: %s", server.errorString())

    controller = Controller(app)

    def handle_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        if sock.waitForReadyRead(250):
            command = bytes(sock.readAll()).decode("utf-8", "replace").strip()
            if command == "show":
                controller.window.show()
                controller.window.raise_()
                controller.window.activateWindow()
        sock.disconnectFromServer()

    server.newConnection.connect(handle_connection)
    signal.signal(signal.SIGINT, lambda *_: controller.quit())
    signal.signal(signal.SIGTERM, lambda *_: controller.quit())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    log.info("FACO VoiceType started session=%s", session_type())
    return app.exec()
