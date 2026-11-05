"""Checks removing color channels on the real GPU, so it needs a display."""

import os
import unittest

import numpy as np

from tests.gui import GuiTestCase
from visual_control.effects import REMOVE_CHANNEL_EFFECTS, Effect


def all_colors() -> np.ndarray:
    """Different amounts of every channel, so that a mixed-up channel would show."""
    y, x = np.indices((200, 400))
    return np.stack([x * 255 // 399, y * 255 // 199, 255 - x * 255 // 399], axis=2).astype(np.uint8)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class RemoveChannelTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.show_image(all_colors())
        self.original = self.picture()

    def press(self, channel: int) -> None:
        self.set_effect(REMOVE_CHANNEL_EFFECTS[channel], 1.0)

    def test_press_removes_only_its_own_channel(self):
        for channel in range(3):
            with self.subTest(channel=channel):
                self.press(channel)
                expected = self.original.copy()
                expected[:, :, channel] = 0
                np.testing.assert_array_equal(self.picture(), expected)
                self.press(channel)

    def test_second_press_restores_the_exact_picture(self):
        for channel in range(3):
            self.press(channel)
            self.press(channel)
        np.testing.assert_array_equal(self.picture(), self.original)

    def test_channels_are_independent(self):
        self.press(0)
        self.press(2)
        self.press(0)
        expected = self.original.copy()
        expected[:, :, 2] = 0
        np.testing.assert_array_equal(self.picture(), expected)

    def test_removing_all_three_leaves_black(self):
        for channel in range(3):
            self.press(channel)
        self.assertEqual(self.picture().max(), 0)

    def test_black_and_white_stays_grey_and_uses_the_remaining_channels(self):
        self.set_effect(Effect.BLACK_AND_WHITE, 1.0)
        grey = self.picture()
        self.press(1)
        picture = self.picture()
        self.assertEqual(np.ptp(picture.astype(int), axis=2).max(), 0)
        self.assertLess(picture.astype(int).sum(), grey.astype(int).sum())


if __name__ == "__main__":
    unittest.main()
