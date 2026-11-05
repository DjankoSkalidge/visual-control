from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config_window import ControllerConfigDialog
from .controllers.config import USER_FOLDER, load_all_controllers
from .effects import REMOVE_CHANNEL_EFFECTS, RGB_SHIFT_EFFECTS, SATURATION_EFFECTS, Effect
from .media import MediaError, open_media
from .midi import MidiInput
from .view import ANIMATIONS, MediaView

PLACEHOLDER_TEXT = "Drop an image or video here"
ERROR_STYLE = "color: #c0392b;"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Visual Control")
        self.resize(960, 600)
        self.setAcceptDrops(True)

        self._media_name = ""
        self._placeholder = QLabel(PLACEHOLDER_TEXT)
        self._placeholder.setWordWrap(True)
        # Black like the video bars, so a failure can't flash white on a projector.
        self._placeholder.setStyleSheet("background: black; color: #dddddd;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view = MediaView()
        # Queued because a failure can be raised in the middle of painting the view.
        self._view.playback_failed.connect(
            self._on_playback_failed, Qt.ConnectionType.QueuedConnection
        )

        self._stack = QStackedWidget()
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._view)

        self._status = QLabel()
        # Long text gets cut off, instead of forcing the whole window wider.
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._midi_status = QLabel()
        self._configure_button = QPushButton("Configure new controller")
        self._configure_button.clicked.connect(self.open_controller_config)
        self._fullscreen_button = QPushButton("Fullscreen")
        self._fullscreen_button.clicked.connect(self.toggle_fullscreen)

        self._controls = QWidget()
        controls_layout = QHBoxLayout(self._controls)
        controls_layout.addWidget(self._status, stretch=1)
        controls_layout.addWidget(self._midi_status)
        controls_layout.addWidget(self._configure_button)
        controls_layout.addWidget(self._fullscreen_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack, stretch=1)
        layout.addWidget(self._controls)
        self.setCentralWidget(central)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.exit_fullscreen)

        self._effect_actions = {
            Effect.BLUR: self._view.set_blur,
            Effect.PIXELATE: self._view.set_pixelate,
            **{
                effect: partial(self._view.set_saturation, band)
                for band, effect in enumerate(SATURATION_EFFECTS)
            },
            **{
                effect: partial(self._view.set_rgb_shift, channel, axis)
                for channel, effects in enumerate(RGB_SHIFT_EFFECTS)
                for axis, effect in enumerate(effects)
            },
            Effect.PLAYBACK_SPEED: self._view.set_playback_speed,
            Effect.PAUSE: self._on_pause_pressed,
            **{
                effect: lambda _amount, animation=effect: self._view.start_animation(animation)
                for effect in ANIMATIONS
            },
            Effect.STUTTER: lambda _amount: self._view.start_stutter(),
            Effect.BLACK_AND_WHITE: lambda _amount: self._view.toggle_black_and_white(),
            **{
                effect: lambda _amount, channel=channel: self._view.toggle_channel(channel)
                for channel, effect in enumerate(REMOVE_CHANNEL_EFFECTS)
            },
        }
        self._config_dialog: ControllerConfigDialog | None = None
        self._controllers = []
        self._midi_inputs = []
        self._start_midi()

    def _start_midi(self) -> None:
        for midi in self._midi_inputs:
            midi.stop()
            midi.deleteLater()
        self._controllers, config_errors = load_all_controllers(USER_FOLDER)
        self._midi_connected = {controller.name: False for controller in self._controllers}
        self._update_midi_status()
        self._midi_inputs = []
        for controller in self._controllers:
            midi = MidiInput(controller)
            midi.effect_changed.connect(self._on_effect_changed)
            midi.connection_changed.connect(partial(self._on_midi_connection, controller.name))
            midi.start()
            self._midi_inputs.append(midi)
        if config_errors:
            self._show_error(" ".join(config_errors))

    def load(self, path: str) -> None:
        try:
            source = open_media(path)
        except MediaError as exc:
            self._show_error(str(exc))  # Whatever is playing keeps playing.
            return
        self._view.set_source(source)
        self._stack.setCurrentWidget(self._view)
        self._media_name = Path(path).name
        self._status.setStyleSheet("")
        self._set_status(self._media_name)

    def open_controller_config(self) -> None:
        # Effects stay off until a control is moved after the window closes.
        self._view.reset_effects()
        self._config_dialog = ControllerConfigDialog(self._controllers, USER_FOLDER, self)
        self._config_dialog.finished.connect(self._on_controller_config_finished)
        self._config_dialog.open()

    def _on_controller_config_finished(self, result: int) -> None:
        self._config_dialog.deleteLater()
        self._config_dialog = None
        if result == QDialog.DialogCode.Accepted:
            self._start_midi()

    def toggle_fullscreen(self) -> None:
        # Toggling the flag keeps a maximized window maximized on the way back.
        self.setWindowState(self.windowState() ^ Qt.WindowState.WindowFullScreen)

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            fullscreen = self.isFullScreen()
            self._controls.setVisible(not fullscreen)
            if fullscreen:
                self._stack.setCursor(Qt.CursorShape.BlankCursor)
            else:
                self._stack.unsetCursor()

    def dragEnterEvent(self, event) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                event.acceptProposedAction()
                self.load(url.toLocalFile())
                return

    def closeEvent(self, event) -> None:
        for midi in self._midi_inputs:
            midi.stop()
        self._view.stop()
        super().closeEvent(event)

    def _on_effect_changed(self, effect: Effect, amount: float) -> None:
        # Moving controls to assign them mustn't change the visuals.
        if self._config_dialog is None:
            self._effect_actions[effect](amount)

    def _on_pause_pressed(self, _amount: float) -> None:
        paused = self._view.toggle_pause()
        if paused is not None:
            self._set_status(f"{self._media_name} (paused)" if paused else self._media_name)

    def _on_midi_connection(self, name: str, connected: bool) -> None:
        self._midi_connected[name] = connected
        self._update_midi_status()

    def _update_midi_status(self) -> None:
        names = [name for name, connected in self._midi_connected.items() if connected]
        self._midi_status.setText(
            f"Connected: {', '.join(names)}" if names else "No controllers connected"
        )

    def _on_playback_failed(self, reason: str) -> None:
        self._stack.setCurrentWidget(self._placeholder)
        self._show_error(f"Stopped playing {self._media_name}: {reason}")

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setToolTip(text)

    def _show_error(self, message: str) -> None:
        self._status.setStyleSheet(ERROR_STYLE)
        self._set_status(message)
        # The status bar is hidden in fullscreen, so with nothing playing the
        # message also goes in the middle of the window.
        if self._stack.currentWidget() is self._placeholder:
            self._placeholder.setText(f"{message}\n\n{PLACEHOLDER_TEXT}")
