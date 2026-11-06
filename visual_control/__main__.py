import os
import sys

from PySide6.QtWidgets import QApplication

from .view import configure_opengl
from .window import MainWindow


def main() -> int:
    # On Linux, the OpenGL library we use connects through X11. Wayland desktops
    # run X11 apps through XWayland, so this works on both. Macs have no X11, and
    # Qt's own platform works there.
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    configure_opengl()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.open_files(app.arguments()[1:])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
