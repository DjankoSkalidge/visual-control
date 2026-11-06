"""OpenGL display and filters."""

from __future__ import annotations

import logging
import random
import time
from collections import deque

import moderngl
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .effects import REMOVE_CHANNEL_EFFECTS, Effect
from .media import ImageSource, VideoSource

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 5

# Largest blur, as a fraction of the media's shorter side. Being relative means
# the rotary encoder looks the same on a small clip as on a 1080p one.
MAX_BLUR_SIGMA = 0.04

# Largest pixelation block, also as a fraction of the shorter side.
MAX_PIXEL_SIZE = 0.1
MIN_PIXEL_SIZE = 2  # In media pixels. A size of 1 would look like no effect at all.

# Controls whose middle means "unchanged" have a dead zone around it, so that the
# spot is easy to find by feel.
CENTER_DEAD_ZONE = 0.03

# Saturation sliders: bottom is grey, the middle is unchanged, and the top is boosted.
SATURATION_BANDS = 6
MAX_SATURATION = 2.0

# Largest RGB shift, as a fraction of the shorter side.
MAX_RGB_SHIFT = 0.1

# Effects that play once per press: the shader value that follows each one's progress,
# and how many seconds it lasts.
ANIMATIONS = {
    Effect.RIPPLE: ("ripple_progress", 0.5),
    Effect.ZOOM_PUNCH: ("zoom_progress", 0.3),
    Effect.GLITCH_BURST: ("glitch_progress", 0.3),
    Effect.FLASH: ("flash_progress", 0.25),
    Effect.SHAKE: ("shake_progress", 0.4),
    Effect.COLOR_SHOCKWAVE: ("shockwave_progress", 0.5),
    Effect.MIRROR_BURST: ("mirror_progress", 0.4),
    Effect.INVERT_FLASH: ("invert_progress", 0.3),
    Effect.STROBE_SLICE: ("slice_progress", 0.35),
    Effect.KALEIDOSCOPE_POP: ("kaleidoscope_progress", 0.6),
    Effect.TUNNEL_ZOOM: ("tunnel_progress", 0.5),
    Effect.VIGNETTE_PULSE: ("vignette_progress", 0.4),
    Effect.SPIN_KICK: ("spin_progress", 0.4),
    Effect.HUE_SPIN: ("hue_progress", 0.5),
}

# A stutter repeats the most recent frames, cycling through them quickly.
STUTTER_FRAMES = 8
STUTTER_SECONDS = 0.5
STUTTER_STEP_SECONDS = 0.033

# Fastest playback speed. The slowest is its inverse, x0.25.
MAX_PLAYBACK_SPEED = 4.0

