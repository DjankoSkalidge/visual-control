"""Reads the notes in a MIDI file, and plays one channel's back on a loop as presses."""

from __future__ import annotations

import time
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import mido
from PySide6.QtCore import QObject, Qt, QTimer, Signal

MIDI_FILE_SUFFIXES = frozenset({".mid", ".midi"})
# General MIDI's drum channel, channel 10. mido counts channels from 0. Drum loops
# made for a sampler often use channel 1 instead, so this is only the first choice.
DRUM_CHANNEL = 9
MOST_PLAYED_LIMIT = 10
# A note this late is skipped instead of played, so a stall, like a suspended
# laptop, can't end in a burst of every note that was missed.
LATE_LIMIT = 0.1

# The General MIDI drum names, by note number. Drum loops use these numbers on any channel.
DRUM_NAMES = {
    35: "Acoustic Bass Drum", 36: "Bass Drum 1", 37: "Side Stick", 38: "Acoustic Snare",
    39: "Hand Clap", 40: "Electric Snare", 41: "Low Floor Tom", 42: "Closed Hi-Hat",
    43: "High Floor Tom", 44: "Pedal Hi-Hat", 45: "Low Tom", 46: "Open Hi-Hat",
    47: "Low-Mid Tom", 48: "Hi-Mid Tom", 49: "Crash Cymbal 1", 50: "High Tom",
    51: "Ride Cymbal 1", 52: "Chinese Cymbal", 53: "Ride Bell", 54: "Tambourine",
    55: "Splash Cymbal", 56: "Cowbell", 57: "Crash Cymbal 2", 58: "Vibraslap",
    59: "Ride Cymbal 2", 60: "Hi Bongo", 61: "Low Bongo", 62: "Mute Hi Conga",
    63: "Open Hi Conga", 64: "Low Conga", 65: "High Timbale", 66: "Low Timbale",
    67: "High Agogo", 68: "Low Agogo", 69: "Cabasa", 70: "Maracas",
    71: "Short Whistle", 72: "Long Whistle", 73: "Short Guiro", 74: "Long Guiro",
    75: "Claves", 76: "Hi Wood Block", 77: "Low Wood Block", 78: "Mute Cuica",
    79: "Open Cuica", 80: "Mute Triangle", 81: "Open Triangle",
}


def is_midi_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in MIDI_FILE_SUFFIXES


def describe_drum(note: int) -> str:
    name = DRUM_NAMES.get(note)
    return f"{name} ({note})" if name else f"Note {note}"


def describe_channel(channel: int) -> str:
    """As people number channels, from 1."""
    return f"Channel {channel + 1}" + (" (drums)" if channel == DRUM_CHANNEL else "")


class MidiFileError(Exception):
    """A MIDI file can't be used. The message names the file and the problem."""


@dataclass(frozen=True)
class ChannelPart:
    """The notes on one channel, which is what plays."""

    name: str  # The file name, for the status bar.
    hits: tuple[tuple[float, int], ...]  # Seconds from the start and note, in time order.
    length: float  # Seconds. The part loops after this, like the file would.

    def most_played(self, limit: int = MOST_PLAYED_LIMIT) -> list[tuple[int, int]]:
        """The notes played most, with how often. Ties go to the lower note."""
        counts = Counter(note for _, note in self.hits)
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


@dataclass(frozen=True)
class MidiFileNotes:
    """Every note in a file, on every channel."""

    name: str
    hits: tuple[tuple[float, int, int], ...]  # Seconds, channel and note, in time order.
    length: float

    def channels(self) -> list[tuple[int, int]]:
        """The channels with notes, in order, with how many hits each has."""
        return sorted(Counter(channel for _, channel, _ in self.hits).items())

    def default_channel(self) -> int:
        """The drum channel if it's used, or else the busiest one, or the lower if tied."""
        channels = self.channels()
        if any(channel == DRUM_CHANNEL for channel, _ in channels):
            return DRUM_CHANNEL
        return min(channels, key=lambda item: (-item[1], item[0]))[0]

    def on_channel(self, channel: int) -> ChannelPart:
        hits = tuple((time, note) for time, ch, note in self.hits if ch == channel)
        return ChannelPart(self.name, hits, self.length)


def read_midi_file(path: str | Path) -> MidiFileNotes:
    name = Path(path).name
    try:
        midi = mido.MidiFile(path)
    except Exception as exc:  # mido raises many kinds of error for a damaged file.
        raise MidiFileError(f"{name}: can't read it as a MIDI file") from exc
    if midi.type == 2:
        raise MidiFileError(f"{name}: type 2 MIDI files aren't supported")

    hits = []
    elapsed = 0.0
    try:
        # Iterating gives times in seconds, following any tempo changes.
        for message in midi:
            elapsed += message.time
            # Velocity 0 is how some files end a note.
            if message.type == "note_on" and message.velocity > 0:
                hits.append((elapsed, message.channel, message.note))
    except Exception as exc:
        raise MidiFileError(f"{name}: can't read it as a MIDI file") from exc
    if not hits:
        raise MidiFileError(f"{name} has no notes")
    if elapsed <= 0:
        raise MidiFileError(f"{name} is too short to loop")
    return MidiFileNotes(name, tuple(hits), elapsed)


class MidiFilePlayer(QObject):
    """Plays one channel's notes on a loop, reporting each note as it's due."""

    note_played = Signal(int)

    def __init__(self, part: ChannelPart, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self._part = part
        self._times = [hit_time for hit_time, _ in part.hits]
        self._clock = clock
        self._loop_start = 0.0
        self._next = 0  # The index of the next hit to play.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self.play_due)

    @property
    def part(self) -> ChannelPart:
        return self._part

    def start(self) -> None:
        self._loop_start = self._clock()
        self._next = 0
        self.play_due()

    def stop(self) -> None:
        self._timer.stop()

    def play_due(self) -> None:
        """Play every note that's due, then wait for the next one."""
        now = self._clock()
        # Times count from the start of the current loop, so they never drift.
        if self._due_time() < now - LATE_LIMIT:
            self._skip_to(now)
        while self._due_time() <= now:
            self.note_played.emit(self._part.hits[self._next][1])
            self._advance()
        wait = self._due_time() - self._clock()
        self._timer.start(max(0, round(wait * 1000)))

    def _due_time(self) -> float:
        return self._loop_start + self._times[self._next]

    def _advance(self) -> None:
        self._next += 1
        if self._next == len(self._times):
            self._next = 0
            self._loop_start += self._part.length

    def _skip_to(self, now: float) -> None:
        """Move past every note before now, without playing them."""
        missed_loops = (now - self._loop_start) // self._part.length
        self._loop_start += missed_loops * self._part.length
        self._next = bisect_left(self._times, now - self._loop_start)
        if self._next == len(self._times):
            self._next = 0
            self._loop_start += self._part.length
