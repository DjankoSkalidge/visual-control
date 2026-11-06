# Keyboard

Keys on the computer's keyboard can trigger [press effects](effects.md#press-effects-one-shot-animations), like pads on a controller. This works with or without a controller plugged in, and alongside one.

## Set up the keyboard

1. Click **Configure keyboard**, below **Configure new controller**. This turns all effects off until something triggers them after the window closes.
2. Click an effect's button, then press a key.
3. Repeat for each effect you want.
4. Click **Save**. The keys work straight away, and again the next time the app starts.

Good to know while assigning:

- **Only press effects are listed.** Effects like blur follow a slider's position, which a key doesn't have.
- **Each key does one thing.** Pressing a key that's already in use moves it to the new effect, and the row tells you where it came from.
- **Single keys only.** Ctrl, Alt, Shift and the like are ignored, alone or held with another key, so the app can't take over shortcuts like Ctrl+Q.
- **Esc can't be assigned**, because it leaves fullscreen. While waiting for a key, Esc cancels. Pressing it again closes the window.
- **Cancel** keeps the keys you had.

## Using the keys

- **A key works whenever the main window is in front**, in fullscreen too.
- **Holding a key down triggers it once**, like a single hit on a pad.
- **An assigned key does only its effect.** Space assigned to an effect no longer clicks the button that last had focus, for example.
- **Keys do nothing while a setup window is open**, as with controllers.

## The keyboard file

The setup is stored in `~/.config/visual-control/keyboard.yaml`, or inside `XDG_CONFIG_HOME` if that's set. You can edit it by hand, then restart the app:

```yaml
effects:
  flash: Space
  ripple: Q
  pause: P
  stutter: F5
```

Effect names are the press effects in [Effects](effects.md). Key names are as the setup window shows them. A key can only be assigned to one effect.

If the file has a mistake, the status bar names `keyboard.yaml` and the problem, and no keys work until it's fixed. Saving from the setup window rewrites it.
