"""Checks the pixelation on the real GPU, so it needs a display."""

import os
import unittest

import numpy as np

from tests.gui import GuiTestCase
from visual_control.effects import Effect
from visual_control.view import MAX_PIXEL_SIZE

SIZE = 400
BLOCK = round(MAX_PIXEL_SIZE * SIZE)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class PixelateTests(GuiTestCase):
    def gradient(self, axis: int) -> np.ndarray:
        """Brightness rising from 0 to 255 along the given axis."""
        ramp = np.linspace(0, 255, SIZE).astype(np.uint8)
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        if axis == 0:
            pixels[:] = ramp[:, None, None]
        else:
            pixels[:] = ramp[None, :, None]
        return pixels

    def expected_blocks(self, length: int) -> np.ndarray:
        """The average brightness of the block each displayed pixel falls in."""
        position = (np.arange(length) + 0.5) * SIZE / length
        block = np.floor(position / BLOCK)
        return (block + 0.5) * BLOCK * 255 / SIZE

    def test_full_rotary_encoder_makes_averaged_blocks_left_to_right(self):
        self.show_image(self.gradient(axis=1))
        self.set_effect(Effect.PIXELATE, 1.0)
        row = self.picture()[100, :, 0]
        self.assertLess(np.abs(row - self.expected_blocks(len(row))).max(), 4)

    def test_full_rotary_encoder_makes_averaged_blocks_top_to_bottom(self):
        self.show_image(self.gradient(axis=0))
        self.set_effect(Effect.PIXELATE, 1.0)
        column = self.picture()[:, 100, 0]
        self.assertLess(np.abs(column - self.expected_blocks(len(column))).max(), 4)

    def test_fine_detail_averages_instead_of_flickering(self):
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        pixels[(np.indices((SIZE, SIZE)).sum(axis=0) % 2) == 0] = 255
        self.show_image(pixels)
        self.set_effect(Effect.PIXELATE, 1.0)
        self.assertLess(np.abs(self.picture() - 127.5).max(), 25)

    def test_turning_further_makes_bigger_blocks(self):
        self.show_image(self.gradient(axis=1))
        levels = []
        for amount in (0.2, 0.5, 1.0):
            self.set_effect(Effect.PIXELATE, amount)
            levels.append(len(np.unique(self.picture()[100, :, 0])))
        self.assertGreater(levels[0], levels[1])
        self.assertGreater(levels[1], levels[2])

    def test_smallest_step_is_still_visible(self):
        self.show_image(self.gradient(axis=1))
        original = self.picture()
        self.set_effect(Effect.PIXELATE, 1 / 127)
        self.assertFalse(np.array_equal(self.picture(), original))

    def test_rotary_encoder_at_zero_restores_the_exact_picture(self):
        self.show_image(self.gradient(axis=1))
        original = self.picture()
        self.set_effect(Effect.PIXELATE, 1.0)
        self.assertFalse(np.array_equal(self.picture(), original))
        self.set_effect(Effect.PIXELATE, 0.0)
        np.testing.assert_array_equal(self.picture(), original)

    def test_blocks_stay_crisp_with_blur_on_top(self):
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        pixels[:, SIZE // 2 :] = 255
        self.show_image(pixels)
        self.set_effect(Effect.BLUR, 1.0)
        self.set_effect(Effect.PIXELATE, 1.0)
        row = self.picture()[100, :, 0]
        steps = np.abs(np.diff(row))
        self.assertLessEqual(int((steps > 1).sum()), SIZE // BLOCK - 1)
        self.assertGreater(len(np.unique(row)), 2, "the blur should still show in the blocks")


if __name__ == "__main__":
    unittest.main()
