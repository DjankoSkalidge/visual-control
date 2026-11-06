from enum import Enum, auto


class Effect(Enum):
    """What a controller can drive, independent of any particular controller."""

    BLUR = auto()
    PIXELATE = auto()
    SATURATION_RED = auto()
    SATURATION_YELLOW = auto()
    SATURATION_GREEN = auto()
    SATURATION_CYAN = auto()
    SATURATION_BLUE = auto()
    SATURATION_MAGENTA = auto()
    RGB_SHIFT_RED_HORIZONTAL = auto()
    RGB_SHIFT_RED_VERTICAL = auto()
    RGB_SHIFT_GREEN_HORIZONTAL = auto()
    RGB_SHIFT_GREEN_VERTICAL = auto()
    RGB_SHIFT_BLUE_HORIZONTAL = auto()
    RGB_SHIFT_BLUE_VERTICAL = auto()
    PLAYBACK_SPEED = auto()
    PAUSE = auto()
    RIPPLE = auto()
    ZOOM_PUNCH = auto()
    GLITCH_BURST = auto()
    FLASH = auto()
    SHAKE = auto()
    COLOR_SHOCKWAVE = auto()
    MIRROR_BURST = auto()
    INVERT_FLASH = auto()
    STROBE_SLICE = auto()
    KALEIDOSCOPE_POP = auto()
    TUNNEL_ZOOM = auto()
    VIGNETTE_PULSE = auto()
    SPIN_KICK = auto()
    HUE_SPIN = auto()
    STUTTER = auto()
    BLACK_AND_WHITE = auto()
    REMOVE_RED = auto()
    REMOVE_GREEN = auto()
    REMOVE_BLUE = auto()


# These respond to a press, instead of following a control's position. They can
# also be assigned to buttons and pads that send notes.
PRESS_EFFECTS = frozenset({
    Effect.PAUSE,
    Effect.RIPPLE,
    Effect.ZOOM_PUNCH,
    Effect.GLITCH_BURST,
    Effect.FLASH,
    Effect.SHAKE,
    Effect.COLOR_SHOCKWAVE,
    Effect.MIRROR_BURST,
    Effect.INVERT_FLASH,
    Effect.STROBE_SLICE,
    Effect.KALEIDOSCOPE_POP,
    Effect.TUNNEL_ZOOM,
    Effect.VIGNETTE_PULSE,
    Effect.SPIN_KICK,
    Effect.HUE_SPIN,
    Effect.STUTTER,
    Effect.BLACK_AND_WHITE,
    Effect.REMOVE_RED,
    Effect.REMOVE_GREEN,
    Effect.REMOVE_BLUE,
})

# In channel order: red, green, blue.
REMOVE_CHANNEL_EFFECTS = (Effect.REMOVE_RED, Effect.REMOVE_GREEN, Effect.REMOVE_BLUE)

# In order around the color wheel, which is the order the saturation shader expects.
SATURATION_EFFECTS = (
    Effect.SATURATION_RED,
    Effect.SATURATION_YELLOW,
    Effect.SATURATION_GREEN,
    Effect.SATURATION_CYAN,
    Effect.SATURATION_BLUE,
    Effect.SATURATION_MAGENTA,
)

# Per channel (red, green, blue): the horizontal effect, then the vertical one.
RGB_SHIFT_EFFECTS = (
    (Effect.RGB_SHIFT_RED_HORIZONTAL, Effect.RGB_SHIFT_RED_VERTICAL),
    (Effect.RGB_SHIFT_GREEN_HORIZONTAL, Effect.RGB_SHIFT_GREEN_VERTICAL),
    (Effect.RGB_SHIFT_BLUE_HORIZONTAL, Effect.RGB_SHIFT_BLUE_VERTICAL),
)