VERTEX_SHADER = """
#version 330
uniform bool flip_y;
in vec2 position;
out vec2 uv;
void main() {
    uv = position * 0.5 + 0.5;
    if (flip_y) {
        uv.y = 1.0 - uv.y;
    }
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

# Scales each pixel's saturation by the factor for its hue. Bands are centered on
# red, yellow, green, cyan, blue and magenta, and a hue between two centers blends
# their factors so there are no hard edges. Brightness stays the same, and greys
# are unaffected because they have no color to scale.
SATURATION_SHADER = """
#version 330
uniform sampler2D image;
uniform float saturation[6];
in vec2 uv;
out vec4 color;
void main() {
    vec3 rgb = texture(image, uv).rgb;
    float largest = max(rgb.r, max(rgb.g, rgb.b));
    float range = largest - min(rgb.r, min(rgb.g, rgb.b));
    if (range == 0.0) {
        color = vec4(rgb, 1.0);
        return;
    }
    float hue;
    if (largest == rgb.r) {
        hue = mod((rgb.g - rgb.b) / range, 6.0);
    } else if (largest == rgb.g) {
        hue = (rgb.b - rgb.r) / range + 2.0;
    } else {
        hue = (rgb.r - rgb.g) / range + 4.0;
    }
    int band = int(floor(hue)) % 6;
    float factor = mix(saturation[band], saturation[(band + 1) % 6], fract(hue));
    float grey = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    color = vec4(clamp(mix(vec3(grey), rgb, factor), 0.0, 1.0), 1.0);
}
"""

# Reads each color channel from its own offset position. What slides off one edge
# comes back on the opposite edge, so that no empty space appears.
RGB_SHIFT_SHADER = """
#version 330
uniform sampler2D image;
uniform vec2 red_offset;
uniform vec2 green_offset;
uniform vec2 blue_offset;
in vec2 uv;
out vec4 color;
void main() {
    color = vec4(
        texture(image, fract(uv - red_offset)).r,
        texture(image, fract(uv - green_offset)).g,
        texture(image, fract(uv - blue_offset)).b,
        1.0
    );
}
"""

# One direction of a Gaussian blur. Each sample sits between two texels, so
# linear filtering averages both in a single fetch.
BLUR_SHADER = """
#version 330
uniform sampler2D image;
uniform vec2 texel_step;
uniform float sigma;
in vec2 uv;
out vec4 color;
void main() {
    vec3 sum = texture(image, uv).rgb;
    float total = 1.0;
    int radius = int(ceil(3.0 * sigma));
    for (int i = 1; i <= radius; i += 2) {
        float near_weight = exp(-float(i * i) / (2.0 * sigma * sigma));
        float far_weight = exp(-float((i + 1) * (i + 1)) / (2.0 * sigma * sigma));
        float weight = near_weight + far_weight;
        vec2 offset = (float(i) + far_weight / weight) * texel_step;
        sum += (texture(image, uv + offset).rgb + texture(image, uv - offset).rgb) * weight;
        total += 2.0 * weight;
    }
    color = vec4(sum / total, 1.0);
}
"""


# Draws to the screen. The animations that move the picture change where it's read
# from, on top of everything else. Then, if pixelating, it averages over blocks, which
# stay crisp whatever the earlier effects did. A tunnel zoom layers smaller copies on
# top. Hue spin, removing color channels and black and white come next, in that order,
# so that no earlier effect can bring color back. The vignette, inverting and a flash
# come last, because they act on the finished picture.
#
# Each animation has a progress value, where 0.0 is off and it ends just before 1.0.
# The ripple is a short train of waves whose center travels from the middle of the
# picture to the corners. Sizes are in units of the picture's shorter side.
DISPLAY_SHADER = """
#version 330
uniform sampler2D image;
uniform vec2 block_size;
uniform float ripple_progress;
uniform float zoom_progress;
uniform float glitch_progress;
uniform float glitch_seed;  // Differs per press, so that no two bursts look the same.
uniform float flash_progress;
uniform float shake_progress;
uniform float shockwave_progress;
uniform float mirror_progress;
uniform float invert_progress;
uniform float slice_progress;
uniform float kaleidoscope_progress;
uniform float tunnel_progress;
uniform float vignette_progress;
uniform float spin_progress;
uniform float hue_progress;
uniform vec2 media_shape;  // The picture's size, divided by its shorter side.
uniform vec3 channels;  // 1.0 keeps a color channel, and 0.0 removes it.
uniform bool black_and_white;
in vec2 uv;
out vec4 color;
const int SAMPLES = 8;
const float TAU = 6.2831853;
const float RIPPLE_HEIGHT = 0.02;
const float RIPPLE_WAVELENGTH = 0.1;
const float RIPPLE_WIDTH = 0.12;
const float ZOOM_AMOUNT = 0.15;
const float GLITCH_STEPS = 6.0;  // How many different patterns one burst goes through.
const float GLITCH_SHIFT = 0.3;
const float GLITCH_SPLIT = 0.012;
const float SHAKE_SIZE = 0.03;
const float SHOCKWAVE_SPLIT = 0.06;
const float SHOCKWAVE_WIDTH = 0.2;
const float MIRROR_WEDGES = 6.0;
const float SLICE_BANDS = 8.0;
const float SLICE_SHIFT = 0.12;
const float KALEIDOSCOPE_WEDGES = 8.0;
const float KALEIDOSCOPE_ZOOM = 0.3;  // How far it zooms in while folded.
const int TUNNEL_COPIES = 3;
const float TUNNEL_SPACING = 1.7;  // Each copy is this many times smaller than the last.
const float VIGNETTE_DARKNESS = 0.85;
const float SPIN_ANGLE = 0.12;  // In radians, about 7 degrees.
const vec3 BRIGHTNESS_WEIGHTS = vec3(0.2126, 0.7152, 0.0722);

