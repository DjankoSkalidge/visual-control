import tempfile
import unittest
from pathlib import Path

from visual_control.controllers.config import (
    ConfigError,
    Controller,
    Note,
    load_controller,
    load_controllers,
    merge_controllers,
    save_controller,
)
from visual_control.effects import PRESS_EFFECTS, Effect

GOOD = """
name: Test Controller
port: Test Port
effects:
  blur: 16
  pixelate: 20
"""


class BuiltInControllerTests(unittest.TestCase):
    def setUp(self):
        self.controllers, self.errors = load_controllers()

    def effects_of(self, name):
        controller = next(c for c in self.controllers if c.name == name)
        return {effect.name.lower(): control for effect, control in controller.effects.items()}

    def test_all_load_without_errors(self):
        self.assertEqual(self.errors, [])
        self.assertEqual([c.name for c in self.controllers], ["Akai MIDI Mix", "Oxygen"])
        self.assertEqual([c.port_match for c in self.controllers], ["MIDI Mix", "Oxygen"])

    def test_akai_assignments(self):
        self.assertEqual(self.effects_of("Akai MIDI Mix"), {
            "blur": 16, "pixelate": 20,
            "saturation_red": 19, "saturation_yellow": 23, "saturation_green": 27,
            "saturation_cyan": 31, "saturation_blue": 49, "saturation_magenta": 53,
            "rgb_shift_red_horizontal": 24, "rgb_shift_red_vertical": 28,
            "rgb_shift_green_horizontal": 46, "rgb_shift_green_vertical": 50,
            "rgb_shift_blue_horizontal": 54, "rgb_shift_blue_vertical": 58,
        })

    def test_oxygen_assignments(self):
        self.assertEqual(self.effects_of("Oxygen"), {
            "blur": 22, "pixelate": 23,
            "saturation_red": 20, "saturation_yellow": 21, "saturation_green": 71,
            "saturation_cyan": 72, "saturation_blue": 25, "saturation_magenta": 73,
            "rgb_shift_red_horizontal": 61, "rgb_shift_red_vertical": 24,
            "rgb_shift_green_horizontal": 26, "rgb_shift_green_vertical": 27,
            "rgb_shift_blue_horizontal": 62, "rgb_shift_blue_vertical": 95,
        })

    def test_every_effect_is_assigned_so_none_can_be_forgotten(self):
        # Toggles are left for users to assign to a button of their choice, and playback
        # speed to whichever slider or rotary encoder they like.
        left_to_users = PRESS_EFFECTS | {Effect.PLAYBACK_SPEED}
        for controller in self.controllers:
            self.assertEqual(set(controller.effects), set(Effect) - left_to_users, controller.name)


class LoadingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def write(self, text: str, name: str = "mine.yaml") -> Path:
        path = self.dir / name
        path.write_text(text)
        return path

    def assert_rejected(self, text: str, reason: str) -> None:
        with self.assertRaisesRegex(ConfigError, f"mine.yaml: .*{reason}"):
            load_controller(self.write(text))

    def test_good_file(self):
        controller = load_controller(self.write(GOOD))
        self.assertEqual(controller.name, "Test Controller")
        self.assertEqual(controller.port_match, "Test Port")
        self.assertEqual(controller.effects, {Effect.BLUR: 16, Effect.PIXELATE: 20})

    def test_effects_can_be_left_out(self):
        self.assertEqual(load_controller(self.write("name: A\nport: B\neffects: {}\n")).effects, {})

    def test_control_numbers_at_both_ends_of_the_range(self):
        text = "name: A\nport: B\neffects:\n  blur: 0\n  pixelate: 127\n"
        self.assertEqual(
            load_controller(self.write(text)).effects, {Effect.BLUR: 0, Effect.PIXELATE: 127}
        )

    def effects_from(self, effects_yaml: str) -> dict:
        return load_controller(self.write(f"name: A\nport: B\neffects:\n{effects_yaml}")).effects

    def test_pause_can_be_a_control_or_a_note(self):
        self.assertEqual(self.effects_from("  pause: 96\n"), {Effect.PAUSE: 96})
        self.assertEqual(self.effects_from("  pause: {note: 36}\n"), {Effect.PAUSE: Note(36)})

    def test_ripple_can_be_a_control_or_a_note(self):
        self.assertEqual(self.effects_from("  ripple: 96\n"), {Effect.RIPPLE: 96})
        self.assertEqual(self.effects_from("  ripple: {note: 36}\n"), {Effect.RIPPLE: Note(36)})

    def test_bad_notes_are_rejected(self):
        for value in ("{note: 128}", "{note: true}", "{note: x}", "{number: 36}",
                      "{note: 36, channel: 1}", "{}"):
            with self.subTest(value=value):
                self.assert_rejected(f"name: A\nport: B\neffects:\n  pause: {value}\n", '"pause"')

    def test_notes_are_rejected_for_effects_that_follow_a_position(self):
        self.assert_rejected("name: A\nport: B\neffects:\n  blur: {note: 36}\n", '"blur"')

    def test_a_control_and_a_note_with_the_same_number_are_different(self):
        effects = self.effects_from("  blur: 16\n  pause: {note: 16}\n")
        self.assertEqual(effects, {Effect.BLUR: 16, Effect.PAUSE: Note(16)})

    def test_invalid_yaml_reports_the_line(self):
        self.assert_rejected("name: A\nport: [\n", "line")

    def test_empty_file(self):
        self.assert_rejected("", "expected")

    def test_missing_fields(self):
        self.assert_rejected("port: B\neffects: {}\n", '"name"')
        self.assert_rejected("name: A\neffects: {}\n", '"port"')
        self.assert_rejected("name: A\nport: B\n", '"effects"')

    def test_empty_port_is_rejected_because_it_would_match_every_device(self):
        self.assert_rejected('name: A\nport: ""\neffects: {}\n', '"port"')

    def test_wrong_field_types(self):
        self.assert_rejected("name: 5\nport: B\neffects: {}\n", '"name"')
        self.assert_rejected("name: A\nport: B\neffects: [1, 2]\n", '"effects"')

    def test_unknown_effect(self):
        self.assert_rejected("name: A\nport: B\neffects:\n  blurr: 16\n", 'unknown effect "blurr"')

    def test_bad_control_values(self):
        for value in ("128", "-1", "1.5", "true", "sixteen", "null", "[16]"):
            with self.subTest(value=value):
                self.assert_rejected(f"name: A\nport: B\neffects:\n  blur: {value}\n", '"blur"')

    def test_control_assigned_to_two_effects(self):
        self.assert_rejected(
            "name: A\nport: B\neffects:\n  blur: 16\n  pixelate: 16\n", "control 16 .*both"
        )

    def test_repeated_effect_is_not_silently_overwritten(self):
        self.assert_rejected("name: A\nport: B\neffects:\n  blur: 16\n  blur: 17\n", "twice")

    def test_unsafe_yaml_is_rejected(self):
        self.assert_rejected("name: !!python/object/apply:os.getcwd []\nport: B\neffects: {}\n", "")

    def test_bad_file_does_not_stop_the_good_ones(self):
        self.write(GOOD, "a_good.yaml")
        self.write("name: [", "b_bad.yaml")
        self.write(GOOD.replace("Test Controller", "Second"), "c_good.yml")
        controllers, errors = load_controllers(self.dir)
        self.assertEqual([c.name for c in controllers], ["Test Controller", "Second"])
        self.assertEqual(len(errors), 1)
        self.assertIn("b_bad.yaml", errors[0])

    def test_duplicate_names_are_reported(self):
        self.write(GOOD, "a.yaml")
        self.write(GOOD, "b.yaml")
        controllers, errors = load_controllers(self.dir)
        self.assertEqual(len(controllers), 1)
        self.assertIn("b.yaml", errors[0])


class SavingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name) / "new" / "folder"

    def controller(self, name="My Device", port="My Port", effects=None):
        return Controller(name, port, effects or {Effect.BLUR: 16})

    def test_round_trip_creates_the_folder(self):
        original = self.controller(effects={Effect.BLUR: 0, Effect.SATURATION_CYAN: 127})
        path = save_controller(original, self.dir)
        self.assertEqual(load_controller(path), original)
        self.assertEqual(path.name, "my_device.yaml")

    def test_notes_round_trip(self):
        original = self.controller(effects={Effect.BLUR: 16, Effect.PAUSE: Note(16)})
        self.assertEqual(load_controller(save_controller(original, self.dir)), original)

    def test_awkward_names_survive(self):
        for name in ("Yes", "123", "a: b # c", "Überwald ©", '"quoted"', "../escape"):
            with self.subTest(name=name):
                path = save_controller(self.controller(name=name, port=f"port {name}"), self.dir)
                self.assertEqual(path.parent, self.dir)
                self.assertEqual(load_controller(path).name, name)

    def test_same_name_replaces_the_file(self):
        first = save_controller(self.controller(), self.dir)
        second = save_controller(self.controller(effects={Effect.BLUR: 99}), self.dir)
        self.assertEqual(first, second)
        self.assertEqual(load_controller(second).effects, {Effect.BLUR: 99})
        self.assertEqual(len(list(self.dir.glob("*.yaml"))), 1)

    def test_same_device_under_a_new_name_replaces_the_old_file(self):
        save_controller(self.controller(name="Old"), self.dir)
        save_controller(self.controller(name="New"), self.dir)
        controllers, errors = load_controllers(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual([c.name for c in controllers], ["New"])

    def test_different_names_that_look_alike_get_separate_files(self):
        first = save_controller(self.controller(name="A B", port="one"), self.dir)
        second = save_controller(self.controller(name="a_b", port="two"), self.dir)
        self.assertNotEqual(first, second)
        self.assertEqual(len(load_controllers(self.dir)[0]), 2)

    def test_unreadable_file_is_left_alone(self):
        self.dir.mkdir(parents=True)
        broken = self.dir / "my_device.yaml"
        broken.write_text("name: [")
        path = save_controller(self.controller(), self.dir)
        self.assertNotEqual(path, broken)
        self.assertEqual(broken.read_text(), "name: [")

    def test_no_temporary_file_is_left_behind(self):
        save_controller(self.controller(), self.dir)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


class MergingTests(unittest.TestCase):
    AKAI = Controller("Akai", "MIDI Mix", {Effect.BLUR: 16})
    OXYGEN = Controller("Oxygen", "Oxygen", {Effect.BLUR: 22})

    def test_user_controller_is_added(self):
        mine = Controller("Mine", "Other", {Effect.BLUR: 1})
        self.assertEqual(merge_controllers([self.AKAI], [mine]), [self.AKAI, mine])

    def test_same_name_replaces_the_built_in(self):
        mine = Controller("Akai", "Elsewhere", {Effect.BLUR: 1})
        self.assertEqual(merge_controllers([self.AKAI, self.OXYGEN], [mine]), [self.OXYGEN, mine])

    def test_same_device_replaces_the_built_in(self):
        mine = Controller("Mine", "MIDI Mix:MIDI Mix MIDI 1", {Effect.BLUR: 1})
        self.assertEqual(merge_controllers([self.AKAI, self.OXYGEN], [mine]), [self.OXYGEN, mine])


if __name__ == "__main__":
    unittest.main()
