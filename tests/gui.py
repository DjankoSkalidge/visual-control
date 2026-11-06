"""Base class for tests that open a real window. They need a display."""

import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from visual_control.controllers.config import load_controllers, merge_controllers
from visual_control.view import configure_opengl
from visual_control.window import MainWindow


def test_port_name(controller_name: str) -> str:
    return f"Visual Control Test {controller_name}"


# The real configurations, except that they only match virtual ports opened by a test.
# That way the tests behave the same whichever controllers are plugged in, and
# bumping a real rotary encoder can't disturb a test.
TEST_CONTROLLERS = tuple(
    dataclasses.replace(controller, port_match=test_port_name(controller.name))
    for controller in load_controllers()[0]
)


def wait(ms: int) -> None:
    """Like QTest.qWait, but in a real event loop, as the app runs.

    QTest.qWait can hang for good once a QMediaPlayer has been stopped, so use this
    in any test that plays an audio file, and anywhere one could have been playing.
    """
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class GuiTestCase(unittest.TestCase):
    config_errors: list[str] = []

    @classmethod
    def setUpClass(cls):
        configure_opengl()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.user_folder = self.dir / "user_controllers"
        for patcher in (
            mock.patch("visual_control.window.load_all_controllers", self._load_test_controllers),
            mock.patch("visual_control.window.USER_FOLDER", self.user_folder),
            # Tests must never play sound through the speakers.
            mock.patch("visual_control.audio_file.MUTED", True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = MainWindow()
        self.addCleanup(self._destroy_window)
        self.window.show()
        QTest.qWait(300)

    def _load_test_controllers(self, user_folder):
        user, _ = load_controllers(user_folder)
        return merge_controllers(list(TEST_CONTROLLERS), user), self.config_errors

    def set_effect(self, effect, amount: float) -> None:
        self.window._midi_inputs[0].effect_changed.emit(effect, amount)
        QTest.qWait(150)

    def show_image(self, pixels: np.ndarray) -> None:
        path = self.dir / "image.png"
        Image.fromarray(pixels).save(path)
        self.window.load(str(path))
        QTest.qWait(200)

    def picture(self) -> np.ndarray:
        """The rendered media alone, without the black bars."""
        image = self.window._view.grabFramebuffer().convertToFormat(QImage.Format.Format_RGB888)
        rows = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
        full = rows[:, : image.width() * 3].reshape(image.height(), image.width(), 3)
        x, y, width, height = self.window._view._letterbox()
        return full[y : y + height, x : x + width].astype(float)

    def _destroy_window(self):
        # OpenGL widgets must be destroyed on the GUI thread. Left to Python's
        # garbage collector, this could happen on a decoder thread and abort.
        self.window.close()
        self.window.deleteLater()
        wait(10)
