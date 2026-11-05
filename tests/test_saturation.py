"""Checks the per-color saturation on the real GPU, so it needs a display."""

import colorsys
import os
import unittest

import numpy as np

from tests.gui import GuiTestCase
from visual_control.effects import SATURATION_EFFECTS, Effect
from visual_control.view import MAX_SATURATION, saturation_from_slider

SWATCH = 80
# Partly saturated, so that there's room to boost them.
SWATCHES = {
    Effect.SATURATION_RED: (200, 90, 90),
    Effect.SATURATION_YELLOW: (200, 200, 90),
    Effect.SATURATION_GREEN: (90, 200, 90),
    Effect.SATURATION_CYAN: (90, 200, 200),
    Effect.SATURATION_BLUE: (90, 90, 200),
    Effect.SATURATION_MAGENTA: (200, 90, 200),
}
LUMA = np.array([0.2126, 0.7152, 0.0722])


def spread(color) -> float:
    return float(np.max(color) - np.min(color))


class SliderCurveTests(unittest.TestCase):
    def test_ends_of_the_slider(self):
        self.assertEqual(saturation_from_slider(0.0), 0.0)
        self.assertEqual(saturation_from_slider(1.0), MAX_SATURATION)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class SaturationTests(GuiTestCase):
    def show_swatches(self) -> None:
        pixels = np.zeros((SWATCH, SWATCH * len(SWATCHES), 3), np.uint8)
        for index, color in enumerate(SWATCHES.values()):
            pixels[:, index * SWATCH : (index + 1) * SWATCH] = color
        self.show_image(pixels)

    def swatch_colors(self) -> dict:
        picture = self.picture()
        height, width = picture.shape[:2]
        return {
            effect: picture[height // 2, int((index + 0.5) * width / len(SWATCHES))]
            for index, effect in enumerate(SWATCHES)
        }

    def assert_same(self, actual, expected, name=None) -> None:
        self.assertLessEqual(np.abs(np.asarray(actual) - np.asarray(expected)).max(), 2, name)

    def test_centered_sliders_leave_the_exact_picture(self):
        self.show_swatches()
        original = self.picture()
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 0.0)
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 64 / 127)
        np.testing.assert_array_equal(self.picture(), original)

    def test_slider_down_turns_only_its_own_color_grey(self):
        self.show_swatches()
        original = self.swatch_colors()
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 0.0)
            colors = self.swatch_colors()
            for other in SATURATION_EFFECTS:
                if other is effect:
                    self.assertLessEqual(spread(colors[other]), 2, other.name)
                    self.assertAlmostEqual(
                        colors[other].mean(), LUMA @ original[other], delta=3, msg="same brightness"
                    )
                else:
                    self.assert_same(colors[other], original[other], other.name)
            self.set_effect(effect, 0.5)

    def test_slider_up_makes_only_its_own_color_more_vivid_at_the_same_hue(self):
        self.show_swatches()
        original = self.swatch_colors()
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 1.0)
            colors = self.swatch_colors()
            for other in SATURATION_EFFECTS:
                if other is effect:
                    self.assertGreater(spread(colors[other]), spread(original[other]) + 20, other.name)
                    hue = colorsys.rgb_to_hsv(*(colors[other] / 255))[0]
                    original_hue = colorsys.rgb_to_hsv(*(original[other] / 255))[0]
                    self.assertAlmostEqual(hue, original_hue, delta=0.02, msg=other.name)
                else:
                    self.assert_same(colors[other], original[other], other.name)
            self.set_effect(effect, 0.5)

    def test_hue_between_two_bands_blends_their_effect(self):
        orange = np.full((40, 40, 3), (220, 155, 90), np.uint8)
        self.show_image(orange)
        original = self.picture()[20, 20]
        self.set_effect(Effect.SATURATION_RED, 0.0)
        reduced = self.picture()[20, 20]
        self.assertGreater(spread(reduced), 0.3 * spread(original), "should keep some color")
        self.assertLess(spread(reduced), 0.7 * spread(original), "should lose some color")

    def test_greys_black_and_white_are_untouched(self):
        pixels = np.zeros((40, 120, 3), np.uint8)
        pixels[:, 40:80] = 128
        pixels[:, 80:] = 255
        self.show_image(pixels)
        original = self.picture()
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 0.0)
        np.testing.assert_array_equal(self.picture(), original)
        for effect in SATURATION_EFFECTS:
            self.set_effect(effect, 1.0)
        np.testing.assert_array_equal(self.picture(), original)

    def test_runs_before_blur_so_a_removed_color_leaves_no_halo(self):
        pixels = np.zeros((200, 200, 3), np.uint8)
        pixels[:] = (0, 0, 255)
        pixels[50:150, 50:150] = (255, 0, 0)
        self.show_image(pixels)
        self.set_effect(Effect.SATURATION_RED, 0.0)
        self.set_effect(Effect.BLUR, 1.0)
        picture = self.picture()
        # The red square became dark grey, so red may never exceed that grey level.
        self.assertLessEqual(picture[:, :, 0].max(), 255 * LUMA[0] + 3)


if __name__ == "__main__":
    unittest.main()
