"""The window for setting up a controller by moving its physical controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .controllers.config import Controller, Note, describe_control, replaces, save_controller
from .effects import PRESS_EFFECTS, Effect
from .midi import MidiCapture, input_device_names, port_match_for

DEVICE_REFRESH_INTERVAL_MS = 2000
NOT_ASSIGNED = "Not assigned"
LISTENING = "Move a control..."
NOTE_STYLE = "color: #b9770e;"
ERROR_STYLE = "color: #c0392b;"
# Screen height to leave for everything around the list of effects.
ROOM_AROUND_EFFECTS = 240


def label_for(effect: Effect) -> str:
    return effect.name.replace("_", " ").capitalize().replace("Rgb", "RGB")


class ControllerConfigDialog(QDialog):
    def __init__(self, controllers: list[Controller], folder: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure new controller")
        self.setMinimumWidth(480)
        self._controllers = controllers
        self._folder = folder
        self._assignments: dict[Effect, int | Note] = {}
        self._listening_for: Effect | None = None
        self._capture = MidiCapture()
        self._capture.control_moved.connect(self._on_control_moved)

        self._device = QComboBox()
        self._device.currentTextChanged.connect(self._select_device)
        self._name = QLineEdit()
        self._name.textChanged.connect(self._update_save_button)
        form = QFormLayout()
        form.addRow("MIDI device", self._device)
        form.addRow("Name", self._name)

        self._device_note = QLabel()
        self._device_note.setWordWrap(True)
        self._device_note.setStyleSheet(NOTE_STYLE)

        self._assign_buttons: dict[Effect, QPushButton] = {}
        self._clear_buttons: dict[Effect, QPushButton] = {}
        self._row_notes: dict[Effect, QLabel] = {}
        effect_rows = QWidget()
        grid = QGridLayout(effect_rows)
        grid.setColumnStretch(1, 1)
        for row, effect in enumerate(Effect):
            assign = QPushButton(NOT_ASSIGNED)
            assign.setAutoDefault(False)
            assign.clicked.connect(lambda _=False, e=effect: self._toggle_listening(e))
            clear = QPushButton("Clear")
            clear.setAutoDefault(False)
            clear.clicked.connect(lambda _=False, e=effect: self._clear(e))
            note = QLabel()
            note.setStyleSheet(NOTE_STYLE)
            grid.addWidget(QLabel(label_for(effect)), row, 0)
            grid.addWidget(assign, row, 1)
            grid.addWidget(clear, row, 2)
            grid.addWidget(note, row, 3)
            self._assign_buttons[effect] = assign
            self._clear_buttons[effect] = clear
            self._row_notes[effect] = note

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet(ERROR_STYLE)

        self._save_button = QPushButton("Save")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._device_note)
        layout.addWidget(QLabel("Click an effect's button, then move a control on your device."))
        layout.addWidget(self._scrolling(effect_rows), stretch=1)
        layout.addWidget(self._error)
        layout.addLayout(buttons)

        self._device_timer = QTimer(self)
        self._device_timer.setInterval(DEVICE_REFRESH_INTERVAL_MS)
        self._device_timer.timeout.connect(self._refresh_devices)
        self._device_timer.start()
        self._refresh_devices()
        self._select_device(self._device.currentText())

    def _scrolling(self, effect_rows: QWidget) -> QScrollArea:
        """Show every effect at once if the screen has room, or else scroll, so Save stays on it."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(effect_rows)
        wanted = effect_rows.sizeHint()
        room = self.screen().availableGeometry().height() - ROOM_AROUND_EFFECTS
        scroll.setMinimumHeight(min(wanted.height(), room))
        scroll.setMinimumWidth(wanted.width() + scroll.verticalScrollBar().sizeHint().width())
        return scroll

    def _refresh_devices(self) -> None:
        """Keep the list current, so a device can be plugged in while this is open."""
        names = input_device_names()
        current = self._device.currentText()
        if names == [self._device.itemText(i) for i in range(self._device.count())]:
            return
        self._device.blockSignals(True)
        self._device.clear()
        self._device.addItems(names)
        if current in names:
            self._device.setCurrentText(current)
        self._device.blockSignals(False)
        if self._device.currentText() != current:
            self._select_device(self._device.currentText())

    def _select_device(self, device_name: str) -> None:
        # Control numbers belong to one device, so another device starts over.
        self._listening_for = None
        self._assignments = {}
        self._error.clear()
        self._device_note.clear()
        for note in self._row_notes.values():
            note.clear()

        if not device_name:
            self._capture.close()
            self._name.clear()
            self._device_note.setText("No MIDI devices found. Plug one in to continue.")
        elif not self._capture.open(device_name):
            self._error.setText(f"Can't open {device_name}. Try unplugging it and plugging it back in.")
        else:
            existing = next((c for c in self._controllers if c.port_match in device_name), None)
            if existing is None:
                self._name.setText(device_name.split(":")[0])
            else:
                self._name.setText(existing.name)
                self._assignments = dict(existing.effects)
                self._device_note.setText(
                    f"This device is set up as {existing.name}. Saving replaces that setup."
                )
        self._update_rows()

    def _toggle_listening(self, effect: Effect) -> None:
        self._listening_for = None if self._listening_for is effect else effect
        self._update_rows()

    def _clear(self, effect: Effect) -> None:
        self._assignments.pop(effect, None)
        self._row_notes[effect].clear()
        if self._listening_for is effect:
            self._listening_for = None
        self._update_rows()

    def _on_control_moved(self, control: int | Note) -> None:
        effect = self._listening_for
        if effect is None:
            return
        for note in self._row_notes.values():
            note.clear()
        if isinstance(control, Note) and effect not in PRESS_EFFECTS:
            # A note has no position to follow, so keep waiting for something that does.
            self._row_notes[effect].setText("Needs a slider or rotary encoder")
            return
        self._listening_for = None
        for other, assigned in list(self._assignments.items()):
            if assigned == control and other is not effect:
                del self._assignments[other]
                self._row_notes[effect].setText(f"Moved from {label_for(other)}")
        self._assignments[effect] = control
        self._update_rows()

    def _update_rows(self) -> None:
        for effect, button in self._assign_buttons.items():
            if self._listening_for is effect:
                button.setText(LISTENING)
            elif effect in self._assignments:
                button.setText(describe_control(self._assignments[effect]).capitalize())
            else:
                button.setText(NOT_ASSIGNED)
            enabled = bool(self._device.currentText())
            button.setEnabled(enabled)
            self._clear_buttons[effect].setEnabled(effect in self._assignments)
        self._update_save_button()

    def _update_save_button(self) -> None:
        self._save_button.setEnabled(
            bool(self._device.currentText() and self._name.text().strip() and self._assignments)
        )

    def _confirm_replace(self, names: list[str]) -> bool:
        answer = QMessageBox.question(
            self,
            "Replace controller?",
            f"This replaces {' and '.join(names)}. Do you want to continue?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _save(self) -> None:
        controller = Controller(
            self._name.text().strip(),
            port_match_for(self._device.currentText()),
            {e: self._assignments[e] for e in Effect if e in self._assignments},
        )
        replaced = [c.name for c in self._controllers if replaces(controller, c)]
        if replaced and not self._confirm_replace(replaced):
            return
        try:
            save_controller(controller, self._folder)
        except OSError as exc:
            self._error.setText(f"Couldn't save the controller: {exc}")
            return
        self.accept()

    def keyPressEvent(self, event) -> None:
        # Like a hotkey editor, Esc first cancels the assignment in progress.
        if event.key() == Qt.Key.Key_Escape and self._listening_for is not None:
            self._listening_for = None
            self._update_rows()
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        self._device_timer.stop()
        self._capture.close()
        super().done(result)
