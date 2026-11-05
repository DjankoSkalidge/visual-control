"""Receives rotary encoder and slider moves from the MIDI controller."""

from __future__ import annotations

import re

import mido
from PySide6.QtCore import QObject, QTimer, Signal

from .controllers.config import Controller, Note
from .effects import PRESS_EFFECTS

RECONNECT_INTERVAL_MS = 2000
MIDI_MAX_VALUE = 127
# The high half of the status byte; the low half is the channel.
CONTROL_CHANGE = 0xB0
NOTE_ON = 0x90


def _control_in(message: mido.Message) -> tuple[int | Note, int] | None:
    """The control a message came from and its value, or None for anything else."""
    data = message.bytes()
    if len(data) != 3:
        return None
    if data[0] & 0xF0 == CONTROL_CHANGE:
        return data[1], data[2]
    # A note on with no velocity is how some devices report a release.
    if data[0] & 0xF0 == NOTE_ON and data[2] > 0:
        return Note(data[1]), data[2]
    return None


def input_device_names() -> list[str]:
    """The connected MIDI devices. A failure just means there are none to offer."""
    try:
        return [name for name in mido.get_input_names() if "Midi Through" not in name]
    except Exception:
        return []


def port_match_for(device_name: str) -> str:
    """Text that finds a device again. The trailing "36:0" can change between sessions."""
    return re.sub(r"\s+\d+:\d+$", "", device_name)


class MidiCapture(QObject):
    """Reports every control moved on one device, for assigning controls to effects."""

    control_moved = Signal(object)  # control number, or Note

    def __init__(self) -> None:
        super().__init__()
        self._port = None

    def open(self, device_name: str) -> bool:
        self.close()
        try:
            self._port = mido.open_input(device_name, callback=self._on_message)
        except Exception:
            return False
        return True

    def close(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None

    def _on_message(self, message: mido.Message) -> None:
        # Runs on the MIDI thread. Qt queues the signal over to the GUI thread.
        control = _control_in(message)
        if control is not None:
            self.control_moved.emit(control[0])


class MidiInput(QObject):
    """Reports effect changes from one controller, connecting whenever it's plugged in."""

    effect_changed = Signal(object, float)  # Effect, amount 0.0-1.0
    connection_changed = Signal(bool)

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller
        self._port = None
        self._last_values: dict[int, int] = {}  # Only used on the MIDI thread.
        self._timer = QTimer(self)
        self._timer.setInterval(RECONNECT_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._close_port()

    def refresh(self) -> None:
        # MIDI must never take the visuals down, so any failure just means
        # "not connected" and is retried on the next refresh.
        try:
            names = mido.get_input_names()
            if self._port is not None and self._port.name not in names:
                self._close_port()
                self.connection_changed.emit(False)
            if self._port is None:
                name = next((n for n in names if self._controller.port_match in n), None)
                if name is not None:
                    self._port = mido.open_input(name, callback=self._on_message)
                    self.connection_changed.emit(True)
        except Exception:
            if self._port is not None:
                self._close_port()
                self.connection_changed.emit(False)

    def _close_port(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None

    def _on_message(self, message: mido.Message) -> None:
        # Runs on the MIDI thread. Qt queues the signal over to the GUI thread.
        received = _control_in(message)
        if received is None:
            return
        control, value = received
        # A button sends a value when pressed and 0 when released, and a slider sends
        # many values, so a press is a control leaving 0. Each note on is its own press.
        previous = self._last_values.get(control, 0) if isinstance(control, int) else 0
        if isinstance(control, int):
            self._last_values[control] = value
        pressed = value > 0 and previous == 0

        for effect, assigned in self._controller.effects.items():
            if assigned != control:
                continue
            if effect not in PRESS_EFFECTS:
                self.effect_changed.emit(effect, value / MIDI_MAX_VALUE)
            elif pressed:
                self.effect_changed.emit(effect, 1.0)
