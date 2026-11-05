"""Checks the ripple on the real GPU, so it needs a display."""

import math
import os
import time
import unittest
from unittest import mock

import numpy as np
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase
from visual_control.effects import Effect

SIZE = 400


def grid() -> np.ndarray:
    """Fine detail everywhere, so that any bending shows up as a change."""
    y, x = np.indices((SIZE, SIZE))
    return (((x // 6 + y // 6) % 2 * 255)[:, :, None].repeat(3, axis=2)).astype(np.uint8)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class RippleShapeTests(GuiTestCase):
    """Holds the ripple at chosen moments, so that timing can't affect the results."""

    def setUp(self):
        super().setUp()
        self.show_image(grid())
        self.original = self.picture()

    def changes_at(self, progress: float) -> np.ndarray:
        view = self.window._view
        with mock.patch.object(view, "_animation_progress", lambda effect: progress if effect is Effect.RIPPLE else 0.0):
            return np.abs(self.picture() - self.original).sum(axis=2)

    def change_by_distance(self, changes: np.ndarray) -> np.ndarray:
        """Average change in rings around the center, where 1.0 is the distance to a corner."""
        height, width = changes.shape
        y, x = np.indices(changes.shape)
        distance = np.hypot(x - width / 2, y - height / 2) / math.hypot(width / 2, height / 2)
        rings = np.minimum((distance * 40).astype(int), 39)
        return np.bincount(rings.ravel(), changes.ravel(), 40) / np.bincount(rings.ravel(), minlength=40)

    def test_front_travels_outward_from_the_center(self):
        peaks = [
            int(np.argmax(self.change_by_distance(self.changes_at(progress))))
            for progress in (0.2, 0.4, 0.6, 0.8)
        ]
        self.assertEqual(peaks, sorted(peaks))
        for progress, peak in zip((0.2, 0.4, 0.6, 0.8), peaks):
            self.assertAlmostEqual(peak / 40, progress, delta=0.15)

    def test_ahead_of_and_far_behind_the_front_looks_untouched(self):
        rings = self.change_by_distance(self.changes_at(0.5))
        # The wave's tail never quite reaches zero, but this is far too small to see.
        self.assertLess(rings[:3].max(), 2, "center, long after the front has passed")
        self.assertLess(rings[-3:].max(), 2, "corners, which the front hasn't reached")
        self.assertGreater(rings[16:24].max(), 50, "around the front")

    def test_reaches_the_edges_and_corners(self):
        changes = self.changes_at(0.95)
        height, width = changes.shape
        corner = changes[: height // 12, : width // 12].mean()
        self.assertGreater(corner, 5)

    def test_spreads_evenly_in_all_directions(self):
        changes = self.changes_at(0.5)
        height, width = changes.shape
        y, x = np.indices(changes.shape)
        total = changes.sum()
        self.assertAlmostEqual((x * changes).sum() / total, width / 2, delta=width * 0.02)
        self.assertAlmostEqual((y * changes).sum() / total, height / 2, delta=height * 0.02)

    def test_fades_out_towards_the_end(self):
        early = self.change_by_distance(self.changes_at(0.3)).max()
        late = self.change_by_distance(self.changes_at(0.97)).max()
        self.assertLess(late, early)

    def test_bends_blocks_when_pixelating(self):
        self.set_effect(Effect.PIXELATE, 0.5)
        pixelated = self.picture()
        view = self.window._view
        with mock.patch.object(view, "_animation_progress", lambda effect: 0.5 if effect is Effect.RIPPLE else 0.0):
            rippled = self.picture()
        self.assertFalse(np.array_equal(rippled, pixelated))


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class RipplePressTests(GuiTestCase):
    def press(self) -> None:
        self.window._midi_inputs[0].effect_changed.emit(Effect.RIPPLE, 1.0)

    def check_ripples_and_ends(self, before: np.ndarray) -> None:
        """Press, see it change during the half second, and see the exact picture after."""
        self.press()
        started = time.monotonic()
        QTest.qWait(120)
        during = self.picture()
        if time.monotonic() - started < 0.45:
            self.assertFalse(np.array_equal(during, before))
        QTest.qWait(600)
        self.assertNotIn(Effect.RIPPLE, self.window._view._animations)
        np.testing.assert_array_equal(self.picture(), before)

    def test_ripples_an_image_and_returns_to_the_exact_picture(self):
        self.show_image(grid())
        self.check_ripples_and_ends(self.picture())

    def test_ripples_a_paused_video(self):
        path = self.dir / "clip.gif"
        frames = [grid(), 255 - grid()]
        from PIL import Image

        images = [Image.fromarray(frame) for frame in frames]
        images[0].save(path, save_all=True, append_images=images[1:], duration=100)
        self.window.load(str(path))
        QTest.qWait(250)
        self.set_effect(Effect.PAUSE, 1.0)
        self.check_ripples_and_ends(self.picture())
        self.assertEqual(self.window._status.text(), "clip.gif (paused)")

    def test_the_window_repaints_during_a_ripple(self):
        self.show_image(grid())
        view = self.window._view
        original_render = view._render
        paints = []
        with mock.patch.object(view, "_render", lambda: (paints.append(1), original_render())):
            self.press()
            QTest.qWait(400)
        self.assertGreater(len(paints), 5)

    def test_another_press_restarts_it(self):
        self.show_image(grid())
        self.press()
        first = self.window._view._animations[Effect.RIPPLE]
        QTest.qWait(50)
        self.press()
        self.assertGreater(self.window._view._animations[Effect.RIPPLE], first)

    def test_pressing_with_nothing_loaded_does_nothing(self):
        self.press()
        self.assertNotIn(Effect.RIPPLE, self.window._view._animations)


if __name__ == "__main__":
    unittest.main()
