"""The controller setup window, with real MIDI through a virtual port. Needs a display."""

import os
import unittest
from unittest import mock

import mido
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase, test_port_name
from visual_control.config_window import ControllerConfigDialog
from visual_control.controllers.config import load_controller
from visual_control.controllers.config import Note
from visual_control.effects import Effect

CONTROL_CHANGE = 176
NEW_DEVICE = "Visual Control New Device"


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ConfigWindowTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.device = mido.open_output(NEW_DEVICE, virtual=True)
        self.addCleanup(self.device.close)

    def open_dialog(self, device: str = NEW_DEVICE) -> ControllerConfigDialog:
        QTest.mouseClick(self.window._configure_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        dialog = self.window._config_dialog
        self.select_device(dialog, device)
        return dialog

    def select_device(self, dialog, device: str) -> None:
        index = dialog._device.findText(device, Qt.MatchFlag.MatchContains)
        self.assertGreaterEqual(index, 0, f"{device} isn't listed")
        dialog._device.setCurrentIndex(index)
        QTest.qWait(50)

    def move(self, control: int, value: int = 100, status: int = CONTROL_CHANGE, port=None) -> None:
        (port or self.device).send(mido.Message.from_bytes([status, control, value]))
        QTest.qWait(100)

    def assign(self, dialog, effect: Effect, control: int, port=None) -> None:
        QTest.mouseClick(dialog._assign_buttons[effect], Qt.MouseButton.LeftButton)
        self.move(control, port=port)

    def button_text(self, dialog, effect: Effect) -> str:
        return dialog._assign_buttons[effect].text()

    def saved_files(self) -> list:
        return sorted(self.user_folder.glob("*.yaml")) if self.user_folder.exists() else []

    def effects_are_off(self) -> bool:
        view = self.window._view
        return (view._blur, view._pixelate, view._saturation, view._rgb_shift) == (
            0.0, 0.0, [1.0] * 6, [[0.0, 0.0] for _ in range(3)],
        )

    # The button

    def test_button_sits_beside_fullscreen(self):
        self.assertEqual(self.window._configure_button.text(), "Configure new controller")
        self.assertTrue(self.window._configure_button.isVisible())
        self.assertLess(
            self.window._configure_button.x(), self.window._fullscreen_button.x()
        )

    def test_button_is_hidden_in_fullscreen_with_the_other_controls(self):
        self.window.toggle_fullscreen()
        QTest.qWait(300)
        self.assertFalse(self.window._configure_button.isVisible())
        self.window.toggle_fullscreen()
        QTest.qWait(300)

    # Effects while configuring

    def test_opening_turns_all_effects_off(self):
        view = self.window._view
        view.set_blur(1.0)
        view.set_pixelate(1.0)
        view.set_saturation(2, 0.0)
        view.set_rgb_shift(1, 1, 1.0)
        view._animations[Effect.RIPPLE] = 1.0
        view.toggle_black_and_white()
        view.toggle_channel(0)
        self.open_dialog().reject()
        self.assertTrue(self.effects_are_off())
        self.assertEqual(view._animations, {})
        self.assertFalse(view._black_and_white)
        self.assertEqual(view._channels, [1.0, 1.0, 1.0])

    def test_controls_do_not_change_effects_while_open(self):
        port = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(port.close)
        self.window._midi_inputs[1].refresh()
        self.open_dialog()
        self.move(22, 127, port=port)
        self.assertTrue(self.effects_are_off())

    def test_effects_stay_off_after_closing_until_a_control_moves(self):
        port = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(port.close)
        self.window._midi_inputs[1].refresh()
        self.window._view.set_blur(1.0)
        dialog = self.open_dialog()
        dialog.reject()
        QTest.qWait(100)
        self.assertTrue(self.effects_are_off())
        self.move(22, 127, port=port)
        self.assertEqual(self.window._view._blur, 1.0)
        self.assertEqual(self.window._view._pixelate, 0.0)

    # Assigning controls

    def test_lists_connected_devices_but_not_midi_through(self):
        dialog = self.open_dialog()
        names = [dialog._device.itemText(i) for i in range(dialog._device.count())]
        self.assertTrue(any(NEW_DEVICE in name for name in names))
        self.assertFalse(any("Midi Through" in name for name in names))

    def test_it_fits_on_a_1080p_screen_with_every_effect_reachable(self):
        dialog = self.open_dialog()
        self.assertLessEqual(dialog.frameGeometry().height(), 1080)
        self.assertTrue(dialog._save_button.isVisible())
        last = dialog._assign_buttons[list(Effect)[-1]]
        last.parent().parent().parent().ensureWidgetVisible(last)
        QTest.mouseClick(last, Qt.MouseButton.LeftButton)
        self.assertEqual(self.button_text(dialog, list(Effect)[-1]), "Move a control...")

    def test_new_device_starts_empty_with_its_name_filled_in(self):
        dialog = self.open_dialog()
        self.assertEqual(dialog._name.text(), dialog._device.currentText().split(":")[0])
        for effect in Effect:
            self.assertEqual(self.button_text(dialog, effect), "Not assigned")
        self.assertFalse(dialog._save_button.isEnabled())

    def test_moving_a_control_assigns_it_to_the_chosen_effect_only(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Move a control...")
        self.move(30)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 30")
        self.assertEqual(self.button_text(dialog, Effect.PIXELATE), "Not assigned")

    def test_a_stream_of_messages_only_assigns_the_first_control(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        self.move(30)
        self.move(31)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 30")

    def test_controls_are_ignored_when_no_effect_is_waiting(self):
        dialog = self.open_dialog()
        self.move(30)
        self.assertEqual(dialog._assignments, {})

    def test_a_note_on_a_position_effect_explains_and_keeps_listening(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        self.move(36, status=144)
        self.assertEqual(dialog._row_notes[Effect.BLUR].text(), "Needs a slider or rotary encoder")
        self.move(30)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 30")
        self.assertEqual(dialog._row_notes[Effect.BLUR].text(), "")

    def test_pause_can_be_assigned_a_note_or_a_control(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.PAUSE], Qt.MouseButton.LeftButton)
        self.move(36, status=144)
        self.assertEqual(self.button_text(dialog, Effect.PAUSE), "Note 36")
        self.assertEqual(dialog._assignments[Effect.PAUSE], Note(36))
        QTest.mouseClick(dialog._assign_buttons[Effect.PAUSE], Qt.MouseButton.LeftButton)
        self.move(96)
        self.assertEqual(self.button_text(dialog, Effect.PAUSE), "Control 96")

    def test_release_messages_do_not_assign_a_button(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.PAUSE], Qt.MouseButton.LeftButton)
        self.move(36, 0, status=128)
        self.move(36, 0, status=144)
        self.assertEqual(self.button_text(dialog, Effect.PAUSE), "Move a control...")

    def test_a_control_already_in_use_moves_with_a_note(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        self.assign(dialog, Effect.PIXELATE, 30)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Not assigned")
        self.assertEqual(self.button_text(dialog, Effect.PIXELATE), "Control 30")
        self.assertEqual(dialog._row_notes[Effect.PIXELATE].text(), "Moved from Blur")

    def test_reassigning_the_same_effect_to_its_control_shows_no_note(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        self.assign(dialog, Effect.BLUR, 30)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 30")
        self.assertEqual(dialog._row_notes[Effect.BLUR].text(), "")

    def test_clicking_again_cancels_listening_and_keeps_the_old_control(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        button = dialog._assign_buttons[Effect.BLUR]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.move(31)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 30")

    def test_escape_cancels_listening_before_closing_the_window(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertIsNone(dialog._listening_for)
        self.assertIs(self.window._config_dialog, dialog)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        QTest.qWait(50)
        self.assertIsNone(self.window._config_dialog)

    def test_clear_removes_an_assignment(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        QTest.mouseClick(dialog._clear_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Not assigned")
        self.assertFalse(dialog._save_button.isEnabled())

    def test_changing_device_starts_over(self):
        second = mido.open_output("Visual Control Second Device", virtual=True)
        self.addCleanup(second.close)
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        self.select_device(dialog, "Visual Control Second Device")
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Not assigned")
        self.move(40)  # From the old device, which is no longer listened to.
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        self.move(41)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Move a control...")
        self.move(42, port=second)
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 42")

    def test_device_plugged_in_while_open_appears(self):
        dialog = self.open_dialog()
        late = mido.open_output("Visual Control Late Device", virtual=True)
        self.addCleanup(late.close)
        dialog._refresh_devices()
        self.assertGreaterEqual(dialog._device.findText("Late Device", Qt.MatchFlag.MatchContains), 0)
        self.assertIn(NEW_DEVICE, dialog._device.currentText(), "selection should be kept")

    def test_selected_device_unplugged_while_open_starts_over(self):
        second = mido.open_output("Visual Control Second Device", virtual=True)
        dialog = self.open_dialog("Visual Control Second Device")
        self.assign(dialog, Effect.BLUR, 30)
        second.close()
        QTest.qWait(100)
        dialog._refresh_devices()
        self.assertNotIn("Second Device", dialog._device.currentText())
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Not assigned")

    # Saving

    def test_save_writes_a_file_and_the_new_setup_works_right_away(self):
        dialog = self.open_dialog()
        dialog._name.setText("My Device")
        self.assign(dialog, Effect.BLUR, 30)
        self.assign(dialog, Effect.PIXELATE, 31)
        QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
        QTest.qWait(200)

        self.assertIsNone(self.window._config_dialog)
        files = self.saved_files()
        self.assertEqual(len(files), 1)
        saved = load_controller(files[0])
        self.assertEqual(saved.name, "My Device")
        self.assertEqual(saved.effects, {Effect.BLUR: 30, Effect.PIXELATE: 31})
        self.assertEqual(self.window._midi_status.text(), "Connected: My Device")

        self.move(30, 127)
        self.assertEqual(self.window._view._blur, 1.0)
        self.assertEqual(self.window._view._pixelate, 0.0)

    def test_cancel_saves_nothing(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        QTest.mouseClick(dialog._assign_buttons[Effect.BLUR], Qt.MouseButton.LeftButton)
        dialog.reject()
        QTest.qWait(100)
        self.assertEqual(self.saved_files(), [])

    def test_blank_name_cannot_be_saved(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        self.assertTrue(dialog._save_button.isEnabled())
        dialog._name.setText("   ")
        self.assertFalse(dialog._save_button.isEnabled())

    def test_save_failure_is_shown_and_the_window_stays_open(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.BLUR, 30)
        self.dir.joinpath("blocked").write_text("a file where the folder should be")
        dialog._folder = self.dir / "blocked"
        QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        self.assertIs(self.window._config_dialog, dialog)
        self.assertIn("Couldn't save", dialog._error.text())

    # Replacing

    def test_device_with_a_setup_is_filled_in_and_noted(self):
        port = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(port.close)
        dialog = self.open_dialog(test_port_name("Oxygen"))
        self.assertEqual(dialog._name.text(), "Oxygen")
        self.assertEqual(self.button_text(dialog, Effect.BLUR), "Control 22")
        self.assertIn("Oxygen", dialog._device_note.text())

    def save_over_oxygen(self, confirm: bool, name: str = "Oxygen"):
        port = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(port.close)
        dialog = self.open_dialog(test_port_name("Oxygen"))
        dialog._name.setText(name)
        self.assign(dialog, Effect.BLUR, 99, port=port)
        with mock.patch.object(dialog, "_confirm_replace", return_value=confirm) as asked:
            QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
            QTest.qWait(200)
        return dialog, port, asked

    def test_declining_to_replace_keeps_the_window_open_and_saves_nothing(self):
        dialog, _, asked = self.save_over_oxygen(confirm=False)
        asked.assert_called_once_with(["Oxygen"])
        self.assertIs(self.window._config_dialog, dialog)
        self.assertEqual(self.saved_files(), [])

    def test_replacing_a_built_in_setup_takes_priority(self):
        _, port, _ = self.save_over_oxygen(confirm=True)
        self.assertEqual(len(self.saved_files()), 1)
        self.assertEqual(self.window._midi_status.text(), "Connected: Oxygen")
        self.move(99, 127, port=port)
        self.assertEqual(self.window._view._blur, 1.0)

    def test_a_new_name_for_the_same_device_still_replaces_so_both_cannot_fire(self):
        _, port, asked = self.save_over_oxygen(confirm=True, name="My Oxygen")
        asked.assert_called_once_with(["Oxygen"])
        self.assertEqual(self.window._midi_status.text(), "Connected: My Oxygen")
        self.move(22, 127, port=port)  # Blur's old control.
        self.assertEqual(self.window._view._blur, 0.0)
        self.move(99, 127, port=port)
        self.assertEqual(self.window._view._blur, 1.0)


if __name__ == "__main__":
    unittest.main()
