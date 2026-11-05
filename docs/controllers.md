# Controllers

A controller setup assigns physical controls to [effects](effects.md). The app has built-in setups for two controllers, and you can add your own or replace those.

Any known controller that's plugged in is active automatically, so there's nothing to select.

## Set up a controller

1. Click **Configure new controller**. This turns all effects off until you move a control after closing the window.
2. Choose your **MIDI device**. If it's already set up, its assignments are loaded so you can change them.
3. Click an effect's button, then move a control or hit a pad on your device.
4. Repeat for each effect you want. The list scrolls if it doesn't fit on your screen.
5. Click **Save**.

Good to know while assigning:

- **Each control does one thing.** Assigning a control that's already in use moves it to the new effect, and the row tells you where it came from.
- **Position effects can't use pads.** If you hit a pad for one, the row says `Needs a slider or rotary encoder` and keeps listening.
- **Esc cancels** the assignment in progress. Pressing it again closes the window.
- **Changing device starts over**, because control numbers belong to one device.
- **Each device gets one setup.** Saving replaces any existing setup for that device, or with that name, after asking you.

## Built-in assignments

Press effects and playback speed aren't included, so assign those yourself.

| Effect | Akai MIDI Mix | Control | Oxygen | Control |
|---|---|---|---|---|
| `blur` | RE_11 | 16 | RE_C10 | 22 |
| `pixelate` | RE_12 | 20 | RE_C11 | 23 |
| `saturation_red` | Slider 1 | 19 | Slider C1 | 20 |
| `saturation_yellow` | Slider 2 | 23 | Slider C2 | 21 |
| `saturation_green` | Slider 3 | 27 | Slider C3 | 71 |
| `saturation_cyan` | Slider 4 | 31 | Slider C4 | 72 |
| `saturation_blue` | Slider 5 | 49 | Slider C5 | 25 |
| `saturation_magenta` | Slider 6 | 53 | Slider C6 | 73 |
| `rgb_shift_red_horizontal` | RE_13 | 24 | RE_C12 | 61 |
| `rgb_shift_red_vertical` | RE_14 | 28 | RE_C13 | 24 |
| `rgb_shift_green_horizontal` | RE_15 | 46 | RE_C14 | 26 |
| `rgb_shift_green_vertical` | RE_16 | 50 | RE_C15 | 27 |
| `rgb_shift_blue_horizontal` | RE_17 | 54 | RE_C16 | 62 |
| `rgb_shift_blue_vertical` | RE_18 | 58 | RE_C17 | 95 |

Control numbers can differ between devices, or with a device's own settings. If a control doesn't respond, assign it in the setup window.

## Controller files

Setups are stored as YAML files, which you can also edit by hand.

| Location | Contains |
|---|---|
| `~/.config/visual-control/controllers/` | Your setups. If `XDG_CONFIG_HOME` is set, the folder is inside that instead. |
| `visual_control/controllers/` | The built-in setups |

Your file **replaces** a built-in setup for the same device completely, rather than adding to it. Any effect you leave out has no control.

The app reads these files when it starts and after you save in the setup window, so restart it after editing one by hand. Saving from the setup window rewrites the file, which removes any comments you added.

### Format

```yaml
name: My controller     # Shown in the status bar. Must be unique.
port: My Device         # Text to look for in the MIDI device's name.

effects:
  blur: 16              # A rotary encoder or slider's control number.
  playback_speed: 20
  pause: 96             # A button that sends a control change.
  ripple: {note: 36}    # A pad or key that sends a note.
```

Rules:

- Effect names are listed in [Effects](effects.md).
- Numbers go from 0 to 127.
- `{note: ...}` only works for press effects.
- A control can only be assigned to one effect, and an effect can only appear once.
- Control 36 and note 36 are different controls, so they can be used for different effects.

If a file breaks these rules, the status bar names the file and the problem. That file is skipped, and the others still load.

## How presses are detected

- **Notes:** each note on is a press. Note off and note on with no velocity are ignored.
- **Control changes:** a press is the value leaving 0. Press and release sends a value and then 0, which counts as one press. Controls that don't return to 0 only count the first time, so use a button rather than a slider.

## Notes and channels

The app ignores MIDI channels, so a key and a pad with the same note number count as the same control.

This matters on the Oxygen, where the pads use channel 10 and the keys use channel 2, with overlapping note numbers. According to `reference/controller_maps/oxygen.py`, the pads send these notes:

| Pad | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Note | 36 | 38 | 42 | 46 | 50 | 45 | 51 | 49 |

If you assign an effect to pad 1, the key that plays note 36 triggers it too. Keys can also serve as extra triggers when you've run out of pads, as long as you choose notes that no pad uses.

## Rotary encoders

The app expects absolute values from 0 to 127. It hasn't been confirmed on real hardware for every controller, and encoders in relative mode won't work properly.
