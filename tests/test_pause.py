"""Pausing in a real window, with a real button press. Needs a display."""

import os
import subprocess
import unittest
import unittest.mock

import mido
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.gui import GuiTestCase, test_port_name
from visual_control.effects import Effect


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class PauseTests(GuiTestCase):
    def play_video(self, name: str = "clip.mp4") -> None:
        path = self.dir / name
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        QTest.qWait(300)

    def press_pause(self) -> None:
        self.set_effect(Effect.PAUSE, 1.0)

    def status(self) -> str:
        return self.window._status.text()

    def test_press_freezes_the_video_and_says_so(self):
        self.play_video()
        self.press_pause()
        self.assertEqual(self.status(), "clip.mp4 (paused)")
        frozen = self.picture()
        QTest.qWait(400)
        np.testing.assert_array_equal(self.picture(), frozen)

    def test_second_press_plays_again(self):
        self.play_video()
        self.press_pause()
        frozen = self.picture()
        self.press_pause()
        self.assertEqual(self.status(), "clip.mp4")
        QTest.qWait(300)
        self.assertFalse(np.array_equal(self.picture(), frozen))

    def test_effects_still_work_on_a_paused_frame(self):
        self.play_video()
        self.press_pause()
        frozen = self.picture()
        self.set_effect(Effect.BLUR, 1.0)
        self.assertFalse(np.array_equal(self.picture(), frozen))
        self.set_effect(Effect.BLUR, 0.0)
        np.testing.assert_array_equal(self.picture(), frozen)

    def test_pause_has_no_effect_on_an_image(self):
        path = self.dir / "still.png"
        Image.new("RGB", (40, 40), "blue").save(path)
        self.window.load(str(path))
        QTest.qWait(200)
        before = self.picture()
        self.press_pause()
        self.assertEqual(self.status(), "still.png")
        np.testing.assert_array_equal(self.picture(), before)

    def test_pause_does_not_overwrite_an_error_on_an_image(self):
        path = self.dir / "still.png"
        Image.new("RGB", (40, 40), "blue").save(path)
        bad = self.dir / "bad.m4v"
        bad.write_text("not a video")
        self.window.load(str(path))
        self.window.load(str(bad))
        self.press_pause()
        self.assertIn("bad.m4v", self.status())

    def test_pause_with_nothing_loaded_does_nothing(self):
        self.press_pause()
        self.assertEqual(self.status(), "")

    def test_a_new_file_starts_playing(self):
        self.play_video()
        self.press_pause()
        self.play_video("next.mp4")
        self.assertEqual(self.status(), "next.mp4")
        frame = self.picture()
        QTest.qWait(300)
        self.assertFalse(np.array_equal(self.picture(), frame))


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class AssignPauseTests(GuiTestCase):
    """The whole flow: assign a button in the setup window, save, and press it."""

    def assign_and_save(self, device, press: list[int]) -> None:
        QTest.mouseClick(self.window._configure_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        dialog = self.window._config_dialog
        dialog._device.setCurrentIndex(
            dialog._device.findText(test_port_name("Oxygen"), Qt.MatchFlag.MatchContains)
        )
        QTest.qWait(50)
        QTest.mouseClick(dialog._assign_buttons[Effect.PAUSE], Qt.MouseButton.LeftButton)
        device.send(mido.Message.from_bytes(press))
        QTest.qWait(100)
        with unittest.mock.patch.object(dialog, "_confirm_replace", return_value=True):
            QTest.mouseClick(dialog._save_button, Qt.MouseButton.LeftButton)
            QTest.qWait(200)

    def check_flow(self, press: list[int], release: list[int]) -> None:
        device = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(device.close)
        self.assign_and_save(device, press)

        path = self.dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        QTest.qWait(300)

        def tap():
            device.send(mido.Message.from_bytes(press))
            device.send(mido.Message.from_bytes(release))
            QTest.qWait(100)

        tap()
        self.assertEqual(self.window._status.text(), "clip.mp4 (paused)")
        tap()
        self.assertEqual(self.window._status.text(), "clip.mp4")

    def test_button_that_sends_notes(self):
        self.check_flow([144, 16, 127], [128, 16, 0])

    def test_assigning_does_not_pause_the_video(self):
        device = mido.open_output(test_port_name("Oxygen"), virtual=True)
        self.addCleanup(device.close)
        path = self.dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        QTest.qWait(200)
        self.assign_and_save(device, [144, 16, 127])
        self.assertEqual(self.window._status.text(), "clip.mp4")


if __name__ == "__main__":
    unittest.main()