vec2 rippled(vec2 position) {
    vec2 from_center = (position - 0.5) * media_shape;
    float distance_out = length(from_center);
    if (ripple_progress == 0.0 || distance_out == 0.0) {
        return position;
    }
    float behind_front = distance_out - ripple_progress * length(media_shape * 0.5);
    float wave = sin(TAU * behind_front / RIPPLE_WAVELENGTH)
        * exp(-behind_front * behind_front / (RIPPLE_WIDTH * RIPPLE_WIDTH));
    // Eases in and out, so that the ripple doesn't pop on or off.
    float strength = smoothstep(0.0, 0.1, ripple_progress)
        * (1.0 - ripple_progress * ripple_progress);
    vec2 direction = from_center / distance_out;
    return position + direction * RIPPLE_HEIGHT * strength * wave / media_shape;
}

float random(vec2 seed) {
    return fract(sin(dot(seed, vec2(12.9898, 78.233))) * 43758.5453);
}

// Folds the picture into mirrored wedges around the center. Holds, then melts back.
vec2 mirrored(vec2 position) {
    vec2 from_center = (position - 0.5) * media_shape;
    float distance_out = length(from_center);
    if (mirror_progress == 0.0 || distance_out == 0.0) {
        return position;
    }
    float wedge = TAU / MIRROR_WEDGES;
    float angle = abs(mod(atan(from_center.y, from_center.x), wedge) - wedge * 0.5);
    vec2 folded = distance_out * vec2(cos(angle), sin(angle)) / media_shape + 0.5;
    // Wedges can reach past the picture's sides, so reflect them back in.
    folded = 1.0 - abs(mod(folded, 2.0) - 1.0);
    return mix(position, folded, 1.0 - smoothstep(0.5, 1.0, mirror_progress));
}

// Like the mirror burst, but with eight turning wedges and a zoom in, folding in
// quickly and unfolding again.
vec2 kaleidoscoped(vec2 position) {
    vec2 from_center = (position - 0.5) * media_shape;
    float distance_out = length(from_center);
    if (kaleidoscope_progress == 0.0 || distance_out == 0.0) {
        return position;
    }
    float amount = smoothstep(0.0, 0.2, kaleidoscope_progress)
        * (1.0 - smoothstep(0.6, 1.0, kaleidoscope_progress));
    float wedge = TAU / KALEIDOSCOPE_WEDGES;
    float turned = atan(from_center.y, from_center.x) + kaleidoscope_progress * wedge;
    float angle = abs(mod(turned, wedge) - wedge * 0.5);
    float reach = distance_out * (1.0 - KALEIDOSCOPE_ZOOM * amount);
    vec2 folded = reach * vec2(cos(angle), sin(angle)) / media_shape + 0.5;
    folded = 1.0 - abs(mod(folded, 2.0) - 1.0);
    return mix(position, folded, amount);
}

// Turns a little, swings back past the start, and settles, like a spring. It zooms in
// by just enough that the corners of the turned picture never show.
vec2 spun(vec2 position) {
    if (spin_progress == 0.0) {
        return position;
    }
    float angle = SPIN_ANGLE * sin(spin_progress * TAU * 1.5) * pow(1.0 - spin_progress, 2.0);
    float cover = abs(cos(angle))
        + abs(sin(angle)) * max(media_shape.x / media_shape.y, media_shape.y / media_shape.x);
    vec2 from_center = (position - 0.5) * media_shape;
    float c = cos(angle);
    float s = sin(angle);
    vec2 turned = vec2(c * from_center.x - s * from_center.y, s * from_center.x + c * from_center.y);
    return turned / cover / media_shape + 0.5;
}

// Cuts the picture into bands that jump sideways, every other one the opposite
// way, then slide back. What slides off one side comes back on the other.
vec2 sliced(vec2 position) {
    if (slice_progress == 0.0) {
        return position;
    }
    float band = floor(position.y * SLICE_BANDS);
    float direction = mod(band, 2.0) == 0.0 ? 1.0 : -1.0;
    float shift = direction * SLICE_SHIFT * pow(1.0 - slice_progress, 2.0);
    return vec2(fract(position.x + shift), position.y);
}

