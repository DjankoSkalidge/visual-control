"""Loads controller configuration files, which assign controls to effects."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..effects import PRESS_EFFECTS, Effect

BUILT_IN_FOLDER = Path(__file__).parent
# Controllers the user configures live outside the app, because an AppImage is read-only.
USER_FOLDER = (
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    / "visual-control"
    / "controllers"
)
MAX_CONTROL_NUMBER = 127  # Also the highest note number.

# These names are stored in users' files, so renaming an Effect would break them.
_EFFECTS_BY_NAME = {effect.name.lower(): effect for effect in Effect}


@dataclass(frozen=True)
class Note:
    """A button or pad that sends notes. A plain int is a control change number."""

    number: int


def describe_control(control: int | Note) -> str:
    return f"note {control.number}" if isinstance(control, Note) else f"control {control}"


@dataclass(frozen=True)
class Controller:
    name: str  # Shown in the status bar.
    port_match: str  # Text to find in the MIDI port name.
    effects: dict[Effect, int | Note]  # Effect -> what triggers it.


class ConfigError(Exception):
    """A controller file can't be used. The message names the file and the problem."""


class _StrictLoader(yaml.SafeLoader):
    """Rejects repeated keys, which YAML would otherwise silently resolve to the last one."""

    def construct_mapping(self, node, deep=False):
        seen = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f'"{key}" appears twice', key_node.start_mark
                )
            seen.append(key)
        return super().construct_mapping(node, deep)


def _read_yaml(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as file:
            return yaml.load(file, Loader=_StrictLoader)
    except yaml.MarkedYAMLError as exc:
        line = exc.problem_mark.line + 1 if exc.problem_mark else "?"
        raise ConfigError(f"{path.name}: {exc.problem} on line {line}") from exc
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name}: can't read the file") from exc


def _text_field(data: dict, field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f'{path.name}: "{field}" must be some text')
    return value


def _is_midi_number(value: object) -> bool:
    # bool counts as an int in Python, but "blur: true" isn't a control number.
    valid_type = isinstance(value, int) and not isinstance(value, bool)
    return valid_type and 0 <= value <= MAX_CONTROL_NUMBER


def _parse_control(value: object, effect: Effect, effect_name: str, path: Path) -> int | Note:
    if _is_midi_number(value):
        return value
    if effect in PRESS_EFFECTS:
        if isinstance(value, dict) and value.keys() == {"note"} and _is_midi_number(value["note"]):
            return Note(value["note"])
        raise ConfigError(
            f'{path.name}: "{effect_name}" must be a number from 0 to {MAX_CONTROL_NUMBER}, '
            f"or a note like {{note: 36}}"
        )
    raise ConfigError(
        f'{path.name}: "{effect_name}" must be a number from 0 to {MAX_CONTROL_NUMBER}'
    )


def load_controller(path: Path) -> Controller:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f'{path.name}: expected "name", "port" and "effects"')
    name = _text_field(data, "name", path)
    port = _text_field(data, "port", path)
    assignments = data.get("effects")
    if not isinstance(assignments, dict):
        raise ConfigError(f'{path.name}: "effects" must list effects and control numbers')

    effects: dict[Effect, int | Note] = {}
    effect_on_control: dict[int | Note, str] = {}
    for effect_name, value in assignments.items():
        effect = _EFFECTS_BY_NAME.get(effect_name)
        if effect is None:
            raise ConfigError(f'{path.name}: unknown effect "{effect_name}"')
        control = _parse_control(value, effect, effect_name, path)
        if control in effect_on_control:
            raise ConfigError(
                f"{path.name}: {describe_control(control)} is assigned to both "
                f'"{effect_on_control[control]}" and "{effect_name}"'
            )
        effect_on_control[control] = effect_name
        effects[effect] = control
    return Controller(name, port, effects)


def load_controllers(folder: Path = BUILT_IN_FOLDER) -> tuple[list[Controller], list[str]]:
    """Load every file in a folder. One bad file doesn't stop the others from working."""
    controllers: list[Controller] = []
    errors: list[str] = []
    paths = sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")])
    for path in paths:
        try:
            controller = load_controller(path)
        except ConfigError as exc:
            errors.append(str(exc))
            continue
        # The status bar tracks controllers by name, so names must be unique.
        if any(existing.name == controller.name for existing in controllers):
            errors.append(f'{path.name}: another controller is already named "{controller.name}"')
            continue
        controllers.append(controller)
    return controllers, errors


def _same_device(port_a: str, port_b: str) -> bool:
    return port_a in port_b or port_b in port_a


def replaces(new: Controller, existing: Controller) -> bool:
    """Whether saving a controller takes over from an existing one.

    Each device gets one controller, because two would both react to its controls.
    """
    return new.name == existing.name or _same_device(new.port_match, existing.port_match)


def merge_controllers(built_in: list[Controller], user: list[Controller]) -> list[Controller]:
    """Combine the two lists, where a user's controller takes priority over a built-in one."""
    kept = [c for c in built_in if not any(replaces(mine, c) for mine in user)]
    return [*kept, *user]


def load_all_controllers(user_folder: Path) -> tuple[list[Controller], list[str]]:
    built_in, built_in_errors = load_controllers(BUILT_IN_FOLDER)
    user, user_errors = load_controllers(user_folder)
    return merge_controllers(built_in, user), [*built_in_errors, *user_errors]


def _file_name_for(name: str, folder: Path) -> Path:
    stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "controller"
    path = folder / f"{stem}.yaml"
    suffix = 2
    while path.exists():
        path = folder / f"{stem}_{suffix}.yaml"
        suffix += 1
    return path


def save_controller(controller: Controller, folder: Path) -> Path:
    """Write a controller file, replacing any file it takes over from.

    Raises OSError if it can't be written. Unreadable files are left alone.
    """
    folder.mkdir(parents=True, exist_ok=True)
    replaced = []
    for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
        try:
            if replaces(controller, load_controller(path)):
                replaced.append(path)
        except ConfigError:
            pass

    target = replaced[0] if replaced else _file_name_for(controller.name, folder)
    data = {
        "name": controller.name,
        "port": controller.port_match,
        "effects": {
            effect.name.lower(): {"note": control.number} if isinstance(control, Note) else control
            for effect, control in controller.effects.items()
        },
    }
    # Write to one side first, so a failure can't leave a half-written file behind.
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        "# Created by Visual Control. Effect: control number\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(target)
    for path in replaced[1:]:
        path.unlink()
    return target
