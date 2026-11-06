"""The panel for choosing which effect each frequency band's hits trigger."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from .audio_file import BAND_LABELS, DEFAULT_SENSITIVITY, AudioAnalysis, Band
from .config_window import label_for
from .effects import Effect
from .midi_file_window import MIDI_FILE_EFFECTS, NO_EFFECT

# The same as for MIDI files: every press effect but pause.
AUDIO_FILE_EFFECTS = MIDI_FILE_EFFECTS


def describe_hits(count: int, length: float) -> str:
    noun = "hit" if count == 1 else "hits"
    return f"{count} {noun}, {count / length:.1f} per second"


class AudioFileDialog(QDialog):
    def __init__(self, analysis: AudioAnalysis, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up audio file")
        self.setMinimumWidth(640)
        self._analysis = analysis
        self._effect_choices: dict[Band, QComboBox] = {}
        self._sensitivities: dict[Band, QSlider] = {}
        self._counts: dict[Band, QLabel] = {}

        intro = QLabel(
            f"{analysis.name} is split into three frequency bands, and each sudden jump "
            "in loudness counts as a hit. Choose an effect for a band, and it plays on "
            "every hit. Higher sensitivity finds more, quieter hits."
        )
        intro.setWordWrap(True)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for column, heading in enumerate(("Band", "Sensitivity", "Hits", "Effect")):
            grid.addWidget(QLabel(f"<b>{heading}</b>"), 0, column)
        for row, band in enumerate(Band, start=1):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(DEFAULT_SENSITIVITY)
            slider.setMinimumWidth(160)
            slider.valueChanged.connect(lambda _value, band=band: self._update_count(band))
            choice = QComboBox()
            choice.addItem(NO_EFFECT, None)
            for effect in AUDIO_FILE_EFFECTS:
                choice.addItem(label_for(effect), effect)
            choice.currentIndexChanged.connect(self._update_start_button)
            count = QLabel()
            grid.addWidget(QLabel(BAND_LABELS[band]), row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(count, row, 2)
            grid.addWidget(choice, row, 3)
            self._sensitivities[band] = slider
            self._counts[band] = count
            self._effect_choices[band] = choice
            self._update_count(band)

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
        layout.addLayout(grid)
        layout.addLayout(buttons)
        self._update_start_button()

    @property
    def analysis(self) -> AudioAnalysis:
        return self._analysis

    def assignments(self) -> dict[Band, Effect]:
        """Band -> the effect it triggers, for the bands that have one."""
        chosen = {band: choice.currentData() for band, choice in self._effect_choices.items()}
        return {band: effect for band, effect in chosen.items() if effect is not None}

    def sensitivities(self) -> dict[Band, int]:
        """The sensitivity of each band that has an effect."""
        return {band: self._sensitivities[band].value() for band in self.assignments()}

    def _update_count(self, band: Band) -> None:
        hits = self._analysis.hits(band, self._sensitivities[band].value())
        self._counts[band].setText(describe_hits(len(hits), self._analysis.length))

    def _update_start_button(self) -> None:
        self._start_button.setEnabled(bool(self.assignments()))