vec2 zoomed(vec2 position) {
    if (zoom_progress == 0.0) {
        return position;
    }
    float strength = pow(1.0 - zoom_progress, 3.0);
    return 0.5 + (position - 0.5) / (1.0 + ZOOM_AMOUNT * strength);
}

// Zooms in by exactly as much as the picture moves, so that its edges never show.
vec2 shaken(vec2 position) {
    if (shake_progress == 0.0) {
        return position;
    }
    float strength = pow(1.0 - shake_progress, 2.0);
    vec2 reach = SHAKE_SIZE * strength / media_shape;
    vec2 wobble = vec2(sin(shake_progress * 47.0), cos(shake_progress * 61.0));
    return 0.5 + (position - 0.5) * (1.0 - 2.0 * reach) + reach * wobble;
}

// Slides random rows of the picture sideways, wrapping around at the edges.
vec2 glitched(vec2 position) {
    if (glitch_progress == 0.0) {
        return position;
    }
    float moment = floor(glitch_progress * GLITCH_STEPS) + glitch_seed;
    float rows = 8.0 + floor(random(vec2(moment, 1.0)) * 24.0);
    float row = floor(position.y * rows);
    if (random(vec2(row, moment)) < 0.5) {
        return position;
    }
    float shift = (random(vec2(row, moment + 0.5)) - 0.5) * GLITCH_SHIFT;
    return vec2(fract(position.x + shift), position.y);
}

// How far apart to read red and blue here, with green in the middle.
vec2 color_split(vec2 position) {
    vec2 split = vec2(0.0);
    if (glitch_progress > 0.0) {
        split.x += GLITCH_SPLIT / media_shape.x;
    }
    vec2 from_center = (position - 0.5) * media_shape;
    float distance_out = length(from_center);
    if (shockwave_progress > 0.0 && distance_out > 0.0) {
        float behind_front = distance_out - shockwave_progress * length(media_shape * 0.5);
        float wave = exp(-behind_front * behind_front / (SHOCKWAVE_WIDTH * SHOCKWAVE_WIDTH));
        vec2 direction = from_center / distance_out;
        split += direction * SHOCKWAVE_SPLIT * wave * (1.0 - shockwave_progress) / media_shape;
    }
    return split;
}

vec3 pixelated(vec2 read_at) {
    if (block_size.x == 0.0) {
        return texture(image, read_at).rgb;
    }
    vec2 block = floor(read_at / block_size);
    vec3 sum = vec3(0.0);
    for (int y = 0; y < SAMPLES; y++) {
        for (int x = 0; x < SAMPLES; x++) {
            vec2 position = (vec2(x, y) + 0.5) / float(SAMPLES);
            sum += texture(image, (block + position) * block_size).rgb;
        }
    }
    return sum / float(SAMPLES * SAMPLES);
}

// Smaller and smaller copies of the picture on top of it, which shrink towards the
// center and fade.
vec3 tunnelled(vec3 rgb, vec2 read_at) {
    if (tunnel_progress == 0.0) {
        return rgb;
    }
    float fade = 0.6 * (1.0 - tunnel_progress);
    float scale = 1.0 + tunnel_progress;
    for (int i = 1; i <= TUNNEL_COPIES; i++) {
        scale *= TUNNEL_SPACING;
        vec2 copy_at = 0.5 + (read_at - 0.5) * scale;
        if (all(greaterThanEqual(copy_at, vec2(0.0))) && all(lessThanEqual(copy_at, vec2(1.0)))) {
            rgb = mix(rgb, pixelated(copy_at), fade);
        }
    }
    return rgb;
}

// Turns every color once around the color wheel, about the grey axis, so greys and
// brightness stay the same.
vec3 hue_spun(vec3 rgb) {
    if (hue_progress == 0.0) {
        return rgb;
    }
    float angle = TAU * smoothstep(0.0, 1.0, hue_progress);
    vec3 axis = vec3(0.57735);
    float c = cos(angle);
    return clamp(rgb * c + cross(axis, rgb) * sin(angle) + axis * dot(axis, rgb) * (1.0 - c),
                 0.0, 1.0);
}

