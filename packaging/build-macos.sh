#!/usr/bin/env bash
# Build dist/VisualControl-macOS-arm64.dmg, an unsigned app for Apple Silicon Macs.
# Run it on a Mac, from the repository root, with requirements.txt and
# requirements-build.txt installed in the active Python. GitHub Actions runs it
# from .github/workflows/macos.yml.
set -euo pipefail

APP_NAME="Visual Control"
BUILD=build/macos
DMG=dist/VisualControl-macOS-arm64.dmg

rm -rf "$BUILD" "$DMG"
mkdir -p "$BUILD" dist

python -m PyInstaller --noconfirm --clean --onedir --windowed \
	--name "$APP_NAME" \
	--osx-bundle-identifier io.github.djankoskalidge.visualcontrol \
	--distpath "$BUILD/dist" \
	--workpath "$BUILD/work" \
	--specpath "$BUILD" \
	--paths . \
	--hidden-import mido.backends.rtmidi \
	--hidden-import rtmidi \
	--copy-metadata mido \
	--add-data "$PWD/visual_control/controllers/*.yaml:visual_control/controllers" \
	--collect-submodules glcontext \
	--collect-submodules moderngl \
	packaging/launcher.py

APP="$BUILD/dist/$APP_NAME.app"

# Apple Silicon only runs signed code. Without a paid Apple Developer account,
# an ad-hoc signature is the most there can be, so macOS asks before the first launch.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# The disk image holds the app and a shortcut to Applications to drag it onto.
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Built $DMG"
