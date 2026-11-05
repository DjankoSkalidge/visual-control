# make appimage   Build dist/VisualControl-x86_64.AppImage
# make bundle     Build only the app folder, in build/pyinstaller/dist/visual-control
# make test       Run the tests on an invisible display, so no windows pop up
# make clean      Remove everything the build created

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
BUILD_DEPS := $(VENV)/.build-deps-installed

BUILD := build
BUNDLE := $(BUILD)/pyinstaller/dist/visual-control
APPDIR := $(BUILD)/AppDir
APPIMAGE := dist/VisualControl-x86_64.AppImage

APPIMAGETOOL_VERSION := 1.9.1
APPIMAGETOOL_SHA256 := ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
APPIMAGETOOL := $(BUILD)/tools/appimagetool-$(APPIMAGETOOL_VERSION).AppImage

.PHONY: appimage bundle test clean

appimage: bundle $(APPIMAGETOOL)
	rm -rf $(APPDIR)
	mkdir -p $(APPDIR) dist
	cp -r $(BUNDLE) $(APPDIR)/visual-control
	cp packaging/AppRun packaging/visual-control.desktop packaging/visual-control.svg $(APPDIR)/
	ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 $(APPIMAGETOOL) --no-appstream $(APPDIR) $(APPIMAGE)
	@echo "Built $(APPIMAGE)"

bundle: $(BUILD_DEPS)
	rm -rf $(BUILD)/pyinstaller
	$(VENV_PYTHON) -m PyInstaller --noconfirm --clean --onedir --windowed \
		--name visual-control \
		--distpath $(BUILD)/pyinstaller/dist \
		--workpath $(BUILD)/pyinstaller/work \
		--specpath $(BUILD)/pyinstaller \
		--paths . \
		--hidden-import mido.backends.rtmidi \
		--hidden-import rtmidi \
		--copy-metadata mido \
		--add-data "$(CURDIR)/visual_control/controllers/*.yaml:visual_control/controllers" \
		--collect-submodules glcontext \
		--collect-submodules moderngl \
		packaging/launcher.py
	# Graphics drivers load these from the bundle too, and fail if they're older
	# than the versions the machine's drivers were built against. Every desktop
	# Linux has them, so use the machine's own.
	rm -f $(BUNDLE)/_internal/libstdc++.so.6 $(BUNDLE)/_internal/libgcc_s.so.1

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

$(BUILD_DEPS): requirements.txt requirements-build.txt | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install -r requirements.txt -r requirements-build.txt
	touch $@

$(APPIMAGETOOL):
	mkdir -p $(dir $@)
	curl -fsSL -o $@.download https://github.com/AppImage/appimagetool/releases/download/$(APPIMAGETOOL_VERSION)/appimagetool-x86_64.AppImage
	echo "$(APPIMAGETOOL_SHA256)  $@.download" | sha256sum --check --quiet
	chmod +x $@.download
	mv $@.download $@

test:
	xvfb-run -a -s "-screen 0 1920x1080x24" $(VENV_PYTHON) -m unittest discover -s tests -t .

clean:
	rm -rf $(BUILD) dist