void main() {
    vec2 read_at = sliced(glitched(rippled(shaken(spun(zoomed(kaleidoscoped(mirrored(uv))))))));
    vec2 split = color_split(read_at);
    vec3 rgb = pixelated(read_at);
    if (split != vec2(0.0)) {
        rgb = vec3(pixelated(read_at + split).r, rgb.g, pixelated(read_at - split).b);
    }
    rgb = tunnelled(rgb, read_at);
    rgb = hue_spun(rgb);
    rgb *= channels;
    if (black_and_white) {
        rgb = vec3(dot(rgb, BRIGHTNESS_WEIGHTS));
    }
    if (vignette_progress > 0.0) {
        vec2 from_center = (uv - 0.5) * media_shape;
        float edge = smoothstep(0.3, 1.0, length(from_center) / length(media_shape * 0.5));
        rgb *= 1.0 - VIGNETTE_DARKNESS * edge * pow(1.0 - vignette_progress, 2.0);
    }
    if (invert_progress > 0.0) {
        rgb = mix(rgb, 1.0 - rgb, pow(1.0 - invert_progress, 2.0));
    }
    if (flash_progress > 0.0) {
        rgb = mix(rgb, vec3(1.0), pow(1.0 - flash_progress, 2.0));
    }
    color = vec4(rgb, 1.0);
}
"""


def configure_opengl() -> None:
    """Request the OpenGL version the shaders need. Call before QApplication."""
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(surface)


def centered(amount: float) -> float:
    """Convert a control position from 0.0-1.0 to -1.0-1.0, with a dead zone at 0.0."""
    low = 0.5 - CENTER_DEAD_ZONE
    high = 0.5 + CENTER_DEAD_ZONE
    if amount < low:
        return amount / low - 1.0
    if amount > high:
        return (amount - high) / (1.0 - high)
    return 0.0


def saturation_from_slider(amount: float) -> float:
    """Convert a slider position from 0.0-1.0 to a saturation factor."""
    position = centered(amount)
    return 1.0 + (position if position < 0 else position * (MAX_SATURATION - 1.0))


def playback_speed_from_control(amount: float) -> float:
    """Convert a control position from 0.0-1.0 to a speed from x0.25 to x4.

    The center's dead zone covers MIDI values 60-67, which all play at normal speed.
    Each equal move of the control multiplies the speed by the same amount, so x0.5
    and x2 sit halfway out on each side.
    """
    return MAX_PLAYBACK_SPEED ** centered(amount)


class MediaView(QOpenGLWidget):
    playback_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._source: ImageSource | VideoSource | None = None
        self._new_pixels: np.ndarray | None = None
        self._blur = 0.0
        self._pixelate = 0.0
        self._saturation = [1.0] * SATURATION_BANDS
        # Per channel (red, green, blue): horizontal and vertical, from -1.0 to 1.0.
        self._rgb_shift = [[0.0, 0.0] for _ in range(3)]
        self._animations: dict[Effect, float] = {}  # Those playing, and when each started.
        self._glitch_seed = 0.0
        self._recent_frames: deque[np.ndarray] = deque(maxlen=STUTTER_FRAMES)
        # The frames being repeated, while a stutter plays.
        self._stutter_frames: list[np.ndarray] | None = None
        self._stutter_start = 0.0
        self._stutter_step = 0
        self._black_and_white = False
        self._channels = [1.0, 1.0, 1.0]
        self._playback_speed = 1.0
        self._ctx: moderngl.Context | None = None
        self._screen: moderngl.Framebuffer | None = None
        self._blur_program: moderngl.Program | None = None
        self._blur_quad: moderngl.VertexArray | None = None
        self._display_program: moderngl.Program | None = None
        self._display_quad: moderngl.VertexArray | None = None
        self._saturation_program: moderngl.Program | None = None
        self._saturation_quad: moderngl.VertexArray | None = None
        self._rgb_shift_program: moderngl.Program | None = None
        self._rgb_shift_quad: moderngl.VertexArray | None = None
        self._texture: moderngl.Texture | None = None
        # One texture and framebuffer per blur direction.
        self._blur_textures: list[moderngl.Texture] = []
        self._blur_targets: list[moderngl.Framebuffer] = []
        self._saturation_texture: moderngl.Texture | None = None
        self._saturation_target: moderngl.Framebuffer | None = None
        self._rgb_shift_texture: moderngl.Texture | None = None
        self._rgb_shift_target: moderngl.Framebuffer | None = None

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def set_source(self, source: ImageSource | VideoSource) -> None:
        self.stop()
        self._source = source
        self._new_pixels = None
        # The control stays where it was, so a new file plays at that speed too.
        self._apply_playback_speed()

    def set_playback_speed(self, amount: float) -> None:
        """Set the speed from a control position from 0.0 to 1.0, where 0.5 is normal."""
        self._playback_speed = playback_speed_from_control(amount)
        self._apply_playback_speed()

    def _apply_playback_speed(self) -> None:
        if self._source is not None:
            self._source.set_speed(self._playback_speed, time.monotonic())

    def set_blur(self, amount: float) -> None:
        """Set the blur strength from 0.0 (none) to 1.0 (maximum)."""
        self._blur = amount
        self.update()

    def set_pixelate(self, amount: float) -> None:
        """Set the pixelation from 0.0 (none) to 1.0 (largest blocks)."""
        self._pixelate = amount
        self.update()

    def set_saturation(self, band: int, amount: float) -> None:
        """Set one color band's slider position from 0.0 to 1.0, where 0.5 is unchanged."""
        self._saturation[band] = saturation_from_slider(amount)
        self.update()

    def set_rgb_shift(self, channel: int, axis: int, amount: float) -> None:
        """Shift one color channel (0-2) along one axis (0 horizontal, 1 vertical).

        A control position of 0.5 is unshifted. Lower is left or down, higher is right or up.
        """
        self._rgb_shift[channel][axis] = centered(amount)
        self.update()

    def start_animation(self, effect: Effect) -> None:
        """Play one of the ANIMATIONS. Another press restarts it."""
        if self._source is not None:
            self._animations[effect] = time.monotonic()
            if effect is Effect.GLITCH_BURST:
                self._glitch_seed = random.uniform(0.0, 100.0)

    def _animation_progress(self, effect: Effect) -> float:
        """How far along an animation is, from 0.0 to 1.0, or 0.0 when it isn't playing."""
        start = self._animations.get(effect)
        if start is None:
            return 0.0
        progress = (time.monotonic() - start) / ANIMATIONS[effect][1]
        if progress >= 1.0:
            del self._animations[effect]
            return 0.0
        return progress

    def start_stutter(self) -> None:
        """Repeat the latest frames for a moment. The video carries on unseen meanwhile.

        Another press restarts it from wherever the video has got to.
        """
        if len(self._recent_frames) < 2:
            return  # Nothing to repeat yet, or a still image.
        self._stutter_frames = list(self._recent_frames)
        self._stutter_start = time.monotonic()
        self._stutter_step = -1

    def _frame_to_show(self, latest: np.ndarray | None) -> np.ndarray | None:
        """The frame to put on screen now, given the source's latest, or None to keep what's there."""
        if self._stutter_frames is None:
            return latest
        elapsed = time.monotonic() - self._stutter_start
        if elapsed >= STUTTER_SECONDS:
            self._stutter_frames = None
            return self._recent_frames[-1]
        step = int(elapsed / STUTTER_STEP_SECONDS)
        if step == self._stutter_step:
            return None
        self._stutter_step = step
        return self._stutter_frames[step % len(self._stutter_frames)]

    def toggle_black_and_white(self) -> None:
        self._black_and_white = not self._black_and_white
        self.update()

    def toggle_channel(self, channel: int) -> None:
        """Remove a color channel (0 red, 1 green, 2 blue), or add it back."""
        self._channels[channel] = 1.0 - self._channels[channel]
        self.update()

    def turn_off_toggles(self, effects: set[Effect]) -> None:
        """Turn off any of these toggle effects that are on. Others are left alone."""
        if Effect.BLACK_AND_WHITE in effects:
            self._black_and_white = False
        for channel, effect in enumerate(REMOVE_CHANNEL_EFFECTS):
            if effect in effects:
                self._channels[channel] = 1.0
        self.update()

    def toggle_pause(self) -> bool | None:
        """Pause or resume, and return whether it's now paused, or None if that doesn't apply."""
        if self._source is None:
            return None
        return self._source.toggle_pause(time.monotonic())

    def is_paused(self) -> bool:
        return self._source is not None and self._source.paused

    def reset_effects(self) -> None:
        """Turn every effect off, leaving the original picture."""
        self._blur = 0.0
        self._pixelate = 0.0
        self._saturation = [1.0] * SATURATION_BANDS
        self._rgb_shift = [[0.0, 0.0] for _ in range(3)]
        self._animations.clear()
        if self._stutter_frames is not None:
            self._stutter_frames = None
            self._new_pixels = self._recent_frames[-1]
        self._black_and_white = False
        self._channels = [1.0, 1.0, 1.0]
        self._playback_speed = 1.0
        self._apply_playback_speed()
        self.update()

    def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
            self._source = None
        self._recent_frames.clear()
        self._stutter_frames = None

    def _fail(self, reason: str) -> None:
        """Stop playback for good, so one failure is reported only once."""
        self.stop()
        self._new_pixels = None
        self.playback_failed.emit(reason)

    def _poll(self) -> None:
        # An animation needs drawing every frame, even on an image or a paused video.
        if self._animations:
            self.update()
        if self._source is None:
            return
        try:
            if self._source.error is not None:
                self._fail(self._source.error)
                return
            pixels = self._source.next_frame(time.monotonic())
        except Exception:
            log.exception("Reading the next frame failed")
            self._fail("an unexpected error occurred while reading it")
            return
        if pixels is not None:
            self._recent_frames.append(pixels)
        pixels = self._frame_to_show(pixels)
        if pixels is not None:
            self._new_pixels = pixels
            self.update()

    def initializeGL(self) -> None:
        self._ctx = moderngl.create_context(require=330)
        corners = self._ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
        self._saturation_program, self._saturation_quad = self._build_pass(
            corners, SATURATION_SHADER, flip_y=False
        )
        self._rgb_shift_program, self._rgb_shift_quad = self._build_pass(
            corners, RGB_SHIFT_SHADER, flip_y=False
        )
        self._blur_program, self._blur_quad = self._build_pass(corners, BLUR_SHADER, flip_y=False)
        self._display_program, self._display_quad = self._build_pass(
            corners, DISPLAY_SHADER, flip_y=True
        )

    def _build_pass(
        self, corners: moderngl.Buffer, fragment_shader: str, flip_y: bool
    ) -> tuple[moderngl.Program, moderngl.VertexArray]:
        program = self._ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=fragment_shader)
        program["flip_y"].value = flip_y
        return program, self._ctx.vertex_array(program, [(corners, "2f", "position")])

    def resizeGL(self, width: int, height: int) -> None:
        # Qt replaces its framebuffer on resize, so look it up again.
        self._screen = self._ctx.detect_framebuffer(self.defaultFramebufferObject())

    def paintGL(self) -> None:
        try:
            self._render()
        except Exception:
            log.exception("Drawing a frame failed")
            self._fail("an unexpected error occurred while displaying it")

    def _render(self) -> None:
        if self._new_pixels is not None:
            self._upload(self._new_pixels)
            self._new_pixels = None

        if self._texture is None:
            self._screen.use()
            self._screen.clear(0.0, 0.0, 0.0, 1.0)
            return

        width, height = self._texture.size
        source = self._texture
        if any(factor != 1.0 for factor in self._saturation):
            self._saturation_target.use()
            self._saturation_program["saturation"].value = tuple(self._saturation)
            source.use(0)
            self._saturation_quad.render(moderngl.TRIANGLE_STRIP)
            source = self._saturation_texture

        if any(amount != 0.0 for channel in self._rgb_shift for amount in channel):
            self._rgb_shift_target.use()
            for name, shift in zip(("red", "green", "blue"), self._rgb_shift):
                self._rgb_shift_program[f"{name}_offset"].value = self._rgb_shift_offset(shift)
            source.use(0)
            self._rgb_shift_quad.render(moderngl.TRIANGLE_STRIP)
            source = self._rgb_shift_texture

        sigma = self._blur * MAX_BLUR_SIGMA * min(width, height)
        if sigma > 0:
            self._blur_pass(source, 0, (1 / width, 0.0), sigma)
            self._blur_pass(self._blur_textures[0], 1, (0.0, 1 / height), sigma)
            source = self._blur_textures[1]

        block_size = (0.0, 0.0)
        if self._pixelate > 0:
            pixels = max(MIN_PIXEL_SIZE, round(self._pixelate * MAX_PIXEL_SIZE * min(width, height)))
            block_size = (pixels / width, pixels / height)

        self._screen.use()
        self._screen.clear(0.0, 0.0, 0.0, 1.0)
        self._screen.viewport = self._letterbox()
        self._display_program["block_size"].value = block_size
        for effect, (progress_name, _seconds) in ANIMATIONS.items():
            self._display_program[progress_name].value = self._animation_progress(effect)
        self._display_program["glitch_seed"].value = self._glitch_seed
        self._display_program["channels"].value = tuple(self._channels)
        self._display_program["black_and_white"].value = self._black_and_white
        shorter_side = min(width, height)
        self._display_program["media_shape"].value = (width / shorter_side, height / shorter_side)
        source.use(0)
        self._display_quad.render(moderngl.TRIANGLE_STRIP)

    def _rgb_shift_offset(self, shift: list[float]) -> tuple[float, float]:
        """The offset for the shader, in whole media pixels so that the picture stays sharp."""
        width, height = self._texture.size
        largest = MAX_RGB_SHIFT * min(width, height)
        # Rows run from the top of the picture here, so moving up is a negative offset.
        return round(shift[0] * largest) / width, -round(shift[1] * largest) / height

    def _blur_pass(
        self,
        source: moderngl.Texture,
        target: int,
        texel_step: tuple[float, float],
        sigma: float,
    ) -> None:
        self._blur_targets[target].use()
        self._blur_program["texel_step"].value = texel_step
        self._blur_program["sigma"].value = sigma
        source.use(0)
        self._blur_quad.render(moderngl.TRIANGLE_STRIP)

    def _upload(self, pixels: np.ndarray) -> None:
        height, width, _ = pixels.shape
        if self._texture is None or self._texture.size != (width, height):
            self._create_textures(width, height)
        self._texture.write(pixels)

    def _create_textures(self, width: int, height: int) -> None:
        for resource in (
            *self._blur_targets,
            *self._blur_textures,
            self._saturation_target,
            self._saturation_texture,
            self._rgb_shift_target,
            self._rgb_shift_texture,
            self._texture,
        ):
            if resource is not None:
                resource.release()
        self._texture = self._ctx.texture((width, height), 3, alignment=1)
        # Floating point keeps smooth gradients from banding between the passes.
        self._saturation_texture = self._ctx.texture((width, height), 4, dtype="f2")
        self._saturation_target = self._ctx.framebuffer(color_attachments=[self._saturation_texture])
        self._rgb_shift_texture = self._ctx.texture((width, height), 4, dtype="f2")
        self._rgb_shift_target = self._ctx.framebuffer(color_attachments=[self._rgb_shift_texture])
        self._blur_textures = [self._ctx.texture((width, height), 4, dtype="f2") for _ in range(2)]
        self._blur_targets = [
            self._ctx.framebuffer(color_attachments=[texture]) for texture in self._blur_textures
        ]
        for texture in (
            self._texture,
            self._saturation_texture,
            self._rgb_shift_texture,
            *self._blur_textures,
        ):
            texture.repeat_x = False
            texture.repeat_y = False

    def _letterbox(self) -> tuple[int, int, int, int]:
        """The largest centered rectangle with the media's aspect ratio."""
        ratio = self.devicePixelRatioF()
        view_width, view_height = round(self.width() * ratio), round(self.height() * ratio)
        media_width, media_height = self._texture.size
        scale = min(view_width / media_width, view_height / media_height)
        width, height = round(media_width * scale), round(media_height * scale)
        return (view_width - width) // 2, (view_height - height) // 2, width, height
