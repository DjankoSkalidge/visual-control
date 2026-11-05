"""The panel for choosing which effect each note in a MIDI file triggers."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config_window import label_for
from .effects import PRESS_EFFECTS, Effect
from .midi_file import ChannelPart, MidiFileNotes, describe_channel, describe_drum

NO_EFFECT = "None"
# Pausing from a file would stop the picture at moments nobody chose.
MIDI_FILE_EFFECTS = tuple(e for e in Effect if e in PRESS_EFFECTS and e is not Effect.PAUSE)


def _hits(count: int) -> str:
    return f"{count} {'hit' if count == 1 else 'hits'}"


class MidiFileDialog(QDialog):
    def __init__(self, notes: MidiFileNotes, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up MIDI file")
        self.setMinimumWidth(480)
        self._notes = notes
        self.part: ChannelPart = notes.on_channel(notes.default_channel())
        self._effect_choices: dict[int, QComboBox] = {}

        intro = QLabel(
            f"The most played notes in {notes.name}. Choose an effect for each one, "
            "and it plays every time that note does."
        )
        intro.setWordWrap(True)

        self._channel = QComboBox()
        for channel, count in notes.channels():
            self._channel.addItem(f"{describe_channel(channel)}: {_hits(count)}", channel)
        self._channel.setCurrentIndex(self._channel.findData(notes.default_channel()))
        self._channel.currentIndexChanged.connect(self._select_channel)
        form = QFormLayout()
        form.addRow("Channel", self._channel)

        self._rows = QWidget()
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.addWidget(self._rows)

        self._start_button = QPushButton("Start")
        self._start_button.setDefault(True)
        self._start_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._start_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addLayout(self._rows_layout)
        layout.addLayout(buttons)
        self._show_notes()

    def assignments(self) -> dict[int, Effect]:
        """Note -> the effect it triggers, for the notes that have one."""
        chosen = {note: choice.currentData() for note, choice in self._effect_choices.items()}
        return {note: effect for note, effect in chosen.items() if effect is not None}

    def _select_channel(self) -> None:
        # Another channel has other notes, so its choices start over.
        self.part = self._notes.on_channel(self._channel.currentData())
        self._show_notes()

    def _show_notes(self) -> None:
        rows = QWidget()
        grid = QGridLayout(rows)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(2, 1)
        self._effect_choices = {}
        for row, (note, count) in enumerate(self.part.most_played()):
            choice = QComboBox()
            choice.addItem(NO_EFFECT, None)
            for effect in MIDI_FILE_EFFECTS:
                choice.addItem(label_for(effect), effect)
            choice.currentIndexChanged.connect(self._update_start_button)
            grid.addWidget(QLabel(describe_drum(note)), row, 0)
            grid.addWidget(QLabel(_hits(count)), row, 1)
            grid.addWidget(choice, row, 2)
            self._effect_choices[note] = choice
        self._rows_layout.replaceWidget(self._rows, rows)
        self._rows.deleteLater()
        self._rows = rows
        self._update_start_button()
        self.adjustSize()

    def _update_start_button(self) -> None:
        self._start_button.setEnabled(bool(self.assignments()))
