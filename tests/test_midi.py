"""Sends real MIDI through a virtual port, without needing a controller."""

import time
import unittest

import mido
from PySide6.QtCore import QCoreApplication

from visual_control.controllers.config import Controller, Note
from visual_control.effects import Effect
from visual_control.midi import MidiInput

TEST_PORT = "Visual Control Test Port"
STATUS = 177  # Control change on channel 2.
OTHER_CHANNEL_STATUS = 176  # Control change on channel 1.
BUTTON_STATUS = 145
BLUR_CONTROL = 22
OTHER_CONTROL = 23


class MidiInputTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.received = []
        self.connections = []
        self.midi = MidiInput(
            Controller("Test", TEST_PORT, {Effect.BLUR: BLUR_CONTROL})
        )
        self.midi.effect_changed.connect(lambda e, a: self.received.append((e, a)))
        self.midi.connection_changed.connect(self.connections.append)
        self.addCleanup(self.midi.stop)

    def pump(self, seconds=0.2):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def send(self, *messages):
        with mido.open_output(TEST_PORT, virtual=True) as sender:
            self.midi.refresh()
            for message in messages:
                sender.send(mido.Message.from_bytes(message))
            self.pump()

    def test_missing_controller_is_not_an_error(self):
        self.midi.refresh()
        self.assertEqual(self.connections, [])

    def test_assigned_control_reports_its_effect_and_amount(self):
        self.send([STATUS, BLUR_CONTROL, 127], [STATUS, BLUR_CONTROL, 0])
        self.assertEqual(self.received, [(Effect.BLUR, 1.0), (Effect.BLUR, 0.0)])

    def test_unassigned_control_is_ignored(self):
        self.send([STATUS, OTHER_CONTROL, 127])
        self.assertEqual(self.received, [])

    def test_any_channel_is_accepted(self):
        self.send([OTHER_CHANNEL_STATUS, BLUR_CONTROL, 127])
        self.assertEqual(self.received, [(Effect.BLUR, 1.0)])

    def test_button_with_the_same_number_is_ignored(self):
        self.send([BUTTON_STATUS, BLUR_CONTROL, 127])
        self.assertEqual(self.received, [])

    def test_any_channels_note_or_control_can_press_a_toggle(self):
        self.use_pause_on(Note(36))
        self.send([0x90, 36, 100], [0x93, 36, 100])
        self.assertEqual(self.received, [(Effect.PAUSE, 1.0)] * 2)

    def use_pause_on(self, control) -> None:
        self.midi = MidiInput(Controller("Test", TEST_PORT, {Effect.PAUSE: control}))
        self.midi.effect_changed.connect(lambda e, a: self.received.append((e, a)))
        self.addCleanup(self.midi.stop)

    def test_note_toggles_once_per_press(self):
        self.use_pause_on(Note(36))
        self.send([0x90, 36, 100], [0x80, 36, 0], [0x90, 36, 100], [0x90, 36, 0])
        self.assertEqual(len(self.received), 2)

    def test_control_toggles_once_per_press(self):
        self.use_pause_on(96)
        self.send([STATUS, 96, 127], [STATUS, 96, 0], [STATUS, 96, 127], [STATUS, 96, 0])
        self.assertEqual(len(self.received), 2)

    def test_a_slider_on_a_toggle_presses_once_each_time_it_leaves_zero(self):
        self.use_pause_on(96)
        self.send(*[[STATUS, 96, value] for value in (1, 40, 90, 127, 60, 0, 5, 9)])
        self.assertEqual(len(self.received), 2)

    def test_a_note_with_the_same_number_as_a_control_is_not_that_control(self):
        self.use_pause_on(96)
        self.send([0x90, 96, 100])
        self.assertEqual(self.received, [])

    def test_unplugging_and_replugging_reconnects(self):
        with mido.open_output(TEST_PORT, virtual=True):
            self.midi.refresh()
            self.assertEqual(self.connections, [True])
        self.pump()
        self.midi.refresh()
        self.assertEqual(self.connections, [True, False])
        with mido.open_output(TEST_PORT, virtual=True):
            self.pump()
            self.midi.refresh()
            self.assertEqual(self.connections, [True, False, True])


if __name__ == "__main__":
    unittest.main()
