# Getting started

## Requirements

- Linux with an X11 or Wayland desktop. It's developed on Ubuntu 24.04. On Wayland it runs through XWayland.
- A graphics driver that supports OpenGL 3.3.
- A MIDI controller. The app runs without one, but then nothing can control the effects.

## Run the app

**From the AppImage:**

```sh
make appimage
./dist/VisualControl-x86_64.AppImage
```

**From source:** see [Set up a development environment](development.md#set-up-a-development-environment), then run this from the project root:

```sh
.venv/bin/python -m visual_control
```

To open a file straight away, add its path to either command.

## Play something

1. Drag an image or video onto the window. If you drop several, only the first one opens. You can also drop a MIDI file, alone or with the image or video, to trigger effects from its notes. See [MIDI files](midi-files.md). An audio file, such as an mp3, plays the song and triggers effects from its beat. See [Audio files](audio-files.md).
2. Plug in your controller. The status bar shows `Connected:` and the controller's name. The app checks for controllers every 2 seconds, so you can plug one in at any time.
3. Move a control. See [Effects](effects.md) for what's available.

To use your own choice of controls, or a controller the app doesn't know, see [Controllers](controllers.md).

## Going fullscreen

Click **Fullscreen**, and press **Esc** to leave. Fullscreen hides the status bar and the mouse pointer.

## What can be played

The app identifies files by their contents, so the file extension doesn't matter.

- **Video:** anything FFmpeg can decode, including animated GIFs. Videos loop forever. Sound is ignored.
- **Images:** any format Pillow can read. Rotation stored in the file is applied, and transparent areas become black.
- **Size:** anything larger than 1080p is scaled down to fit, in either orientation. Smaller media is never scaled up in the file, only stretched to fit the window.

If a file can't be opened, whatever is playing keeps playing, and the status bar says why.

## Good to know

- **Effects start off.** The app can't ask a controller where its controls are, so an effect stays off until you move its control. A slider that's already raised has no effect until then.
- **Opening the setup window turns effects off.** Moving controls to assign them won't change the picture, and effects stay off until you move a control after closing the window. If the video was paused, it stays paused.

## Troubleshooting

| Problem | What to try |
|---|---|
| The status bar says `No controllers connected` | Check the cable. If the controller is new to the app, [set it up](controllers.md#set-up-a-controller). |
| A control does nothing | Check it's assigned in **Configure new controller**. Your own controller file replaces the built-in one completely. |
| An effect jumps when you first touch its control | This is expected, because the control's real position is only known once it moves. |
| A key triggers an effect meant for a pad | Keys and pads can share note numbers. See [Notes and channels](controllers.md#notes-and-channels). |
| The status bar shows an error naming a `.yaml` file | That controller file has a mistake, and the message says what. Other controllers keep working. |
| A rotary encoder jumps around or barely moves | The app expects absolute values from 0 to 127. Encoders set to relative mode won't work properly, so change this in the controller's own settings if it can. |
| Video stutters at x4 | See [Playback speed limits](effects.md#playback-speed-limits). |
| The app won't start, with an error about the `xcb` platform plugin | Run `sudo apt install libxcb-cursor0`. |
