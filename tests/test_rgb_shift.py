"""Checks the RGB shift on the real GPU, so it needs a display."""

import os
import unittest

import numpy as np

from tests.gui import GuiTestCase
from visual_control.effects import RGB_SHIFT_EFFECTS, Effect
from visual_control.view import MAX_RGB_SHIFT, centered

SIZE = 400
LARGEST = round(MAX_RGB_SHIFT * SIZE)
CHANNELS = {0: "red", 1: "green", 2: "blue"}
HORIZONTAL, VERTICAL = 0, 1
LEFT_OR_DOWN, RIGHT_OR_UP = 0.0, 1.0


class CenteredTests(unittest.TestCase):
    def test_ends(self):
        self.assertEqual(centered(0.0), -1.0)
        self.assertEqual(centered(1.0), 1.0)

    def test_middle_values_are_all_zero(self):
        for value in range(60, 68):
            self.assertEqual(centered(value / 127), 0.0, value)

    def test_rises_steadily_without_jumps(self):
        positions = [centered(value / 127) for value in range(128)]
        steps = np.diff(positions)
        self.assertTrue((steps >= 0).all())
        self.assertLess(steps.max(), 0.03)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class RgbShiftTests(GuiTestCase):
    def show_white_square(self) -> None:
        """White in the middle of black, so each channel has edges that can be measured."""
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        pixels[100:300, 100:300] = 255
        self.show_image(pixels)

    def square_position(self, channel: int) -> tuple[float, float]:
        """Where one channel's square starts: from the left, and from the top, in media pixels."""
        picture = self.picture()[:, :, channel] > 128
        height, width = picture.shape
        left = np.argmax(picture[height // 2]) * SIZE / width
        top = np.argmax(picture[:, width // 2]) * SIZE / height
        return left, top

    def assert_square_at(self, channel: int, left: float, top: float) -> None:
        actual_left, actual_top = self.square_position(channel)
        self.assertAlmostEqual(actual_left, left, delta=2, msg=f"{CHANNELS[channel]} left")
        self.assertAlmostEqual(actual_top, top, delta=2, msg=f"{CHANNELS[channel]} top")

    def check_each_control(self, axis: int, position: float, left: float, top: float) -> None:
        self.show_white_square()
        for channel, effects in enumerate(RGB_SHIFT_EFFECTS):
            self.set_effect(effects[axis], position)
            for other in CHANNELS:
                if other == channel:
                    self.assert_square_at(other, left, top)
                else:
                    self.assert_square_at(other, 100, 100)
            self.set_effect(effects[axis], 0.5)

    def test_turning_up_shifts_only_that_channel_right(self):
        self.check_each_control(HORIZONTAL, RIGHT_OR_UP, 100 + LARGEST, 100)

    def test_turning_down_shifts_only_that_channel_left(self):
        self.check_each_control(HORIZONTAL, LEFT_OR_DOWN, 100 - LARGEST, 100)

    def test_turning_up_shifts_only_that_channel_up(self):
        self.check_each_control(VERTICAL, RIGHT_OR_UP, 100, 100 - LARGEST)

    def test_turning_down_shifts_only_that_channel_down(self):
        self.check_each_control(VERTICAL, LEFT_OR_DOWN, 100, 100 + LARGEST)

    def test_both_directions_of_one_channel_combine(self):
        self.show_white_square()
        self.set_effect(Effect.RGB_SHIFT_RED_HORIZONTAL, RIGHT_OR_UP)
        self.set_effect(Effect.RGB_SHIFT_RED_VERTICAL, LEFT_OR_DOWN)
        self.assert_square_at(0, 100 + LARGEST, 100 + LARGEST)

    def test_centered_controls_restore_the_exact_picture(self):
        self.show_white_square()
        original = self.picture()
        for effects in RGB_SHIFT_EFFECTS:
            for effect in effects:
                self.set_effect(effect, 1.0)
        self.assertFalse(np.array_equal(self.picture(), original))
        for effects in RGB_SHIFT_EFFECTS:
            for effect in effects:
                self.set_effect(effect, 64 / 127)
        np.testing.assert_array_equal(self.picture(), original)

    def test_what_slides_off_one_edge_comes_back_on_the_other(self):
        pixels = np.zeros((SIZE, SIZE, 3), np.uint8)
        pixels[:, SIZE - 20 :] = 255  # A stripe touching the right edge.
        self.show_image(pixels)
        self.set_effect(Effect.RGB_SHIFT_RED_HORIZONTAL, RIGHT_OR_UP)
        picture = self.picture()
        row = picture[picture.shape[0] // 2, :, 0] > 128
        scale = len(row) / SIZE
        # The stripe's 20 pixels now sit just before the shift distance from the left edge.
        self.assertFalse(row[: int((LARGEST - 22) * scale)].any(), "gap before the stripe")
        self.assertTrue(
            row[int((LARGEST - 18) * scale) : int((LARGEST - 2) * scale)].all(),
            "the stripe wrapped around to the left side",
        )
        self.assertFalse(row[int((LARGEST + 2) * scale) :].any(), "nothing after the stripe")

    def test_shifted_picture_stays_sharp(self):
        self.show_white_square()
        self.set_effect(Effect.RGB_SHIFT_RED_HORIZONTAL, 0.8)
        picture = self.picture()
        row = picture[picture.shape[0] // 2, :, 0]
        # The picture is scaled up for the window, so its edges are slightly soft anyway.
        soft_pixels = int(((row > 5) & (row < 250)).sum())
        self.assertLessEqual(soft_pixels, 8)

    def test_runs_before_blur_and_pixelate(self):
        self.show_white_square()
        self.set_effect(Effect.RGB_SHIFT_RED_HORIZONTAL, RIGHT_OR_UP)
        self.set_effect(Effect.PIXELATE, 1.0)
        picture = self.picture()
        rows = picture[picture.shape[0] // 2]
        steps = (np.abs(np.diff(rows[:, 0])) > 1).sum()
        self.assertLessEqual(int(steps), SIZE // LARGEST, "blocks stay crisp and aligned")
        self.assertGreater(np.abs(rows[:, 0] - rows[:, 1]).max(), 50, "the shift still shows")


if __name__ == "__main__":
    unittest.main()
