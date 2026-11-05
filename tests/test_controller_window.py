"""The real controller configurations in a real window, sending MIDI through virtual ports."""

import os
import unittest

import mido
from PySide6.QtTest import QTest

from tests.gui import TEST_CONTROLLERS, GuiTestCase, test_port_name
from visual_control.effects import RGB_SHIFT_EFFECTS, SATURATION_EFFECTS, Effect

AKAI = "Akai MIDI Mix"
OXYGEN = "Oxygen"
INPUT_INDEX = {AKAI: 0, OXYGEN: 1}
# What each real controller sends for rotary encoders and sliders.
STATUS = {AKAI: 176, OXYGEN: 177}
CONTROLS = {controller.name: controller.effects for controller in TEST_CONTROLLERS}


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ControllerWindowTests(GuiTestCase):
    def status(self) -> str:
        return self.window._midi_status.text()

    def plug_in(self, name: str):
        port = mido.open_output(test_port_name(name), virtual=True)
        self.addCleanup(port.close)
        self.window._midi_inputs[INPUT_INDEX[name]].refresh()
        return port

    def send(self, port, name: str, control: int, value: int) -> None:
        port.send(mido.Message.from_bytes([STATUS[name], control, value]))
        QTest.qWait(200)

    def effects(self) -> tuple[float, float]:
        return self.window._view._blur, self.window._view._pixelate

    def test_status_lists_only_connected_controllers(self):
        self.assertEqual(self.status(), "No controllers connected")
        oxygen = self.plug_in(OXYGEN)
        self.assertEqual(self.status(), "Connected: Oxygen")
        self.plug_in(AKAI)
        self.assertEqual(self.status(), "Connected: Akai MIDI Mix, Oxygen")
        oxygen.close()
        QTest.qWait(100)
        self.window._midi_inputs[INPUT_INDEX[OXYGEN]].refresh()
        self.assertEqual(self.status(), "Connected: Akai MIDI Mix")

    def assert_rotary_encoders_drive_their_effects(self, name):
        port = self.plug_in(name)
        controls = CONTROLS[name]
        self.send(port, name, controls[Effect.BLUR], 127)
        self.assertEqual(self.effects(), (1.0, 0.0))
        self.send(port, name, controls[Effect.PIXELATE], 127)
        self.assertEqual(self.effects(), (1.0, 1.0))
        self.send(port, name, controls[Effect.BLUR], 0)
        self.assertEqual(self.effects(), (0.0, 1.0))

    def test_oxygen_rotary_encoders_drive_their_effects(self):
        self.assert_rotary_encoders_drive_their_effects(OXYGEN)

    def assert_sliders_drive_saturation(self, name):
        port = self.plug_in(name)
        view = self.window._view
        for band, effect in enumerate(SATURATION_EFFECTS):
            self.send(port, name, CONTROLS[name][effect], 0)
            expected = [1.0] * 6
            expected[band] = 0.0
            self.assertEqual(view._saturation, expected)
            self.send(port, name, CONTROLS[name][effect], 64)
            self.assertEqual(view._saturation, [1.0] * 6)

    def test_oxygen_sliders_drive_saturation(self):
        self.assert_sliders_drive_saturation(OXYGEN)

    def assert_rotary_encoders_drive_rgb_shift(self, name):
        port = self.plug_in(name)
        view = self.window._view
        for channel, effects in enumerate(RGB_SHIFT_EFFECTS):
            for axis, effect in enumerate(effects):
                self.send(port, name, CONTROLS[name][effect], 127)
                expected = [[0.0, 0.0] for _ in range(3)]
                expected[channel][axis] = 1.0
                self.assertEqual(view._rgb_shift, expected, effect.name)
                self.send(port, name, CONTROLS[name][effect], 64)
                self.assertEqual(view._rgb_shift, [[0.0, 0.0] for _ in range(3)])

    def test_oxygen_rotary_encoders_drive_rgb_shift(self):
        self.assert_rotary_encoders_drive_rgb_shift(OXYGEN)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ConfigErrorDisplayTests(GuiTestCase):
    config_errors = ["broken.yaml: unknown effect \"blurr\""]

    def test_config_errors_are_shown_and_the_app_still_runs(self):
        self.assertIn("broken.yaml", self.window._status.text())
        self.assertIn("broken.yaml", self.window._placeholder.text())
        self.assertEqual(len(self.window._midi_inputs), 2)


if __name__ == "__main__":
    unittest.main()
