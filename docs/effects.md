# Effects

Effects come in two kinds:

- **Position effects** follow where a rotary encoder or slider is. They can't be assigned to a pad, because a pad has no position to follow.
- **Press effects** respond to a press. They can be assigned to a pad, key or button.

The name in `code` is what a [controller file](controllers.md#controller-files) uses.

> Which effects have a control already depends on the controller. Press effects and playback speed have no built-in assignment, so you choose controls for them in the [setup window](controllers.md#set-up-a-controller).

## Position effects

| Effect | Name | 0 | Middle (60-67) | 127 |
|---|---|---|---|---|
| Blur | `blur` | Off | Partial | Strongest |
| Pixelate | `pixelate` | Off | Partial | Largest blocks |
| Saturation (6 colors) | `saturation_red` and others | Grey | Unchanged | Boosted |
| RGB shift (6 directions) | `rgb_shift_red_horizontal` and others | Fully left or down | No shift | Fully right or up |
| Playback speed | `playback_speed` | x0.25 | x1 | x4 |

Effects with a meaningful middle have a dead zone there. Values 60-67 all count as the center, so it's easy to find by feel.

### Blur

Softens the whole picture. At full strength, the blur's spread (its sigma) is 4% of the picture's shorter side, so it looks the same on a small clip as on a 1080p one.

### Pixelate

Breaks the picture into blocks of solid color, up to 10% of the shorter side and never smaller than 2 pixels. Blocks stay crisp even when combined with blur.

### Saturation

Six separate controls set the color intensity of one range of hues each: `saturation_red`, `saturation_yellow`, `saturation_green`, `saturation_cyan`, `saturation_blue` and `saturation_magenta`.

The bottom removes that color and the top doubles its intensity. Colors between two ranges blend smoothly, so no hard edges appear. Brightness stays the same, and greys are unaffected.

### RGB shift

Moves the red, green and blue layers of the picture independently, which creates colored fringes. There are two controls per color:

- `rgb_shift_red_horizontal` and `rgb_shift_red_vertical`
- `rgb_shift_green_horizontal` and `rgb_shift_green_vertical`
- `rgb_shift_blue_horizontal` and `rgb_shift_blue_vertical`

The largest shift is 10% of the shorter side. Whatever slides off one edge comes back on the opposite edge, so no empty space appears.

### Playback speed

Each equal move of the control multiplies the speed by the same amount:

| Value | 0 | 30 | 60-67 | 97 | 127 |
|---|---|---|---|---|---|
| Speed | x0.25 | about x0.5 | x1 | about x2 | x4 |

A change takes effect from the next frame, without a jump in the video. A newly loaded file plays at the speed the control is set to. It has no effect on still images.

#### Playback speed limits

- **Slow speeds look choppy.** The video has a fixed number of frames, so a 30 fps clip at x0.25 only shows 7.5 new frames per second. Effects keep drawing smoothly on top.
- **4K sources may not reach x4.** They're measured below. The file is reopened at each loop point, and at x4 that can take longer than the frames queued up ahead of it last.

Measured on a Ryzen 9 7900X, using deliberately hard-to-decode test clips:

| Source | Actual speed at x4 | Longest gap between frames |
|---|---|---|
| 1080p30 | 4.00x | 14 ms |
| 1080p60 | 4.00x | 16 ms |
| 1080p60, 1-second loop | 4.00x | 16 ms |
| 4K60 | 3.72x | 76 ms |
| 4K30, 2-second loop | 3.55x | 81 ms |
| 4K60, 1-second loop | 3.27x | 61 ms |

A slower CPU will have less headroom.

## Press effects: one-shot animations

Each press plays the animation once, and another press restarts it. Different animations can overlap. They all work on still images and paused videos, except stutter.

| Effect | Name | What you see | Length |
|---|---|---|---|
| Ripple | `ripple` | A wave travels from the center to the corners, like water | 0.5 s |
| Zoom punch | `zoom_punch` | Jumps in to 115% and eases back | 0.3 s |
| Glitch burst | `glitch_burst` | Random rows slide sideways with split colors, then it snaps back | 0.3 s |
| Flash | `flash` | Jumps to white and fades back | 0.25 s |
| Shake | `shake` | Rattles and settles | 0.4 s |
| Color shockwave | `color_shockwave` | A ring of split color travels outward from the center | 0.5 s |
| Mirror burst | `mirror_burst` | Folds into a six-sided kaleidoscope, then melts back | 0.4 s |
| Stutter | `stutter` | Cycles the last 8 frames quickly | 0.5 s |

Every press plays at full strength, however hard the pad is hit.

**Flash:** rapid hits make a strobe, and nothing limits how fast it can go. A [MIDI file](midi-files.md) makes this easy to do by accident, for example with flash on the hi-hats. Take care if an audience could include photosensitive people.

**Glitch burst:** the pattern changes several times during a burst and is different on every press.

**Shake:** the picture zooms in slightly while it moves, so its edges never show.

**Stutter:** the video keeps going unseen during the stutter, then the picture jumps to where it has got to. On a paused video, it returns to the paused frame. It has no effect on still images.

## Press effects: toggles

The first press turns these on, and the next turns them off.

| Effect | Name | What it does |
|---|---|---|
| Pause | `pause` | Freezes or resumes the video. Other effects keep working on the frozen frame. It has no effect on still images. A new file always starts playing. |
| Black and white | `black_and_white` | Removes all color |
| Remove red | `remove_red` | Removes the red layer |
| Remove green | `remove_green` | Removes the green layer |
| Remove blue | `remove_blue` | Removes the blue layer |

## How effects combine

Every effect can run at once, and they're applied in a fixed order. Later steps act on the result of earlier ones:

1. Saturation
2. RGB shift
3. Blur
4. Mirror burst, zoom punch, shake, ripple and glitch burst, which move the picture
5. Color shockwave and glitch burst's color split
6. Pixelate
7. Remove red, green and blue
8. Black and white
9. Flash

This order has some useful results:

- Pixelate comes after blur and the moving effects, so its blocks stay crisp.
- Black and white comes after the color effects, so none of them can bring color back.
- Flash comes last, so it's always white, even with black and white on and every color removed. It only covers the picture, not the black bars around it.

Stutter and playback speed aren't in this list, because they change which frame is showing rather than how it's drawn.
