"""The window for assigning keys on the computer's keyboard to press effects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .config_window import ERROR_STYLE, NOT_ASSIGNED, NOTE_STYLE, label_for
from .effects import Effect
from .keyboard import (
    KEYBOARD_EFFECTS,
    RESERVED_KEYS,
    SHORTCUT_MODIFIERS,
    can_assign,
    describe_key,
    save_keyboard,
)

LISTENING = "Press a key..."
COLUMN_WIDTH = 5  # Grid columns per column of effects: four, then a gap.


class KeyboardConfigDialog(QDialog):
    def __init__(self, effects: dict[Effect, int], path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure keyboard")
        self.setMinimumWidth(720)
        self._path = path
        self._assignments: dict[Effect, int] = dict(effects)
        self._listening_for: Effect | None = None

        self._assign_buttons: dict[Effect, QPushButton] = {}
        self._clear_buttons: dict[Effect, QPushButton] = {}
        self._row_notes: dict[Effect, QLabel] = {}
        # Two columns of effects, so the window isn't taller than a screen.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        rows = (len(KEYBOARD_EFFECTS) + 1) // 2
        for index, effect in enumerate(KEYBOARD_EFFECTS):
            row, first = index % rows, (index // rows) * COLUMN_WIDTH
            assign = QPushButton(NOT_ASSIGNED)
            assign.setAutoDefault(False)
            assign.clicked.connect(lambda _=False, e=effect: self._toggle_listening(e))
            clear = QPushButton("Clear")
            clear.setAutoDefault(False)
            clear.clicked.connect(lambda _=False, e=effect: self._clear(e))
            note = QLabel()
            note.setStyleSheet(NOTE_STYLE)
            grid.addWidget(QLabel(label_for(effect)), row, first)
            grid.addWidget(assign, row, first + 1)
            grid.addWidget(clear, row, first + 2)
            grid.addWidget(note, row, first + 3)
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
        layout.addWidget(QLabel("Click an effect's button, then press a key."))
        # The key buttons take up any spare width, and a gap separates the columns.
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(COLUMN_WIDTH + 1, 1)
        grid.setColumnMinimumWidth(COLUMN_WIDTH - 1, 24)
        layout.addLayout(grid)
        layout.addWidget(self._error)
        layout.addLayout(buttons)
        self._update_rows()

        # Keys like Space and Tab would otherwise reach the focused button first.
        QApplication.instance().installEventFilter(self)

    def assignments(self) -> dict[Effect, int]:
        return dict(self._assignments)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            self._listening_for is not None
            and event.type() == QEvent.Type.KeyPress
            and watched.isWidgetType()
            and watched.window() is self
        ):
            return self._on_key_pressed(event)
        return False

    def _on_key_pressed(self, event) -> bool:
        key = event.key()
        if key in RESERVED_KEYS:
            return False  # Esc reaches keyPressEvent, and cancels listening.
        if event.modifiers() & SHORTCUT_MODIFIERS or not can_assign(key):
            return True  # Ctrl, Alt and the like, alone or held, are ignored.
        effect = self._listening_for
        self._listening_for = None
        for note in self._row_notes.values():
            note.clear()
        for other, assigned in list(self._assignments.items()):
            if assigned == key and other is not effect:
                del self._assignments[other]
                self._row_notes[effect].setText(f"Moved from {label_for(other)}")
        self._assignments[effect] = key
        self._update_rows()
        return True

    def _toggle_listening(self, effect: Effect) -> None:
        self._listening_for = None if self._listening_for is effect else effect
        self._update_rows()

    def _clear(self, effect: Effect) -> None:
        self._assignments.pop(effect, None)
        self._row_notes[effect].clear()
        if self._listening_for is effect:
            self._listening_for = None
        self._update_rows()

    def _update_rows(self) -> None:
        for effect, button in self._assign_buttons.items():
            if self._listening_for is effect:
                button.setText(LISTENING)
            elif effect in self._assignments:
                button.setText(describe_key(self._assignments[effect]))
            else:
                button.setText(NOT_ASSIGNED)
            self._clear_buttons[effect].setEnabled(effect in self._assignments)

    def _save(self) -> None:
        try:
            save_keyboard(self._assignments, self._path)
        except OSError as exc:
            self._error.setText(f"Couldn't save the keyboard setup: {exc}")
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
        QApplication.instance().removeEventFilter(self)
        super().done(result)
