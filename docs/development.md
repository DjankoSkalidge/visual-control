# Development

## Set up a development environment

System packages, on Ubuntu 24.04:

```sh
sudo apt install libasound2-dev libxcb-cursor0 ffmpeg xvfb
```

- `libasound2-dev` is needed to build `python-rtmidi`, which compiles from source.
- `libxcb-cursor0` is needed for Qt on X11.
- `ffmpeg` and `xvfb` are only needed for the tests.

Python packages:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The project's virtual environment uses Python 3.15.2 from pyenv. Versions in `requirements.txt` are pinned.

Run the app from the project root:

```sh
.venv/bin/python -m visual_control
```

## Run the tests

```sh
make test
```

This runs every test on an invisible Xvfb display, so no windows pop up and you can keep using your machine. It takes about 2 minutes. To run one module:

```sh
xvfb-run -a .venv/bin/python -m unittest tests.test_animations
```

Tests use virtual MIDI ports, so a controller that's plugged in can't disturb them. Because of those shared port names, don't run two copies at once.

Xvfb draws with the CPU, so it's fine for tests but says nothing about real framerate. Run performance measurements on a real display.

### Writing tests

- **Measure playback timing under a real event loop**, with `app.exec()` or `QEventLoop`. `QTest.qWait` can falsely show stalls of about 500 ms.
- **Inherit from `GuiTestCase`** in `tests/gui.py` for anything with a window. OpenGL widgets must be destroyed on the GUI thread, or garbage collection on a decoder thread can abort the process.
- **Include widths like 854, 426 and 1080 in test media.** Decoders pad rows at those widths, and common widths like 640 and 1280 hide the resulting bugs.
- **Hold animations at a fixed moment** by patching `_animation_progress`, so that timing can't affect results. `tests/test_animations.py` has examples.
- **Avoid test patterns finer than the effect's movement.** A color split can land on the next stripe along and look smaller than it is.

## Build the AppImage

```sh
make appimage    # Builds dist/VisualControl-x86_64.AppImage
make bundle      # Builds only the app folder
make clean       # Removes everything the build created
```

The AppImage is a snapshot, so rebuild it to include code changes. The build downloads `appimagetool`, and checks it against a fixed SHA-256 hash.

### The macOS build

A Mac app can only be built on a Mac, so GitHub builds it. On GitHub, open **Actions > macOS build > Run workflow**, or run:

```sh
gh workflow run macos.yml
```

It runs the tests on an Apple Silicon Mac (the ones that open a window skip themselves), builds the app with `packaging/build-macos.sh`, checks that it starts, and publishes `VisualControl-macOS-arm64.dmg` on the `macos-latest` release, replacing the previous build. It takes about 10 minutes. Untick **release** to only keep the file on the run's page instead.

