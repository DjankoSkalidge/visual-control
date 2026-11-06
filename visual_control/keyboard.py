"""Loads and saves the keyboard setup, which assigns keys to press effects."""

from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from .controllers.config import ConfigError, _read_yaml
from .effects import PRESS_EFFECTS, Effect

KEYBOARD_FILE_NAME = "keyboard.yaml"
# Esc leaves fullscreen and cancels in setup windows, so it can't trigger an effect.
RESERVED_KEYS = frozenset({Qt.Key.Key_Escape.value})
# Pressed alone, these change other keys rather than being keys of their own.
MODIFIER_KEYS = frozenset(key.value for key in (
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Meta,
    Qt.Key.Key_Alt,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
    Qt.Key.Key_Super_L,
    Qt.Key.Key_Super_R,
    Qt.Key.Key_Hyper_L,
    Qt.Key.Key_Hyper_R,
))
# Keys held with one of these belong to the system or other apps, like Ctrl+Q.
SHORTCUT_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)
KEYBOARD_EFFECTS = tuple(e for e in Effect if e in PRESS_EFFECTS)

_EFFECTS_BY_NAME = {effect.name.lower(): effect for effect in KEYBOARD_EFFECTS}


def keyboard_file(user_folder: Path) -> Path:
    """The keyboard setup sits next to the folder of controller setups."""
    return user_folder.parent / KEYBOARD_FILE_NAME


def can_assign(key: int) -> bool:
    return key not in RESERVED_KEYS and key not in MODIFIER_KEYS and key != Qt.Key.Key_unknown.value


def describe_key(key: int) -> str:
    """The key's name, like "Q", "Space" or "F5"."""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def _key_text(key: int) -> str:
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)


def _parse_key(text: object, effect_name: str, path: Path) -> int:
    problem = f'{path.name}: "{effect_name}" must be a single key, like Q, Space or F5'
    # A number like 1 is read from YAML as an int, but it's the 1 key.
    if isinstance(text, int) and not isinstance(text, bool):
        text = str(text)
    if not isinstance(text, str) or not text.strip():
        raise ConfigError(problem)
    sequence = QKeySequence.fromString(text.strip(), QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1:
        raise ConfigError(problem)
    combination = sequence[0]
    key = combination.key()
    if combination.keyboardModifiers() != Qt.KeyboardModifier.NoModifier or not can_assign(key):
        raise ConfigError(problem)
    return key.value


def load_keyboard(path: Path) -> dict[Effect, int]:
    """Effect -> Qt key. A missing file means nothing is assigned."""
    if not path.exists():
        return {}
    data = _read_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("effects", {}), dict):
        raise ConfigError(f'{path.name}: "effects" must list press effects and keys')
    effects: dict[Effect, int] = {}
    effect_on_key: dict[int, str] = {}
    for effect_name, text in (data.get("effects") or {}).items():
        effect = _EFFECTS_BY_NAME.get(effect_name)
        if effect is None:
            raise ConfigError(f'{path.name}: "{effect_name}" isn\'t a press effect')
        key = _parse_key(text, effect_name, path)
        if key in effect_on_key:
            raise ConfigError(
                f'{path.name}: {describe_key(key)} is assigned to both '
                f'"{effect_on_key[key]}" and "{effect_name}"'
            )
        effect_on_key[key] = effect_name
        effects[effect] = key
    return effects


def save_keyboard(effects: dict[Effect, int], path: Path) -> None:
    """Raises OSError if it can't be written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "effects": {
            effect.name.lower(): _key_text(effects[effect])
            for effect in KEYBOARD_EFFECTS
            if effect in effects
        }
    }
    # Write to one side first, so a failure can't leave a half-written file behind.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "# Created by Visual Control. Effect: key\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)
