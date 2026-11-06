"""The effects that play once per press, on the real GPU, so most of this needs a display."""

import os
import subprocess
import time
import unittest
from unittest import mock

import numpy as np
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase
from visual_control.effects import PRESS_EFFECTS, Effect
from visual_control.view import ANIMATIONS, STUTTER_FRAMES, STUTTER_SECONDS, STUTTER_STEP_SECONDS

SIZE = 400


def photo_like() -> np.ndarray:
    """Different everywhere: red runs left to right, green top to bottom, and blue is fine detail."""
    y, x = np.indices((SIZE, SIZE))
    return np.dstack([x * 255 // SIZE, y * 255 // SIZE, ((x // 6 + y // 6) % 2) * 255]).astype(np.uint8)


def grey_waves() -> np.ndarray:
    """No color at all, so any color that shows up came from the effect.

    The waves are wider than the largest split. With finer ones, the split colors would
    land on the next wave along and look like less of a split than they are.
    """
    y, x = np.indices((SIZE, SIZE))
    wave = np.abs(((x + y) % 320) - 160) * 255 // 160
    return wave[:, :, None].repeat(3, axis=2).astype(np.uint8)


def difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


class AssignmentTests(unittest.TestCase):
    def test_every_new_effect_responds_to_a_press(self):
        for effect in (*ANIMATIONS, Effect.STUTTER):
            self.assertIn(effect, PRESS_EFFECTS)


class HeldAnimationCase(GuiTestCase):
    """Holds an animation at chosen moments, so that timing can't affect the results."""

    def at(self, effect: Effect, progress: float) -> np.ndarray:
        view = self.window._view
        with mock.patch.object(
            view, "_animation_progress", lambda e: progress if e is effect else 0.0
        ):
            return self.picture()


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ZoomPunchTests(HeldAnimationCase):
    def test_starts_zoomed_in_and_eases_back_out(self):
        self.show_image(photo_like())
        original = self.picture()
        changes = [
            difference(self.at(Effect.ZOOM_PUNCH, p), original) for p in (0.01, 0.3, 0.6, 0.99)
        ]
        self.assertEqual(changes, sorted(changes, reverse=True))
        self.assertLess(changes[-1], 0.5)

    def test_the_edge_shows_what_was_further_in(self):
        self.show_image(photo_like())
        original = self.picture()
        zoomed = self.at(Effect.ZOOM_PUNCH, 0.01)
        self.assertGreater(zoomed[:, 0, 0].mean(), original[:, 0, 0].mean() + 10)
        self.assertLess(zoomed[:, -1, 0].mean(), original[:, -1, 0].mean() - 10)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class GlitchBurstTests(HeldAnimationCase):
    def test_only_some_rows_move(self):
        self.show_image(photo_like())
        original = self.picture()
        glitched = self.at(Effect.GLITCH_BURST, 0.1)
        # Red runs left to right, so it shows sideways movement in each row.
        moved = np.abs(glitched - original)[:, :, 0].mean(axis=1) > 5
        self.assertGreater(moved.mean(), 0.1)
        self.assertLess(moved.mean(), 0.9)

    def test_nothing_moves_up_or_down(self):
        y, _ = np.indices((SIZE, SIZE))
        self.show_image(np.dstack([y * 255 // SIZE] * 3).astype(np.uint8))
        original = self.picture()
        self.assertLess(difference(self.at(Effect.GLITCH_BURST, 0.1), original), 0.5)

    def test_the_pattern_changes_during_a_burst_and_between_bursts(self):
        self.show_image(photo_like())
        early = self.at(Effect.GLITCH_BURST, 0.1)
        self.assertGreater(difference(self.at(Effect.GLITCH_BURST, 0.5), early), 1)
        self.window._view._glitch_seed = 42.0
        self.assertGreater(difference(self.at(Effect.GLITCH_BURST, 0.1), early), 1)

    def test_presses_get_different_patterns(self):
        self.show_image(photo_like())
        view = self.window._view
        seeds = set()
        for _ in range(3):
            view.start_animation(Effect.GLITCH_BURST)
            seeds.add(view._glitch_seed)
        self.assertEqual(len(seeds), 3)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class FlashTests(HeldAnimationCase):
    def test_starts_white_and_fades_back(self):
        self.show_image(photo_like())
        original = self.picture()
        self.assertGreater(self.at(Effect.FLASH, 0.001).min(), 250)
        middle = self.at(Effect.FLASH, 0.5)
        self.assertGreater(middle.mean(), original.mean() + 10)
        self.assertLess(middle.mean(), 250)
        self.assertLess(difference(self.at(Effect.FLASH, 0.99), original), 0.5)

    def test_is_white_even_with_color_removed_and_black_and_white_on(self):
        self.show_image(photo_like())
        view = self.window._view
        view.toggle_black_and_white()
        view.toggle_channel(0)
        view.toggle_channel(1)
        view.toggle_channel(2)
        self.assertGreater(self.at(Effect.FLASH, 0.001).min(), 250)

    def test_leaves_the_black_bars_black(self):
        self.show_image(photo_like())
        view = self.window._view
        with mock.patch.object(
            view, "_animation_progress", lambda e: 0.001 if e is Effect.FLASH else 0.0
        ):
            image = view.grabFramebuffer()
        x, _, _, _ = view._letterbox()
        self.assertGreater(x, 0)
        self.assertEqual(image.pixelColor(0, image.height() // 2).lightness(), 0)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ShakeTests(HeldAnimationCase):
    def test_moves_the_picture_differently_over_time_and_settles(self):
        self.show_image(photo_like())
        original = self.picture()
        early = self.at(Effect.SHAKE, 0.05)
        self.assertGreater(difference(early, original), 1)
        self.assertGreater(difference(self.at(Effect.SHAKE, 0.15), early), 1)
        self.assertLess(difference(self.at(Effect.SHAKE, 0.99), original), 0.5)

    def test_never_runs_off_the_edge_of_the_picture(self):
        # Reading past an edge would repeat its last pixels, leaving flat streaks there,
        # so every row and column must still have detail right up to the edge. Red has
        # stripes across the picture and green has stripes down it, so each is always
        # visible in the direction it's measured.
        y, x = np.indices((SIZE, SIZE))
        stripes = np.dstack([(x // 6 % 2) * 255, (y // 6 % 2) * 255, np.zeros_like(x)])
        self.show_image(stripes.astype(np.uint8))
        strip = 20  # Wider than a pair of stripes on screen.
        for progress in np.linspace(0.001, 0.5, 12):
            shaken = self.at(Effect.SHAKE, float(progress))
            red, green = shaken[:, :, 0], shaken[:, :, 1]
            for name, edge, axis in (
                ("left", red[:, :strip], 1),
                ("right", red[:, -strip:], 1),
                ("top", green[:strip, :], 0),
                ("bottom", green[-strip:, :], 0),
            ):
                self.assertGreater(np.ptp(edge, axis=axis).min(), 50, (name, progress))


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class ColorShockwaveTests(HeldAnimationCase):
    def color_by_distance(self, picture: np.ndarray) -> np.ndarray:
        """How colorful each ring around the center is, where 1.0 is the distance to a corner."""
        height, width, _ = picture.shape
        y, x = np.indices((height, width))
        distance = np.hypot(x - width / 2, y - height / 2) / np.hypot(width / 2, height / 2)
        rings = np.minimum((distance * 20).astype(int), 19)
        color = np.abs(picture[:, :, 0] - picture[:, :, 2])
        return np.bincount(rings.ravel(), color.ravel(), 20) / np.bincount(rings.ravel(), minlength=20)

    def test_splits_colors_in_a_ring_that_travels_outward(self):
        self.show_image(grey_waves())
        peaks = [
            int(np.argmax(self.color_by_distance(self.at(Effect.COLOR_SHOCKWAVE, p))))
            for p in (0.2, 0.5, 0.8)
        ]
        self.assertEqual(peaks, sorted(set(peaks)))

    def test_ahead_of_the_ring_is_untouched(self):
        self.show_image(grey_waves())
        rings = self.color_by_distance(self.at(Effect.COLOR_SHOCKWAVE, 0.2))
        self.assertLess(rings[-3:].max(), 1)
        self.assertGreater(rings.max(), 20)

    def test_comes_back_together_at_the_end(self):
        self.show_image(grey_waves())
        original = self.picture()
        self.assertLess(difference(self.at(Effect.COLOR_SHOCKWAVE, 0.99), original), 2)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class MirrorBurstTests(HeldAnimationCase):
    def test_makes_the_picture_symmetrical_and_then_melts_back(self):
        self.show_image(photo_like())
        original = self.picture()
        mirrored = self.at(Effect.MIRROR_BURST, 0.25)
        turned = mirrored[::-1, ::-1]
        self.assertGreater(difference(original, original[::-1, ::-1]), 30)
        self.assertLess(difference(mirrored, turned), 15)
        self.assertLess(difference(self.at(Effect.MIRROR_BURST, 0.999), original), 0.5)

    def test_works_on_a_wide_picture_without_black_gaps(self):
        pixels = np.full((200, 800, 3), 200, dtype=np.uint8)
        self.show_image(pixels)
        self.assertGreater(self.at(Effect.MIRROR_BURST, 0.25).min(), 190)


def colorful() -> np.ndarray:
    """Strong, smooth colors, so hue changes show clearly: red left to right, blue top to bottom."""
    y, x = np.indices((SIZE, SIZE))
    return np.dstack([x * 255 // SIZE, np.full_like(x, 60), y * 255 // SIZE]).astype(np.uint8)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class InvertFlashTests(HeldAnimationCase):
    def test_starts_as_the_negative_and_fades_back(self):
        self.show_image(photo_like())
        original = self.picture()
        self.assertLess(difference(self.at(Effect.INVERT_FLASH, 0.001), 255 - original), 1.5)
        self.assertLess(difference(self.at(Effect.INVERT_FLASH, 0.99), original), 0.5)

    def test_inverts_after_black_and_white(self):
        self.show_image(photo_like())
        self.window._view.toggle_black_and_white()
        inverted = self.at(Effect.INVERT_FLASH, 0.001)
        self.assertLess(np.ptp(inverted, axis=2).max(), 2)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class StrobeSliceTests(HeldAnimationCase):
    def test_bands_move_in_opposite_directions_then_return(self):
        self.show_image(photo_like())
        original = self.picture()
        sliced = self.at(Effect.STROBE_SLICE, 0.01)
        height = sliced.shape[0]
        # Red runs left to right, so a band moved one way gets redder in the middle.
        middle = sliced.shape[1] // 2
        first = sliced[height // 16, middle, 0] - original[height // 16, middle, 0]
        second = sliced[3 * height // 16, middle, 0] - original[3 * height // 16, middle, 0]
        self.assertGreater(abs(first), 15)
        self.assertLess(first * second, 0)
        self.assertLess(difference(self.at(Effect.STROBE_SLICE, 0.99), original), 0.5)

    def test_nothing_moves_up_or_down(self):
        y, _ = np.indices((SIZE, SIZE))
        self.show_image(np.dstack([y * 255 // SIZE] * 3).astype(np.uint8))
        original = self.picture()
        self.assertLess(difference(self.at(Effect.STROBE_SLICE, 0.01), original), 0.5)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class KaleidoscopePopTests(HeldAnimationCase):
    def test_folds_into_a_symmetrical_pattern_and_unfolds(self):
        self.show_image(photo_like())
        original = self.picture()
        folded = self.at(Effect.KALEIDOSCOPE_POP, 0.4)
        self.assertGreater(difference(original, original[::-1, ::-1]), 30)
        self.assertLess(difference(folded, folded[::-1, ::-1]), 15)
        self.assertLess(difference(self.at(Effect.KALEIDOSCOPE_POP, 0.001), original), 0.5)
        self.assertLess(difference(self.at(Effect.KALEIDOSCOPE_POP, 0.999), original), 0.5)

    def test_differs_from_a_mirror_burst(self):
        self.show_image(photo_like())
        self.assertGreater(
            difference(self.at(Effect.KALEIDOSCOPE_POP, 0.4), self.at(Effect.MIRROR_BURST, 0.25)), 5
        )

    def test_works_on_a_wide_picture_without_black_gaps(self):
        self.show_image(np.full((200, 800, 3), 200, dtype=np.uint8))
        self.assertGreater(self.at(Effect.KALEIDOSCOPE_POP, 0.4).min(), 190)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class TunnelZoomTests(HeldAnimationCase):
    def test_puts_a_smaller_copy_in_the_middle_and_fades(self):
        # A white frame around a black picture: a smaller copy shows a white ring inside.
        pixels = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
        pixels[:20], pixels[-20:], pixels[:, :20], pixels[:, -20:] = 255, 255, 255, 255
        self.show_image(pixels)
        original = self.picture()
        tunnel = self.at(Effect.TUNNEL_ZOOM, 0.01)
        inside = slice(30, -30)
        self.assertLess(original[inside, inside].max(), 1)
        self.assertGreater(tunnel[inside, inside].max(), 100)
        self.assertLess(difference(self.at(Effect.TUNNEL_ZOOM, 0.999), original), 0.5)

    def test_the_copies_shrink_towards_the_center(self):
        pixels = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
        pixels[:20], pixels[-20:], pixels[:, :20], pixels[:, -20:] = 255, 255, 255, 255
        self.show_image(pixels)

        def first_ring(picture):
            row = picture[picture.shape[0] // 2, 30 : picture.shape[1] // 2, 0]
            return 30 + int(np.argmax(row > 50))

        self.assertGreater(first_ring(self.at(Effect.TUNNEL_ZOOM, 0.6)),
                           first_ring(self.at(Effect.TUNNEL_ZOOM, 0.01)))


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class VignettePulseTests(HeldAnimationCase):
    def test_darkens_the_edges_but_not_the_middle(self):
        self.show_image(np.full((SIZE, SIZE, 3), 200, dtype=np.uint8))
        darkened = self.at(Effect.VIGNETTE_PULSE, 0.001)
        height, width, _ = darkened.shape
        self.assertGreater(darkened[height // 2, width // 2].min(), 195)
        self.assertLess(darkened[2, 2].max(), 60)
        self.assertLess(difference(self.at(Effect.VIGNETTE_PULSE, 0.99), self.picture()), 0.5)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class SpinKickTests(HeldAnimationCase):
    def test_turns_one_way_then_the_other_and_settles(self):
        self.show_image(photo_like())
        original = self.picture()
        # Green runs top to bottom, so turning tilts it: the left and right edges differ.
        def tilt(picture):
            return picture[:, 5, 1].mean() - picture[:, -6, 1].mean()

        self.assertLess(abs(tilt(original)), 2)
        first, second = tilt(self.at(Effect.SPIN_KICK, 0.15)), tilt(self.at(Effect.SPIN_KICK, 0.5))
        self.assertGreater(abs(first), 5)
        self.assertLess(first * second, 0)
        self.assertLess(difference(self.at(Effect.SPIN_KICK, 0.999), original), 0.5)

    def test_never_shows_past_the_corners(self):
        # Reading past an edge repeats its last pixels. With a black border, any
        # reading past the edge would show black in the corners.
        pixels = np.full((200, 400, 3), 200, dtype=np.uint8)
        self.show_image(pixels)
        for progress in np.linspace(0.02, 0.6, 10):
            self.assertGreater(self.at(Effect.SPIN_KICK, float(progress)).min(), 190, progress)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class HueSpinTests(HeldAnimationCase):
    def test_changes_colors_and_comes_back_round(self):
        self.show_image(colorful())
        original = self.picture()
        self.assertGreater(difference(self.at(Effect.HUE_SPIN, 0.33), original), 30)
        self.assertLess(difference(self.at(Effect.HUE_SPIN, 0.999), original), 1.5)

    def test_leaves_greys_alone(self):
        self.show_image(grey_waves())
        original = self.picture()
        self.assertLess(difference(self.at(Effect.HUE_SPIN, 0.4), original), 1.5)

    def test_cannot_bring_back_a_removed_color(self):
        self.show_image(colorful())
        self.window._view.toggle_channel(0)
        self.assertLess(self.at(Effect.HUE_SPIN, 0.33)[:, :, 0].max(), 1)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class PressTests(GuiTestCase):
    def press(self, effect: Effect) -> None:
        self.window._midi_inputs[0].effect_changed.emit(effect, 1.0)

    def test_each_one_plays_and_returns_to_the_exact_picture(self):
        self.show_image(photo_like())
        before = self.picture()
        for effect, (_name, seconds) in ANIMATIONS.items():
            with self.subTest(effect=effect):
                self.press(effect)
                self.assertIn(effect, self.window._view._animations)
                QTest.qWait(round(seconds * 1000) + 300)
                self.assertNotIn(effect, self.window._view._animations)
                np.testing.assert_array_equal(self.picture(), before)

    def test_all_at_once_on_top_of_every_other_effect_still_returns(self):
        self.show_image(photo_like())
        self.set_effect(Effect.PIXELATE, 0.3)
        self.set_effect(Effect.BLUR, 0.3)
        before = self.picture()
        for effect in ANIMATIONS:
            self.press(effect)
        QTest.qWait(100)
        self.assertGreater(difference(self.picture(), before), 1)
        QTest.qWait(800)
        np.testing.assert_array_equal(self.picture(), before)
        self.assertEqual(self.window._status.text(), "image.png")

    def test_another_press_restarts_it(self):
        self.show_image(photo_like())
        for effect in ANIMATIONS:
            self.press(effect)
            first = self.window._view._animations[effect]
            time.sleep(0.002)
            self.press(effect)
            self.assertGreater(self.window._view._animations[effect], first)

    def test_with_nothing_loaded_nothing_happens(self):
        for effect in (*ANIMATIONS, Effect.STUTTER):
            self.press(effect)
        self.assertEqual(self.window._view._animations, {})
        self.assertIsNone(self.window._view._stutter_frames)

    def test_opening_the_setup_window_ends_them(self):
        self.show_image(photo_like())
        for effect in ANIMATIONS:
            self.press(effect)
        self.window.open_controller_config()
        self.addCleanup(self.window._config_dialog.reject)
        self.assertEqual(self.window._view._animations, {})


class FakeSource:
    """Hands out numbered one-pixel frames whenever a test says one is due."""

    error = None

    def __init__(self):
        self.due: list[np.ndarray] = []

    def next_frame(self, now):
        return self.due.pop(0) if self.due else None

    def toggle_pause(self, now):
        return True

    def set_speed(self, speed, now):
        pass

    def stop(self):
        pass


def numbered(number: int) -> np.ndarray:
    return np.full((1, 1, 3), number, dtype=np.uint8)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class StutterTests(GuiTestCase):
    """Runs the polling by hand on a pretend clock, so that timing can't affect the results."""

    def setUp(self):
        super().setUp()
        self.view = self.window._view
        self.view._timer.stop()
        self.source = FakeSource()
        self.view.set_source(self.source)
        self.now = 1000.0
        clock = mock.patch("visual_control.view.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def show_frames(self, first: int, last: int) -> None:
        for number in range(first, last + 1):
            self.source.due.append(numbered(number))
            self.view._poll()

    def shown(self) -> int | None:
        """What the last poll put up to be drawn, if anything."""
        pixels, self.view._new_pixels = self.view._new_pixels, None
        return None if pixels is None else int(pixels[0, 0, 0])

    def shown_after(self, seconds: float) -> int | None:
        self.now += seconds
        self.view._poll()
        return self.shown()

    def test_cycles_through_the_latest_frames(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        step = STUTTER_STEP_SECONDS
        shown = [self.shown_after(0.0 if i == 0 else step) for i in range(STUTTER_FRAMES + 2)]
        first = 20 - STUTTER_FRAMES + 1
        self.assertEqual(shown, [*range(first, 21), first, first + 1])

    def test_holds_each_frame_until_its_step_is_over(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.assertIsNotNone(self.shown_after(0.0))
        self.assertIsNone(self.shown_after(STUTTER_STEP_SECONDS / 4))

    def test_the_video_carries_on_underneath_and_comes_back_where_it_got_to(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.show_frames(21, 30)
        self.assertEqual(self.view._stutter_frames[0][0, 0, 0], 20 - STUTTER_FRAMES + 1)
        self.assertEqual(self.shown_after(STUTTER_SECONDS), 30)
        self.assertIsNone(self.view._stutter_frames)

    def test_frames_arriving_during_it_do_not_show(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.shown_after(0.0)
        self.now += STUTTER_STEP_SECONDS / 4
        self.source.due.append(numbered(21))
        self.view._poll()
        self.assertIsNone(self.shown())

    def test_a_paused_video_returns_to_its_frozen_frame(self):
        self.show_frames(1, 20)
        self.view.start_stutter()  # next_frame gives nothing, just as it does when paused.
        self.assertEqual(self.shown_after(0.0), 13)
        self.assertEqual(self.shown_after(STUTTER_SECONDS), 20)

    def test_another_press_repeats_what_has_played_since(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.show_frames(21, 40)
        self.now += 0.1
        self.view.start_stutter()
        self.assertEqual(self.shown_after(0.0), 40 - STUTTER_FRAMES + 1)

    def test_needs_at_least_two_frames(self):
        self.show_frames(1, 1)
        self.view.start_stutter()
        self.assertIsNone(self.view._stutter_frames)

    def test_turning_effects_off_returns_to_the_latest_frame(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.shown_after(0.0)
        self.view.reset_effects()
        self.assertIsNone(self.view._stutter_frames)
        self.assertEqual(self.shown(), 20)

    def test_a_new_file_forgets_the_old_frames(self):
        self.show_frames(1, 20)
        self.view.start_stutter()
        self.view.set_source(FakeSource())
        self.assertIsNone(self.view._stutter_frames)
        self.assertEqual(len(self.view._recent_frames), 0)
        self.view.start_stutter()
        self.assertIsNone(self.view._stutter_frames)

    def test_keeps_only_as_many_frames_as_it_repeats(self):
        self.show_frames(1, 100)
        self.assertEqual(len(self.view._recent_frames), STUTTER_FRAMES)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class StutterInRealPlaybackTests(GuiTestCase):
    def play_video(self) -> None:
        path = self.dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=854x480:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        # Stutter needs frames to repeat. A fixed wait was sometimes too short on
        # a busy machine, so wait until a few have been shown, for up to 5 s.
        for _ in range(100):
            if len(self.window._view._recent_frames) >= 4:
                break
            QTest.qWait(50)

    def test_stutters_then_plays_on(self):
        self.play_video()
        self.window._midi_inputs[0].effect_changed.emit(Effect.STUTTER, 1.0)
        self.assertIsNotNone(self.window._view._stutter_frames)
        QTest.qWait(round(STUTTER_SECONDS * 1000) + 200)
        self.assertIsNone(self.window._view._stutter_frames)
        frame = self.picture()
        QTest.qWait(300)
        self.assertFalse(np.array_equal(self.picture(), frame))

    def test_a_still_image_is_unaffected(self):
        self.show_image(photo_like())
        before = self.picture()
        self.window._midi_inputs[0].effect_changed.emit(Effect.STUTTER, 1.0)
        self.assertIsNone(self.window._view._stutter_frames)
        np.testing.assert_array_equal(self.picture(), before)


if __name__ == "__main__":
    unittest.main()
