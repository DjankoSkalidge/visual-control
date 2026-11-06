"""Loading and saving the keyboard setup."""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt

from visual_control.controllers.config import ConfigError
from visual_control.effects import Effect
from visual_control.keyboard import (
    KEYBOARD_EFFECTS,
    can_assign,
    keyboard_file,
    load_keyboard,
    save_keyboard,
)

Q = Qt.Key.Key_Q.value
SPACE = Qt.Key.Key_Space.value
ONE = Qt.Key.Key_1.value
F5 = Qt.Key.Key_F5.value


class KeyboardFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "visual-control" / "keyboard.yaml"

    def write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def test_it_sits_next_to_the_controllers_folder(self):
        folder = Path("/config/visual-control/controllers")
        self.assertEqual(keyboard_file(folder), Path("/config/visual-control/keyboard.yaml"))

    def test_no_file_means_no_keys(self):
        self.assertEqual(load_keyboard(self.path), {})

    def test_an_empty_file_means_no_keys(self):
        self.write("")
        self.assertEqual(load_keyboard(self.path), {})

    def test_saved_keys_load_back(self):
        effects = {Effect.FLASH: SPACE, Effect.RIPPLE: Q, Effect.PAUSE: ONE, Effect.STUTTER: F5}
        save_keyboard(effects, self.path)
        self.assertEqual(load_keyboard(self.path), effects)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_the_file_is_readable_by_hand(self):
        save_keyboard({Effect.FLASH: SPACE, Effect.RIPPLE: Q}, self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("ripple: Q", text)
        self.assertIn("flash: Space", text)

    def test_hand_written_keys_load(self):
        self.write("effects:\n  flash: space\n  pause: 1\n  shake: F5\n")
        self.assertEqual(
            load_keyboard(self.path), {Effect.FLASH: SPACE, Effect.PAUSE: ONE, Effect.SHAKE: F5}
        )

    def test_only_press_effects_can_be_assigned(self):
        self.assertIn(Effect.PAUSE, KEYBOARD_EFFECTS)
        self.assertNotIn(Effect.BLUR, KEYBOARD_EFFECTS)
        self.write("effects:\n  blur: Q\n")
        with self.assertRaisesRegex(ConfigError, '"blur" isn\'t a press effect'):
            load_keyboard(self.path)

    def test_bad_keys_are_explained(self):
        for text in ("Ctrl+Q", "Q, W", "Esc", "Shift", "nonsense", "''", "true", "[Q]"):
            with self.subTest(text=text):
                self.write(f"effects:\n  flash: {text}\n")
                with self.assertRaisesRegex(ConfigError, '"flash" must be a single key'):
                    load_keyboard(self.path)

    def test_a_key_can_only_trigger_one_effect(self):
        self.write("effects:\n  flash: Q\n  shake: Q\n")
        with self.assertRaisesRegex(ConfigError, 'Q is assigned to both "flash" and "shake"'):
            load_keyboard(self.path)

    def test_a_file_without_effects_is_explained(self):
        self.write("effects: Q\n")
        with self.assertRaisesRegex(ConfigError, "keyboard.yaml"):
            load_keyboard(self.path)

    def test_escape_and_modifier_keys_cannot_be_assigned(self):
        self.assertFalse(can_assign(Qt.Key.Key_Escape.value))
        self.assertFalse(can_assign(Qt.Key.Key_Shift.value))
        self.assertTrue(can_assign(SPACE))
