"""Checks black and white on the real GPU, so it needs a display."""

import os
import unittest

import numpy as np

from tests.gui import GuiTestCase
from visual_control.effects import Effect


def color_bars() -> np.ndarray:
    """Vertical red, green, blue and white bars."""
    pixels = np.zeros((200, 400, 3), np.uint8)
    pixels[:, :100] = (255, 0, 0)
    pixels[:, 100:200] = (0, 255, 0)
    pixels[:, 200:300] = (0, 0, 255)
    pixels[:, 300:] = (255, 255, 255)
    return pixels


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class BlackAndWhiteTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.show_image(color_bars())
        self.original = self.picture()

    def press(self) -> None:
        self.set_effect(Effect.BLACK_AND_WHITE, 1.0)

    def assert_no_color(self, picture: np.ndarray) -> None:
        self.assertEqual(np.ptp(picture.astype(int), axis=2).max(), 0)

    def test_press_removes_all_color_and_keeps_brightness_order(self):
        self.press()
        picture = self.picture()
        self.assert_no_color(picture)
        height, width = picture.shape[:2]
        red, green, blue, white = (
            int(picture[height // 2, width * bar // 8, 0]) for bar in (1, 3, 5, 7)
        )
        self.assertLess(blue, red)
        self.assertLess(red, green)
        self.assertLess(green, white)
        self.assertEqual(white, 255)

    def test_second_press_restores_the_exact_picture(self):
        self.press()
        self.press()
        np.testing.assert_array_equal(self.picture(), self.original)

    def test_no_other_effect_can_bring_color_back(self):
        self.press()
        self.set_effect(Effect.RGB_SHIFT_RED_HORIZONTAL, 1.0)
        self.set_effect(Effect.SATURATION_RED, 1.0)
        self.set_effect(Effect.BLUR, 0.5)
        self.set_effect(Effect.PIXELATE, 0.5)
        self.assert_no_color(self.picture())

    def test_stays_on_when_another_file_loads(self):
        self.press()
        self.show_image(color_bars()[::-1, ::-1])
        self.assert_no_color(self.picture())


if __name__ == "__main__":
    unittest.main()
