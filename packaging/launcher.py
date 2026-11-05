"""Entry point for the packaged app. PyInstaller can't start from inside a package."""

import sys

from visual_control.__main__ import main

sys.exit(main())