The app is ad-hoc signed, which is free but means macOS asks before the first launch. See [On a Mac](getting-started.md#on-a-mac).

## How the code is organized

| File | Responsibility |
|---|---|
| `visual_control/__main__.py` | Entry point |
| `visual_control/window.py` | Main window, file dropping, and connecting effects to the view |
| `visual_control/view.py` | OpenGL display, shaders, animations and stutter |
| `visual_control/media.py` | Loading files, decoding on a background thread, and the playback clock |
| `visual_control/midi.py` | MIDI input and capture for the setup window |
| `visual_control/effects.py` | The list of effects, independent of any controller |
| `visual_control/config_window.py` | The setup window |
| `visual_control/keyboard.py` | Loading and saving the keyboard setup |
| `visual_control/keyboard_window.py` | The window for assigning keys to press effects |
| `visual_control/midi_file.py` | Reading a MIDI file's notes, and playing one channel on a loop |
| `visual_control/midi_file_window.py` | The panel for choosing a channel and assigning effects to its notes |
| `visual_control/audio_file.py` | Finding the hits in an audio file, and playing it with its hits in sync |
| `visual_control/audio_file_window.py` | The panel for assigning effects and sensitivity to each frequency band |
| `visual_control/controllers/` | Controller file loading and the built-in setups |
| `reference/controller_maps/` | The older Python maps of each controller's controls, kept for reference |

### How a frame gets to the screen

```text
Video file -> decoder thread -> queue (8 frames) -> VideoSource clock
                                                         |
                               every 5 ms, MediaView._poll asks for the frame that's due
                                                         |
                       saturation -> RGB shift -> blur -> display shader -> screen
```

- **Decoding** runs on a background thread. When the queue is full, the decoder waits, which is also how pausing avoids using CPU.
- **The clock** tracks the position in the video's own seconds, and frames that are already late are dropped. Playback speed and pause just change how fast the clock runs. If the decoder falls behind, the clock is held back, so slowing down later takes effect immediately.
- **Looping** reopens the file rather than seeking, because that works for every format, including ones that can't seek, such as GIF.
- **Passes** that aren't in use are skipped. Saturation, RGB shift and blur each draw into their own floating-point texture, which prevents banding.

### How MIDI reaches an effect

```text
Device -> MidiInput._on_message (MIDI thread) -> effect_changed signal
       -> MainWindow._on_effect_changed (GUI thread) -> MediaView
```

Qt queues the signal across threads. MIDI errors only ever mean "not connected" and are retried, so MIDI can't take the visuals down.

A MIDI file takes a shorter path, because it plays on the GUI thread:

```text
MidiFilePlayer timer -> note_played signal -> MainWindow._on_midi_file_note -> MediaView
```

The player waits on a single-shot timer for the next note. Each note's time counts from the start of the current loop, rather than from the previous note, so timer delays never build up into drift.

An audio file is analysed before it plays, and then follows the sound:

```text
read_audio_file: decode to mono -> spectra every 12 ms -> rise in loudness per band
AudioFilePlayer: QMediaPlayer position -> AudioClock -> HitSchedule (every 5 ms)
               -> hit signal -> MainWindow._on_audio_file_hit -> MediaView
```

- **Hits are picked per sensitivity** from the stored loudness rises, in a few milliseconds, so the panel's counts update live.
- **The audio is the clock.** Qt reports the playing position only every 50 ms or so, so `AudioClock` fills in between from the system clock, and gently corrects towards each report. A report far off the estimate, like a loop, is followed at once.
- **Tests** mute the sound by patching `audio_file.MUTED`, which `GuiTestCase` does. Use `tests.gui.wait` rather than `QTest.qWait` in them: `qWait` can hang for good once a `QMediaPlayer` has stopped.

## Add an effect

### A one-shot animation

1. Add it to `Effect` and `PRESS_EFFECTS` in `effects.py`.
2. Add it to `ANIMATIONS` in `view.py`, with its progress value's name and its length in seconds. The main window and rendering pick it up from there.
3. In `DISPLAY_SHADER`, declare `uniform float <name>_progress;` and use it. A progress of 0.0 must mean off. The value has to actually affect the output: OpenGL removes unused values, and looking one up then fails.
4. Add tests to `tests/test_animations.py`.

Step 2 also covers restarts, overlapping and turning off when the setup window opens.

### A position effect

1. Add it to `Effect` in `effects.py`.
2. Add a setter to `MediaView` that takes an amount from 0.0 to 1.0. Use `centered()` if the middle means "unchanged", which provides the dead zone.
3. Reset it in `MediaView.reset_effects`.
4. Connect it in `_effect_actions` in `window.py`.
5. Assign it in the built-in YAML files. A test requires every position effect to be assigned, so if it's meant for users to assign, add it to `left_to_users` in `tests/test_controller_config.py`.

### A toggle

Follow the position effect steps, adding it to `PRESS_EFFECTS` as well, and leave out the built-in assignment.

### Rules for every effect

- **Don't rename effects.** Their names are stored in users' controller files, so a rename breaks those files.
- **Say "rotary encoder" and "slider"**, not "knob" or "fader", in code, comments and tests.
- **Think about where it goes in the order.** See [How effects combine](effects.md#how-effects-combine).

## Known gaps

- Pad and button hit strength is ignored, so every press is full strength.
- MIDI channels are ignored. See [Notes and channels](controllers.md#notes-and-channels).
- The newest one-shot animations have only been tested with CPU drawing, so their framerate on a real GPU hasn't been measured.
- Rotary encoders are assumed to send absolute values, and whether Oxygen buttons are momentary hasn't been verified.
