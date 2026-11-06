"""Assigning keys to press effects, and pressing them in a real window. Needs a display."""

import os
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.gui import GuiTestCase
from visual_control.effects import Effect
from visual_control.keyboard import load_keyboard
from visual_control.keyboard_window import LISTENING

Q = Qt.Key.Key_Q.value
SPACE = Qt.Key.Key_Space.value


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class KeyboardWindowTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.keyboard_path = self.dir / "keyboard.yaml"
        self.triggered = []
        for effect in (Effect.FLASH, Effect.RIPPLE, Effect.SHAKE):
            self.window._effect_actions[effect] = lambda amount, e=effect: self.triggered.append(e)

    def open_dialog(self):
        QTest.mouseClick(self.window._keyboard_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        return self.window._keyboard_dialog

    def assign(self, dialog, effect: Effect, key) -> None:
        QTest.mouseClick(dialog._assign_buttons[effect], Qt.MouseButton.LeftButton)
        # The button that was clicked has focus, so it would use Space itself.
        QTest.keyClick(dialog._assign_buttons[effect], key)
        QTest.qWait(20)

    def save(self, dialog) -> None:
        QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
        QTest.qWait(50)

    def press(self, key, modifier=Qt.KeyboardModifier.NoModifier, widget=None) -> None:
        QTest.keyClick(widget or self.window._fullscreen_button, key, modifier)
        QTest.qWait(20)

    def set_up_keys(self) -> None:
        dialog = self.open_dialog()
        self.assign(dialog, Effect.FLASH, Qt.Key.Key_Space)
        self.assign(dialog, Effect.RIPPLE, Qt.Key.Key_Q)
        self.save(dialog)

    # The button

    def test_button_sits_below_configure_new_controller(self):
        button = self.window._keyboard_button
        configure = self.window._configure_button
        self.assertEqual(button.text(), "Configure keyboard")
        self.assertTrue(button.isVisible())
        self.assertEqual(button.mapToGlobal(button.rect().topLeft()).x(),
                         configure.mapToGlobal(configure.rect().topLeft()).x())
        self.assertGreater(button.y(), configure.y())

    def test_it_lists_only_press_effects(self):
        dialog = self.open_dialog()
        self.assertTrue(dialog.isVisible())
        self.assertIn(Effect.PAUSE, dialog._assign_buttons)
        self.assertIn(Effect.FLASH, dialog._assign_buttons)
        self.assertNotIn(Effect.BLUR, dialog._assign_buttons)
        self.assertNotIn(Effect.PLAYBACK_SPEED, dialog._assign_buttons)

    def test_effects_are_in_two_columns_that_fit_on_a_1080p_screen(self):
        dialog = self.open_dialog()
        buttons = dialog._assign_buttons
        lefts = {button.x() for button in buttons.values()}
        self.assertEqual(len(lefts), 2)
        self.assertLessEqual(dialog.frameGeometry().height(), 1080)
        self.assertLessEqual(dialog.frameGeometry().width(), 1920)

    # Assigning keys

    def test_clicking_then_pressing_a_key_assigns_it(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.FLASH], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog._assign_buttons[Effect.FLASH].text(), LISTENING)
        QTest.keyClick(dialog._assign_buttons[Effect.FLASH], Qt.Key.Key_Space)
        self.assertEqual(dialog._assign_buttons[Effect.FLASH].text(), "Space")
        self.assertEqual(dialog.assignments(), {Effect.FLASH: SPACE})

    def test_keys_are_ignored_when_no_effect_is_waiting(self):
        dialog = self.open_dialog()
        QTest.keyClick(dialog, Qt.Key.Key_Q)
        self.assertEqual(dialog.assignments(), {})

    def test_a_key_already_in_use_moves_with_a_note(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.FLASH, Qt.Key.Key_Q)
        self.assign(dialog, Effect.SHAKE, Qt.Key.Key_Q)
        self.assertEqual(dialog.assignments(), {Effect.SHAKE: Q})
        self.assertEqual(dialog._row_notes[Effect.SHAKE].text(), "Moved from Flash")

    def test_modifier_keys_and_shortcuts_keep_it_listening(self):
        dialog = self.open_dialog()
        button = dialog._assign_buttons[Effect.FLASH]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.keyClick(button, Qt.Key.Key_Shift)
        QTest.keyClick(button, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(button.text(), LISTENING)
        self.assertEqual(dialog.assignments(), {})

    def test_escape_cancels_listening_before_closing_the_window(self):
        dialog = self.open_dialog()
        QTest.mouseClick(dialog._assign_buttons[Effect.FLASH], Qt.MouseButton.LeftButton)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog._assign_buttons[Effect.FLASH].text(), "Not assigned")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        QTest.qWait(50)
        self.assertIsNone(self.window._keyboard_dialog)

    def test_clear_removes_an_assignment(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.FLASH, Qt.Key.Key_Q)
        QTest.mouseClick(dialog._clear_buttons[Effect.FLASH], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.assignments(), {})
        self.assertFalse(dialog._clear_buttons[Effect.FLASH].isEnabled())

    # Saving

    def test_save_writes_the_file_and_the_keys_work_right_away(self):
        self.set_up_keys()
        self.assertIsNone(self.window._keyboard_dialog)
        self.assertEqual(load_keyboard(self.keyboard_path), {Effect.FLASH: SPACE, Effect.RIPPLE: Q})
        self.press(Qt.Key.Key_Space)
        self.press(Qt.Key.Key_Q)
        self.assertEqual(self.triggered, [Effect.FLASH, Effect.RIPPLE])

    def test_cancel_saves_nothing(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.FLASH, Qt.Key.Key_Q)
        dialog.reject()
        QTest.qWait(50)
        self.assertFalse(self.keyboard_path.exists())
        self.press(Qt.Key.Key_Q)
        self.assertEqual(self.triggered, [])

    def test_reopening_shows_the_saved_keys(self):
        self.set_up_keys()
        dialog = self.open_dialog()
        self.assertEqual(dialog._assign_buttons[Effect.RIPPLE].text(), "Q")
        self.assertEqual(dialog.assignments(), {Effect.FLASH: SPACE, Effect.RIPPLE: Q})

    def test_save_failure_is_shown_and_the_window_stays_open(self):
        dialog = self.open_dialog()
        self.assign(dialog, Effect.FLASH, Qt.Key.Key_Q)
        with mock.patch("visual_control.keyboard_window.save_keyboard", side_effect=OSError("disk full")):
            self.save(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertIn("disk full", dialog._error.text())

    def test_saved_keys_load_when_the_app_starts(self):
        self.keyboard_path.write_text("effects:\n  shake: S\n", encoding="utf-8")
        self.window._load_keyboard()
        self.press(Qt.Key.Key_S)
        self.assertEqual(self.triggered, [Effect.SHAKE])

    def test_a_broken_file_is_named_in_the_status_bar(self):
        self.keyboard_path.write_text("effects:\n  shake: Ctrl+S\n", encoding="utf-8")
        self.window._load_keyboard()
        self.assertIn("keyboard.yaml", self.window._status.text())

    # Pressing keys

    def test_holding_a_key_down_triggers_once(self):
        self.set_up_keys()
        button = self.window._fullscreen_button
        for repeat in (False, True, True):
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Q, Qt.KeyboardModifier.NoModifier,
                              "q", repeat)
            QApplication.sendEvent(button, event)
        self.assertEqual(self.triggered, [Effect.RIPPLE])

    def test_a_key_does_not_also_press_the_focused_button(self):
        self.set_up_keys()
        self.window._fullscreen_button.setFocus()
        self.press(Qt.Key.Key_Space)
        QTest.qWait(200)
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.triggered, [Effect.FLASH])

    def test_keys_held_with_ctrl_do_nothing(self):
        self.set_up_keys()
        self.press(Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.triggered, [])

    def test_unassigned_keys_do_nothing(self):
        self.set_up_keys()
        self.press(Qt.Key.Key_W)
        self.assertEqual(self.triggered, [])

    def test_keys_do_nothing_while_a_setup_window_is_open(self):
        self.set_up_keys()
        self.open_dialog()
        self.press(Qt.Key.Key_Q, widget=self.window)
        self.window.open_controller_config()
        QTest.qWait(100)
        self.press(Qt.Key.Key_Q, widget=self.window)
        self.window._config_dialog.reject()
        QTest.qWait(50)
        self.assertEqual(self.triggered, [])
