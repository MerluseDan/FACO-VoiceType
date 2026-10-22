from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .audio import list_input_devices
from .resources import discover_local_whisper_models


def make_icon(state: str = "ready") -> QIcon:
    colors = {
        "ready": QColor("#2f80ed"),
        "recording": QColor("#e53935"),
        "busy": QColor("#8e44ad"),
        "paused": QColor("#7f8c8d"),
        "error": QColor("#c0392b"),
    }
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colors.get(state, colors["ready"]))
    p.drawRoundedRect(21, 7, 22, 34, 11, 11)
    pen = QPen(colors.get(state, colors["ready"]), 5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(13, 22, 38, 28, 180 * 16, 180 * 16)
    p.drawLine(32, 49, 32, 57)
    p.drawLine(23, 57, 41, 57)
    p.end()
    return QIcon(pix)


class SettingsWindow(QMainWindow):
    save_requested = Signal(dict)
    learn_voice_requested = Signal()
    learn_enter_requested = Signal()
    test_model_requested = Signal()
    pause_requested = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FACO VoiceType")
        self.setMinimumSize(680, 670)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        intro = QLabel("Map one mouse button for dictation and an optional second button for Enter/Submit. VoiceType pastes speech into the focused text field and can send a real Return key without touching the keyboard.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        bind_group = QGroupBox("Mouse trigger")
        bind_form = QFormLayout(bind_group)
        self.binding_label = QLabel("Not configured")
        self.learn_button = QPushButton("Map voice button…")
        self.learn_button.clicked.connect(self.learn_voice_requested.emit)
        row = QHBoxLayout()
        row.addWidget(self.binding_label, 1)
        row.addWidget(self.learn_button)
        bind_form.addRow("Voice button", row)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Hold to talk", "hold")
        self.mode_combo.addItem("Press once to start / again to stop", "toggle")
        bind_form.addRow("Trigger mode", self.mode_combo)
        self.suppress_check = QCheckBox("Suppress the voice button's normal mouse action while VoiceType is active")
        bind_form.addRow("", self.suppress_check)

        self.enter_binding_label = QLabel("Not configured")
        self.enter_learn_button = QPushButton("Map Enter button…")
        self.enter_learn_button.clicked.connect(self.learn_enter_requested.emit)
        enter_row = QHBoxLayout()
        enter_row.addWidget(self.enter_binding_label, 1)
        enter_row.addWidget(self.enter_learn_button)
        bind_form.addRow("Enter / submit button", enter_row)
        self.enter_suppress_check = QCheckBox("Suppress the Enter button's normal mouse action while VoiceType is active")
        bind_form.addRow("", self.enter_suppress_check)
        layout.addWidget(bind_group)

        speech_group = QGroupBox("Speech recognition")
        speech_form = QFormLayout(speech_group)
        self.mic_combo = QComboBox()
        self.refresh_mics()
        speech_form.addRow("Microphone", self.mic_combo)
        self.model_combo = QComboBox()
        for name in ("tiny", "base", "small", "medium", "distil-large-v3", "large-v3"):
            self.model_combo.addItem(name, name)
        for label, path in discover_local_whisper_models():
            self.model_combo.addItem(f"Local: {label}", path)
        speech_form.addRow("Whisper model", self.model_combo)
        self.language_combo = QComboBox()
        for label, code in (("Auto detect", "auto"), ("English", "en"), ("French", "fr"), ("Spanish", "es"), ("German", "de"), ("Italian", "it"), ("Portuguese", "pt")):
            self.language_combo.addItem(label, code)
        speech_form.addRow("Language", self.language_combo)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Auto (GPU when available)", "auto")
        self.device_combo.addItem("NVIDIA CUDA", "cuda")
        self.device_combo.addItem("CPU", "cpu")
        speech_form.addRow("Inference", self.device_combo)
        self.compute_combo = QComboBox()
        for label, value in (("Auto", "auto"), ("float16", "float16"), ("int8_float16", "int8_float16"), ("int8", "int8")):
            self.compute_combo.addItem(label, value)
        speech_form.addRow("Compute type", self.compute_combo)
        self.test_model_button = QPushButton("Preload / test selected model")
        self.test_model_button.clicked.connect(self.test_model_requested.emit)
        speech_form.addRow("", self.test_model_button)
        layout.addWidget(speech_group)

        behavior_group = QGroupBox("Behavior")
        behavior_form = QFormLayout(behavior_group)
        self.append_space_check = QCheckBox("Add a trailing space after each dictation")
        behavior_form.addRow("", self.append_space_check)
        self.expressive_check = QCheckBox("Expressive punctuation from pauses, pitch and emphasis")
        self.expressive_check.setToolTip("Uses the recorded waveform plus Whisper word timing to improve commas, questions, exclamation marks and sentence breaks.")
        behavior_form.addRow("", self.expressive_check)
        self.expression_level_combo = QComboBox()
        self.expression_level_combo.addItem("Conservative", "conservative")
        self.expression_level_combo.addItem("Balanced", "balanced")
        self.expression_level_combo.addItem("Expressive", "expressive")
        behavior_form.addRow("Expression sensitivity", self.expression_level_combo)
        self.preserve_clipboard_check = QCheckBox("Restore previous text clipboard after paste")
        behavior_form.addRow("", self.preserve_clipboard_check)
        self.restore_delay = QSpinBox()
        self.restore_delay.setRange(100, 5000)
        self.restore_delay.setSuffix(" ms")
        behavior_form.addRow("Clipboard restore delay", self.restore_delay)
        self.notifications_check = QCheckBox("Show tray notifications")
        behavior_form.addRow("", self.notifications_check)
        self.start_minimized_check = QCheckBox("Start hidden in tray")
        behavior_form.addRow("", self.start_minimized_check)
        layout.addWidget(behavior_group)

        pulse_group = QGroupBox("System Pulse")
        pulse_layout = QVBoxLayout(pulse_group)
        self.pulse_label = QLabel("Collecting CPU / RAM / GPU / audio status…")
        self.pulse_label.setWordWrap(True)
        pulse_layout.addWidget(self.pulse_label)
        layout.addWidget(pulse_group)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.pause_button = QPushButton("Pause & unload model")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self.pause_requested.emit)
        self.save_button = QPushButton("Save settings")
        self.save_button.clicked.connect(self._emit_save)
        actions.addWidget(self.pause_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

        self._mouse_dict = {}
        self._enter_mouse_dict = {}

    def refresh_mics(self) -> None:
        current = self.mic_combo.currentData() if self.mic_combo.count() else ""
        self.mic_combo.clear()
        self.mic_combo.addItem("System default", "")
        for dev in list_input_devices():
            self.mic_combo.addItem(dev.name, dev.name)
        idx = self.mic_combo.findData(current)
        if idx >= 0:
            self.mic_combo.setCurrentIndex(idx)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def load_settings(self, settings) -> None:
        self._mouse_dict = settings.mouse.__dict__.copy()
        self.binding_label.setText(settings.mouse.button_name or "Not configured")
        if settings.mouse.name:
            self.binding_label.setToolTip(f"{settings.mouse.name} • {settings.mouse.path}")
        self.learn_button.setText("Remap voice button…" if settings.mouse.button_code is not None else "Map voice button…")
        self._enter_mouse_dict = settings.enter_mouse.__dict__.copy()
        self.enter_binding_label.setText(settings.enter_mouse.button_name or "Not configured")
        if settings.enter_mouse.name:
            self.enter_binding_label.setToolTip(f"{settings.enter_mouse.name} • {settings.enter_mouse.path}")
        self.enter_learn_button.setText("Remap Enter button…" if settings.enter_mouse.button_code is not None else "Map Enter button…")
        self._set_combo(self.mode_combo, settings.trigger_mode)
        self.suppress_check.setChecked(settings.suppress_original_button)
        self.enter_suppress_check.setChecked(getattr(settings, "suppress_enter_button", True))
        self._set_combo(self.mic_combo, settings.microphone_name)
        # Add a configured local path if it disappeared from discovery.
        if self.model_combo.findData(settings.model) < 0:
            self.model_combo.addItem(f"Configured: {settings.model}", settings.model)
        self._set_combo(self.model_combo, settings.model)
        self._set_combo(self.language_combo, settings.language)
        self._set_combo(self.device_combo, settings.inference_device)
        self._set_combo(self.compute_combo, settings.compute_type)
        self.append_space_check.setChecked(settings.append_space)
        self.expressive_check.setChecked(settings.expressive_punctuation)
        self._set_combo(self.expression_level_combo, settings.expression_level)
        self.preserve_clipboard_check.setChecked(settings.preserve_clipboard_text)
        self.restore_delay.setValue(settings.clipboard_restore_delay_ms)
        self.notifications_check.setChecked(settings.show_notifications)
        self.start_minimized_check.setChecked(settings.start_minimized)

    def set_learned_binding(self, item: dict, target: str = "voice") -> None:
        if target == "enter":
            self._enter_mouse_dict = item.copy()
            self.enter_binding_label.setText(f"{item.get('button_name', item.get('button_code'))} on {item.get('name', 'mouse')}")
            self.enter_learn_button.setText("Remap Enter button…")
        else:
            self._mouse_dict = item.copy()
            self.binding_label.setText(f"{item.get('button_name', item.get('button_code'))} on {item.get('name', 'mouse')}")
            self.learn_button.setText("Remap voice button…")

    def set_learning(self, active: bool, target: str = "voice") -> None:
        self.learn_button.setEnabled(not active)
        self.enter_learn_button.setEnabled(not active)
        if target == "enter":
            self.enter_learn_button.setText("Press the desired mouse button now…" if active else "Map Enter button…")
        else:
            self.learn_button.setText("Press the desired mouse button now…" if active else "Map voice button…")


    def set_paused(self, paused: bool) -> None:
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(paused)
        self.pause_button.setText("Resume VoiceType" if paused else "Pause & unload model")
        self.pause_button.blockSignals(False)

    def _emit_save(self) -> None:
        self.save_requested.emit({
            "mouse": self._mouse_dict.copy(),
            "enter_mouse": self._enter_mouse_dict.copy(),
            "trigger_mode": self.mode_combo.currentData(),
            "suppress_original_button": self.suppress_check.isChecked(),
            "suppress_enter_button": self.enter_suppress_check.isChecked(),
            "microphone_name": self.mic_combo.currentData() or "",
            "model": self.model_combo.currentData(),
            "language": self.language_combo.currentData(),
            "inference_device": self.device_combo.currentData(),
            "compute_type": self.compute_combo.currentData(),
            "append_space": self.append_space_check.isChecked(),
            "expressive_punctuation": self.expressive_check.isChecked(),
            "expression_level": self.expression_level_combo.currentData(),
            "preserve_clipboard_text": self.preserve_clipboard_check.isChecked(),
            "clipboard_restore_delay_ms": self.restore_delay.value(),
            "start_minimized": self.start_minimized_check.isChecked(),
            "show_notifications": self.notifications_check.isChecked(),
        })

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class Tray:
    def __init__(self, window: SettingsWindow, on_pause, on_quit):
        self.tray = QSystemTrayIcon(make_icon("ready"), window)
        self.tray.setToolTip("FACO VoiceType")
        menu = self.tray.contextMenu() or None
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        show_action = QAction("Settings", menu)
        show_action.triggered.connect(window.show)
        menu.addAction(show_action)
        self.pause_action = QAction("Pause & unload model", menu)
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(on_pause)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(on_quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: window.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def state(self, state: str, tooltip: str | None = None) -> None:
        self.tray.setIcon(make_icon(state))
        if tooltip:
            self.tray.setToolTip(tooltip)


    def set_paused(self, paused: bool) -> None:
        self.pause_action.blockSignals(True)
        self.pause_action.setChecked(paused)
        self.pause_action.setText("Resume VoiceType" if paused else "Pause & unload model")
        self.pause_action.blockSignals(False)

    def notify(self, title: str, message: str) -> None:
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 2500)
