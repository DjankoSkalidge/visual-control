"""What the window does when media fails. Needs a display; a window opens briefly."""

import os
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtTest import QTest

from tests.gui import GuiTestCase
from tests.test_media import make_damaged_late_video, make_video
from visual_control.window import PLACEHOLDER_TEXT


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class FailureTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.failures = []
        self.window._view.playback_failed.connect(self.failures.append)

    def wait_until(self, condition, seconds=10):
        waited = 0
        while not condition() and waited < seconds * 1000:
            QTest.qWait(50)
            waited += 50
        self.assertTrue(condition(), "timed out")

    def good_video(self) -> Path:
        path = self.dir / "good.mp4"
        make_video(path, "-pix_fmt", "yuv420p", seconds="2")
        return path

    def showing_placeholder(self) -> bool:
        return self.window._stack.currentWidget() is self.window._placeholder

    def test_damage_during_playback_stops_and_shows_the_message(self):
        path = self.dir / "late.mp4"
        make_damaged_late_video(path)
        self.window.load(str(path))
        self.assertFalse(self.showing_placeholder())
        self.wait_until(lambda: self.failures)
        QTest.qWait(500)

        self.assertEqual(len(self.failures), 1, "should report only once")
        self.assertIsNone(self.window._view._source)
        self.assertTrue(self.showing_placeholder())
        self.assertIn("late.mp4", self.window._placeholder.text())
        self.assertIn("damaged", self.window._status.text())

    def test_rejected_file_shows_message_when_nothing_is_playing(self):
        path = self.dir / "bad.m4v"
        path.write_text("not a video")
        self.window.load(str(path))
        self.assertTrue(self.showing_placeholder())
        self.assertIn("bad.m4v", self.window._placeholder.text())
        self.assertIn(PLACEHOLDER_TEXT, self.window._placeholder.text())

    def test_rejected_file_leaves_current_video_playing(self):
        self.window.load(str(self.good_video()))
        playing = self.window._view._source
        path = self.dir / "bad.m4v"
        path.write_text("not a video")
        self.window.load(str(path))
        self.assertIs(self.window._view._source, playing)
        self.assertFalse(self.showing_placeholder())
        self.assertIn("bad.m4v", self.window._status.text())

    def test_long_messages_do_not_resize_the_window(self):
        self.window.load(str(self.good_video()))
        QTest.qWait(200)
        size = self.window.size()
        path = self.dir / ("a_very_long_file_name_" * 8 + ".m4v")
        path.write_text("not a video")
        self.window.load(str(path))
        QTest.qWait(200)
        self.assertEqual(self.window.size(), size)
        self.assertIn(path.name, self.window._status.toolTip(), "the full text stays available")

    def test_good_file_plays_after_a_failure_and_clears_the_error(self):
        late = self.dir / "late.mp4"
        make_damaged_late_video(late)
        self.window.load(str(late))
        self.wait_until(lambda: self.failures)
        QTest.qWait(100)

        self.window.load(str(self.good_video()))
        QTest.qWait(500)
        self.assertFalse(self.showing_placeholder())
        self.assertEqual(self.window._status.text(), "good.mp4")
        self.assertIsNone(self.window._view._source.error)

    def test_exception_while_drawing_is_reported_once(self):
        self.window.load(str(self.good_video()))
        with mock.patch.object(self.window._view, "_upload", side_effect=RuntimeError("boom")):
            with self.assertLogs("visual_control.view", level="ERROR") as logs:
                self.wait_until(lambda: self.failures)
                QTest.qWait(500)
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(len(logs.records), 1)
        self.assertTrue(self.showing_placeholder())

    def test_exception_while_reading_frames_is_reported_once(self):
        self.window.load(str(self.good_video()))
        with mock.patch.object(
            self.window._view._source, "next_frame", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs("visual_control.view", level="ERROR") as logs:
                self.wait_until(lambda: self.failures)
                QTest.qWait(500)
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(len(logs.records), 1)

    def test_failure_in_fullscreen_is_visible(self):
        path = self.dir / "late.mp4"
        make_damaged_late_video(path)
        self.window.load(str(path))
        self.window.toggle_fullscreen()
        self.wait_until(lambda: self.failures)
        QTest.qWait(200)
        self.assertTrue(self.window._placeholder.isVisible())
        self.assertIn("late.mp4", self.window._placeholder.text())


if __name__ == "__main__":
    unittest.main()
