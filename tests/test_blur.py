"""Checks the blur on the real GPU, so it needs a display. A window opens briefly."""

import math
import os
import unittest

import numpy as np
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase
from visual_control.effects import Effect
from visual_control.view import MAX_BLUR_SIGMA

SIZE = 400


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class BlurTests(GuiTestCase):
    def turn_rotary_encoder(self, amount: float) -> None:
        self.window._midi_inputs[0].effect_changed.emit(Effect.BLUR, amount)
        QTest.qWait(200)

    def edge_image(self, axis: int) -> np.ndarray:
        """Black on the first half and white on the second, along the given axis."""
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        if axis == 0:
            pixels[SIZE // 2 :] = 255
        else:
            pixels[:, SIZE // 2 :] = 255
        return pixels

    def assert_matches_gaussian(self, profile: np.ndarray) -> None:
        sigma = MAX_BLUR_SIGMA * len(profile)
        positions = np.arange(len(profile)) + 0.5 - len(profile) / 2
        expected = [255 * 0.5 * (1 + math.erf(x / (sigma * math.sqrt(2)))) for x in positions]
        self.assertLess(np.abs(profile - expected).max(), 4)

    def test_full_rotary_encoder_blurs_left_to_right_like_a_gaussian(self):
        self.show_image(self.edge_image(axis=1))
        self.turn_rotary_encoder(1.0)
        picture = self.picture()
        self.assert_matches_gaussian(picture[picture.shape[0] // 2, :, 0])

    def test_full_rotary_encoder_blurs_top_to_bottom_like_a_gaussian(self):
        self.show_image(self.edge_image(axis=0))
        self.turn_rotary_encoder(1.0)
        picture = self.picture()
        self.assert_matches_gaussian(picture[:, picture.shape[1] // 2, 0])

    def test_rotary_encoder_at_zero_restores_the_exact_picture(self):
        self.show_image(self.edge_image(axis=1))
        original = self.picture()
        self.turn_rotary_encoder(1.0)
        self.assertFalse(np.array_equal(self.picture(), original))
        self.turn_rotary_encoder(0.0)
        np.testing.assert_array_equal(self.picture(), original)

    def test_turning_further_blurs_more(self):
        self.show_image(self.edge_image(axis=1))
        widths = []
        for amount in (0.1, 0.5, 1.0):
            self.turn_rotary_encoder(amount)
            picture = self.picture()
            row = picture[picture.shape[0] // 2, :, 0]
            widths.append(int(((row > 5) & (row < 250)).sum()))
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])


if __name__ == "__main__":
    unittest.main()
