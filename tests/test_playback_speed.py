"""Playback speed: the control's mapping, the clock, and the whole app. The last needs a display."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import mido
import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase, test_port_name
from visual_control.controllers.config import ConfigError, load_controller
from visual_control.effects import Effect
from visual_control.media import VideoSource, _TimedFrame
from visual_control.view import playback_speed_from_control


def speed_at(value: int) -> float:
    return playback_speed_from_control(value / 127)


class ControlMappingTests(unittest.TestCase):
    def test_bottom_is_a_quarter_speed(self):
        self.assertAlmostEqual(speed_at(0), 0.25)

    def test_top_is_four_times_speed(self):
        self.assertAlmostEqual(speed_at(127), 4.0)

    def test_values_60_to_67_are_exactly_normal_speed(self):
        for value in range(60, 68):
            self.assertEqual(speed_at(value), 1.0, value)

    def test_just_outside_the_center_is_not_normal_but_is_close(self):
        self.assertLess(speed_at(59), 1.0)
        self.assertGreater(speed_at(59), 0.95)
        self.assertGreater(speed_at(68), 1.0)
        self.assertLess(speed_at(68), 1.05)

    def test_every_step_up_is_at_least_as_fast(self):
        speeds = [speed_at(value) for value in range(128)]
        self.assertEqual(speeds, sorted(speeds))

    def test_halfway_out_is_half_and_double_speed(self):
        self.assertAlmostEqual(speed_at(30), 0.5, places=1)
        self.assertAlmostEqual(speed_at(97), 2.0, places=1)


class ClockTests(unittest.TestCase):
    """Frames are fed by hand at 10 per second, so that no timing can vary."""

    def setUp(self):
        with mock.patch.object(VideoSource, "_run", lambda _self: None):
            self.source = VideoSource("unused")
        self.next_to_feed = 0

    def feed(self, count: int) -> None:
        for _ in range(count):
            pixels = np.full((1, 1, 3), self.next_to_feed, dtype=np.uint8)
            self.source._frames.put(_TimedFrame(pixels, self.next_to_feed / 10))
            self.next_to_feed += 1

    def frame_at(self, now: float) -> int | None:
        pixels = self.source.next_frame(now)
        return None if pixels is None else int(pixels[0, 0, 0])

    def test_normal_speed_follows_the_wall_clock(self):
        self.feed(8)
        self.assertEqual(self.frame_at(100.0), 0)
        self.assertEqual(self.frame_at(100.25), 2)

    def test_four_times_speed_reaches_frames_four_times_sooner(self):
        self.feed(8)
        self.source.set_speed(4.0, 100.0)
        self.assertEqual(self.frame_at(100.0), 0)
        self.assertEqual(self.frame_at(100.13), 5)

    def test_quarter_speed_holds_frames_four_times_longer(self):
        self.feed(8)
        self.source.set_speed(0.25, 100.0)
        self.assertEqual(self.frame_at(100.0), 0)
        self.assertIsNone(self.frame_at(100.39))
        self.assertEqual(self.frame_at(100.41), 1)

    def test_changing_speed_does_not_jump_in_the_video(self):
        self.feed(8)
        self.assertEqual(self.frame_at(100.0), 0)
        self.assertEqual(self.frame_at(100.21), 2)
        # x1 got to 0.21 s, so at x4 the next frame is 0.09 s of video, 0.0225 s, away.
        self.source.set_speed(4.0, 100.21)
        self.assertIsNone(self.frame_at(100.22))
        self.assertEqual(self.frame_at(100.235), 3)

    def test_slowing_down_applies_to_the_frame_already_waiting(self):
        self.feed(8)
        self.assertEqual(self.frame_at(100.0), 0)
        self.source.set_speed(0.25, 100.0)
        self.assertIsNone(self.frame_at(100.2))  # Due now at x1, but not at x0.25.
        self.assertEqual(self.frame_at(100.41), 1)

    def test_speed_can_change_while_paused_without_moving_the_video(self):
        self.feed(8)
        self.assertEqual(self.frame_at(100.0), 0)
        self.source.toggle_pause(100.0)
        self.source.set_speed(4.0, 150.0)
        self.assertIsNone(self.frame_at(200.0))
        self.source.toggle_pause(200.0)
        self.assertIsNone(self.frame_at(200.0))
        self.assertEqual(self.frame_at(200.03), 1)

    def test_pausing_at_a_changed_speed_does_not_count_the_pause(self):
        self.feed(8)
        self.source.set_speed(4.0, 100.0)
        self.assertEqual(self.frame_at(100.0), 0)
        self.source.toggle_pause(100.0)
        self.source.toggle_pause(160.0)
        self.assertEqual(self.frame_at(160.03), 1)

    def test_a_decoder_that_falls_behind_builds_no_backlog(self):
        self.feed(1)
        self.source.set_speed(4.0, 100.0)
        self.assertEqual(self.frame_at(100.0), 0)
        # Nothing arrives for a long time, which would be 40 s of video at x4.
        self.assertIsNone(self.frame_at(110.0))
        self.feed(8)
        self.source.set_speed(1.0, 110.0)
        # Normal speed really is normal, rather than racing to catch up.
        self.assertIsNone(self.frame_at(110.05))
        self.assertEqual(self.frame_at(110.11), 1)

    def test_speed_set_before_the_first_frame_applies_from_the_start(self):
        self.source.set_speed(4.0, 100.0)
        self.assertIsNone(self.frame_at(105.0))
        self.feed(8)
        self.assertEqual(self.frame_at(105.0), 0)
        self.assertEqual(self.frame_at(105.13), 5)


class RealVideoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "clip.mp4"

    def test_a_very_short_clip_loops_at_four_times_speed(self):
        # At x4 this clip reopens eight times a second, which mustn't fail or stall.
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=854x480:r=30:d=0.5", "-pix_fmt", "yuv420p", str(self.path)],
            check=True,
        )
        source = VideoSource(str(self.path))
        self.addCleanup(source.stop)
        source.set_speed(4.0, time.monotonic())
        start = time.monotonic()
        frames = 0
        while time.monotonic() - start < 1.0:
            frames += source.next_frame(time.monotonic()) is not None
            time.sleep(0.005)
        self.assertIsNone(source.error)
        self.assertGreater(source._last_shown_time, 3.0)  # 4.0 s of video in 1.0 s.
        self.assertGreater(frames, 40)


class ConfigFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "mine.yaml"

    def test_assigning_a_control_number(self):
        self.path.write_text("name: Mine\nport: Mine\neffects:\n  playback_speed: 12\n")
        self.assertEqual(load_controller(self.path).effects, {Effect.PLAYBACK_SPEED: 12})

    def test_a_note_has_no_position_so_it_is_refused(self):
        self.path.write_text("name: Mine\nport: Mine\neffects:\n  playback_speed: {note: 12}\n")
        with self.assertRaises(ConfigError):
            load_controller(self.path)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class WindowTests(GuiTestCase):
    def play_video(self, name: str = "clip.mp4") -> None:
        path = self.dir / name
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=854x480:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        QTest.qWait(200)

    def video_seconds_played_in(self, wall_seconds: float) -> float:
        source = self.window._view._source
        before = source._last_shown_time
        # A real event loop, because QTest.qWait can stall playback for 500 ms.
        loop = QEventLoop()
        QTimer.singleShot(round(wall_seconds * 1000), loop.quit)
        loop.exec()
        return source._last_shown_time - before

    def test_control_at_the_top_plays_about_four_times_as_fast(self):
        self.play_video()
        self.set_effect(Effect.PLAYBACK_SPEED, 1.0)
        self.assertAlmostEqual(self.video_seconds_played_in(0.5), 2.0, delta=0.5)

    def test_control_at_the_bottom_plays_about_a_quarter_as_fast(self):
        self.play_video()
        self.set_effect(Effect.PLAYBACK_SPEED, 0.0)
        self.assertAlmostEqual(self.video_seconds_played_in(1.0), 0.25, delta=0.15)

    def test_a_new_file_keeps_the_speed_the_control_is_at(self):
        self.play_video()
        self.set_effect(Effect.PLAYBACK_SPEED, 1.0)
        self.play_video("next.mp4")
        self.assertEqual(self.window._view._source._speed, 4.0)

    def test_it_does_nothing_to_an_image(self):
        path = self.dir / "still.png"
        Image.new("RGB", (40, 40), "blue").save(path)
        self.window.load(str(path))
        QTest.qWait(200)
        before = self.picture()
        self.set_effect(Effect.PLAYBACK_SPEED, 1.0)
        np.testing.assert_array_equal(self.picture(), before)

    def test_with_nothing_loaded_it_still_applies_to_the_next_file(self):
        self.set_effect(Effect.PLAYBACK_SPEED, 0.0)
        self.play_video()
        self.assertEqual(self.window._view._source._speed, 0.25)

    def test_opening_the_setup_window_returns_to_normal_speed(self):
        self.play_video()
        self.set_effect(Effect.PLAYBACK_SPEED, 1.0)
        QTest.mouseClick(self.window._configure_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        self.assertEqual(self.window._view._source._speed, 1.0)

    def test_assigning_a_slider_and_moving_it(self):
        device = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(device.close)
        QTest.mouseClick(self.window._configure_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        dialog = self.window._config_dialog
        dialog._device.setCurrentIndex(
            dialog._device.findText(test_port_name("Oxygen"), Qt.MatchFlag.MatchContains)
        )
        QTest.qWait(50)
        QTest.mouseClick(dialog._assign_buttons[Effect.PLAYBACK_SPEED], Qt.MouseButton.LeftButton)
        device.send(mido.Message("control_change", control=100, value=127))
        QTest.qWait(100)
        with mock.patch.object(dialog, "_confirm_replace", return_value=True):
            QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
            QTest.qWait(200)

        self.play_video()
        for value, speed in ((127, 4.0), (64, 1.0), (0, 0.25)):
            device.send(mido.Message("control_change", control=100, value=value))
            QTest.qWait(100)
            self.assertAlmostEqual(self.window._view._source._speed, speed)


if __name__ == "__main__":
    unittest.main()
