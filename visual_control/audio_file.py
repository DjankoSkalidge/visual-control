"""Finds the hits in an audio file, and plays it on a loop, reporting each hit as it's heard.

The song is split into three frequency bands. A hit is a sudden jump in loudness in
one band, like a kick in the low band or a hi-hat in the high one. Analysing the
whole file up front means every hit is known before it plays, so effects land on
the beat instead of just after it.
"""

from __future__ import annotations

import time
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import av
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

AUDIO_FILE_SUFFIXES = frozenset({".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac"})

# Analysis works on a mono copy at this rate. Hi-hats sit up to about 11 kHz, which fits.
ANALYSIS_RATE = 22050
FRAME_SIZE = 1024  # Samples per spectrum, about 46 ms.
HOP_SIZE = 256  # Samples between spectra, about 12 ms, which sets how exactly hits are timed.
# How many spectra back a rise in loudness is measured from, about 35 ms. Over a
# single step, the same drum scores up to 40% differently depending on where it
# falls between spectra, which sensitivity can't tell from a quieter hit.
RISE_SPAN = 3
FRAME_RATE = ANALYSIS_RATE / HOP_SIZE


class Band(Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


# The frequencies each band covers, in Hz.
BAND_RANGES = {Band.LOW: (30, 150), Band.MID: (200, 4000), Band.HIGH: (6000, 11000)}
BAND_LABELS = {
    Band.LOW: "Low (kick, bass)",
    Band.MID: "Mid (snare, claps)",
    Band.HIGH: "High (hi-hats, cymbals)",
}

# Sensitivity runs from 0 (only the strongest hits) to 100 (nearly every one).
DEFAULT_SENSITIVITY = 50
# A hit has to be at least this much of the strongest hit in the CONTEXT around it,
# from MOST_SELECTIVE at sensitivity 0 to LEAST_SELECTIVE at 100.
MOST_SELECTIVE = 0.9
LEAST_SELECTIVE = 0.3
CONTEXT = 4.0  # Seconds either side. Quiet parts of a song still get their own hits.
PEAK_WINDOW = 0.05  # Seconds either side a hit must be the loudest in.
AVERAGE_WINDOW = 0.5  # Seconds either side of the average a hit must stand out from.
ABOVE_AVERAGE = 1.5  # How many times the average a hit must be.
NOISE_FLOOR = 0.02  # Of the band's loudest jump. Anything less is hiss, not a hit.
MIN_GAP = 0.1  # Seconds between hits in one band, so one drum can't count twice.

# A hit this late is skipped instead of played, so a stall, like a suspended
# laptop, can't end in a burst of every hit that was missed.
LATE_LIMIT = 0.1
TICK_MS = 5  # How often the player checks for hits that are due.
# Qt only reports the playing position every 50 ms or so. Between reports, the
# position is worked out from the system clock. A report this far off the
# estimate means a jump, like the song looping, rather than timing jitter.
RESYNC_LIMIT = 0.1
# How much of each report's difference to correct at once. Small, so the jitter in
# when reports arrive is averaged out instead of making hits wobble.
SMOOTHING = 0.1

# Tests set this, so they never make a sound.
MUTED = False


def is_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_FILE_SUFFIXES


class AudioFileError(Exception):
    """An audio file can't be used. The message names the file and the problem."""


def _selectivity(sensitivity: int) -> float:
    return MOST_SELECTIVE + (LEAST_SELECTIVE - MOST_SELECTIVE) * sensitivity / 100


def _window(values: np.ndarray, seconds: float) -> np.ndarray:
    """Each value's neighbourhood, as rows, padded at the ends with the end values."""
    size = max(1, round(seconds * FRAME_RATE))
    return sliding_window_view(np.pad(values, size, mode="edge"), 2 * size + 1)


@dataclass(frozen=True, eq=False)
class AudioAnalysis:
    """How sharply each band gets louder over time, from which hits are picked."""

    name: str  # The file name, for the status bar.
    path: str
    length: float  # Seconds. The song loops after this.
    # Per band, how much louder each spectrum is than the one before, scaled so the
    # biggest jump is 1.0. One value every 1 / FRAME_RATE seconds.
    flux: dict[Band, np.ndarray]
    _cache: dict = field(default_factory=dict, repr=False)

    def hits(self, band: Band, sensitivity: int = DEFAULT_SENSITIVITY) -> np.ndarray:
        """The times of the band's hits, in seconds, in order."""
        key = (band, sensitivity)
        if key not in self._cache:
            self._cache[key] = self._find_hits(self.flux[band], _selectivity(sensitivity))
        return self._cache[key]

    @staticmethod
    def _find_hits(flux: np.ndarray, selectivity: float) -> np.ndarray:
        if flux.size == 0:
            return np.empty(0)
        candidates = np.flatnonzero(
            (flux == _window(flux, PEAK_WINDOW).max(axis=1))
            & (flux > _window(flux, AVERAGE_WINDOW).mean(axis=1) * ABOVE_AVERAGE)
            & (flux >= _window(flux, CONTEXT).max(axis=1) * selectivity)
            & (flux > NOISE_FLOOR)
        )
        min_gap = MIN_GAP * FRAME_RATE
        kept = []
        for frame in candidates:
            if not kept or frame - kept[-1] >= min_gap:
                kept.append(frame)
        # A spectrum's time is its middle, which is where a new sound shows up most.
        return np.array(kept, dtype=float) / FRAME_RATE + FRAME_SIZE / 2 / ANALYSIS_RATE


def _decode_mono(path: str | Path) -> np.ndarray:
    resampler = av.AudioResampler(format="flt", layout="mono", rate=ANALYSIS_RATE)
    chunks = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError("no audio")
        for frame in container.decode(container.streams.audio[0]):
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
    chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    return np.concatenate(chunks) if chunks else np.empty(0, np.float32)


def _band_flux(samples: np.ndarray) -> dict[Band, np.ndarray]:
    frames = sliding_window_view(samples, FRAME_SIZE)[::HOP_SIZE]
    window = np.hanning(FRAME_SIZE).astype(np.float32)
    freqs = np.fft.rfftfreq(FRAME_SIZE, 1 / ANALYSIS_RATE)
    masks = {band: (freqs >= low) & (freqs < high) for band, (low, high) in BAND_RANGES.items()}
    flux = {band: np.zeros(len(frames), np.float32) for band in Band}
    # In blocks, to keep memory down for long songs. Each block starts RISE_SPAN
    # spectra early, so it can compare its first spectra with earlier ones.
    for start in range(0, len(frames), 4096):
        first = max(0, start - RISE_SPAN)
        # Log loudness, so a jump counts the same in a quiet passage as a loud one.
        spectrum = np.log1p(100 * np.abs(np.fft.rfft(frames[first : start + 4096] * window)))
        rise = np.maximum(0, spectrum[RISE_SPAN:] - spectrum[:-RISE_SPAN])  # Only louder counts.
        for band, mask in masks.items():
            values = rise[:, mask].mean(axis=1)
            flux[band][first + RISE_SPAN : first + RISE_SPAN + len(values)] = values
    for band, values in flux.items():
        peak = values.max(initial=0)
        if peak > 0:
            values /= peak
    return flux


def read_audio_file(path: str | Path) -> AudioAnalysis:
    name = Path(path).name
    try:
        samples = _decode_mono(path)
    except Exception as exc:  # PyAV raises many kinds of error for a damaged file.
        raise AudioFileError(f"{name}: can't read it as an audio file") from exc
    if len(samples) < FRAME_SIZE:
        raise AudioFileError(f"{name} is too short to loop")
    if not np.any(np.abs(samples) > 1e-4):
        raise AudioFileError(f"{name} is silent")
    return AudioAnalysis(name, str(path), len(samples) / ANALYSIS_RATE, _band_flux(samples))


class AudioClock:
    """The playing position, smoothed between Qt's coarse position reports."""

    def __init__(self, length: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._length = length
        self._clock = clock
        self._offset: float | None = None  # System time minus position.

    def report(self, position: float) -> None:
        offset = self._clock() - position
        if self._offset is None:
            self._offset = offset
            return
        # Compare within one loop, so reports just after looping aren't a jump.
        difference = (offset - self._offset + self._length / 2) % self._length - self._length / 2
        if abs(difference) > RESYNC_LIMIT:
            self._offset = offset
        else:
            self._offset += difference * SMOOTHING

    def position(self) -> float | None:
        """Seconds into the current loop, or None until the first report."""
        if self._offset is None:
            return None
        return (self._clock() - self._offset) % self._length

    def reset(self) -> None:
        self._offset = None


class HitSchedule:
    """Turns a playing position into the hits that have passed since the last one."""

    def __init__(self, hits: list[tuple[float, Band]], length: float) -> None:
        self._hits = sorted(hits, key=lambda hit: hit[0])
        self._times = [hit_time for hit_time, _ in self._hits]
        self._length = length
        self._last: float | None = None  # The last position hits were played up to.

    def advance(self, position: float) -> list[Band]:
        if self._last is None:
            # Hits right at the start are due straight away.
            self._last = position
            return self._between(-1.0, position)
        moved = (position - self._last) % self._length
        if moved > self._length / 2:
            return []  # A small step back, from smoothing. Wait for it to catch up.
        if moved > LATE_LIMIT:
            self._last = position  # A stall or a jump. Skip what was missed.
            return []
        start, self._last = self._last, position
        if position >= start:
            return self._between(start, position)
        return self._between(start, self._length) + self._between(-1.0, position)

    def reset(self) -> None:
        self._last = None

    def _between(self, after: float, upto: float) -> list[Band]:
        """Hits after one time, up to and including another."""
        first = bisect_right(self._times, after)
        last = bisect_right(self._times, upto)
        return [band for _, band in self._hits[first:last]]


class AudioFilePlayer(QObject):
    """Plays an audio file on a loop, and reports each assigned band's hits as they're heard."""

    hit = Signal(object)  # The Band.
    failed = Signal(str)

    def __init__(self, analysis: AudioAnalysis, sensitivities: dict[Band, int]) -> None:
        super().__init__()
        self._analysis = analysis
        hits = [
            (float(hit_time), band)
            for band, sensitivity in sensitivities.items()
            for hit_time in analysis.hits(band, sensitivity)
        ]
        self._schedule = HitSchedule(hits, analysis.length)
        self._clock = AudioClock(analysis.length)

        self._output = QAudioOutput(self)
        self._output.setMuted(MUTED)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.positionChanged.connect(self._on_position)
        self._player.errorOccurred.connect(self._on_error)
        self._player.setSource(QUrl.fromLocalFile(analysis.path))

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    @property
    def analysis(self) -> AudioAnalysis:
        return self._analysis

    def start(self) -> None:
        self._clock.reset()
        self._schedule.reset()
        self._player.setPosition(0)
        self._player.play()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._player.stop()

    def _on_position(self, milliseconds: int) -> None:
        # Qt reports 0 before the sound has actually started.
        if milliseconds > 0 and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._clock.report(milliseconds / 1000)

    def _tick(self) -> None:
        position = self._clock.position()
        if position is not None:
            for band in self._schedule.advance(position):
                self.hit.emit(band)

    def _on_error(self, _error, message: str) -> None:
        self.stop()
        self.failed.emit(message or "can't play it")
