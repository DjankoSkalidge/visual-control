"""Setting up and playing a MIDI file in a real window. Needs a display."""

import os
import subprocess
import unittest

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from tests.gui import GuiTestCase
from tests.test_midi_file import (
    BASS, DRUMS, HI_HAT, KICK, PIANO, REAL_DRUM_LOOP, SNARE, write_midi, write_tracks,
)
from visual_control.effects import Effect
from visual_control.midi_file_window import NO_EFFECT


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class MidiFileWindowTests(GuiTestCase):
    def beat(self, name: str = "beat.mid", **kwargs):
        # Kick on every beat, snare on 2 and 4, hi-hat on the off-beats, at 120 bpm.
        notes = [(b, KICK) for b in range(4)] + [(1, SNARE), (3, SNARE)]
        notes += [(b + 0.5, HI_HAT) for b in range(4)] + [(b + 0.75, HI_HAT) for b in range(3)]
        return write_midi(self.dir / name, notes, end_beat=4, **kwargs)

    def play_video(self):
        path = self.dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        QTest.qWait(300)
        return path

    def open_panel(self, path=None):
        self.window.open_midi_file(str(path or self.beat()))
        QTest.qWait(100)
        return self.window._midi_file_dialog

    def choose(self, dialog, note: int, effect: Effect | None) -> None:
        choice = dialog._effect_choices[note]
        choice.setCurrentIndex(choice.findData(effect))

    def rows(self, dialog) -> list[int]:
        return list(dialog._effect_choices)

    def status(self) -> str:
        return self.window._status.text()

    def test_the_panel_lists_drum_notes_most_played_first(self):
        dialog = self.open_panel()
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.rows(dialog), [HI_HAT, KICK, SNARE])

    def test_fewer_than_ten_notes_shows_just_those(self):
        dialog = self.open_panel(write_midi(self.dir / "kick.mid", [(0, KICK)], end_beat=1))
        self.assertEqual(self.rows(dialog), [KICK])

    def test_every_note_starts_with_no_effect(self):
        dialog = self.open_panel()
        for choice in dialog._effect_choices.values():
            self.assertEqual(choice.currentText(), NO_EFFECT)

    def test_pause_isnt_offered_but_toggles_and_animations_are(self):
        dialog = self.open_panel()
        choice = dialog._effect_choices[KICK]
        offered = [choice.itemData(i) for i in range(1, choice.count())]
        self.assertNotIn(Effect.PAUSE, offered)
        self.assertNotIn(Effect.BLUR, offered)
        for effect in (Effect.BLACK_AND_WHITE, Effect.REMOVE_RED, Effect.FLASH, Effect.STUTTER):
            self.assertIn(effect, offered)

    def test_the_same_effect_can_go_on_several_notes(self):
        dialog = self.open_panel()
        self.choose(dialog, KICK, Effect.RIPPLE)
        self.choose(dialog, SNARE, Effect.RIPPLE)
        self.assertEqual(dialog.assignments(), {KICK: Effect.RIPPLE, SNARE: Effect.RIPPLE})

    def test_start_needs_at_least_one_effect(self):
        dialog = self.open_panel()
        self.assertFalse(dialog._start_button.isEnabled())
        self.choose(dialog, KICK, Effect.FLASH)
        self.assertTrue(dialog._start_button.isEnabled())
        self.choose(dialog, KICK, None)
        self.assertFalse(dialog._start_button.isEnabled())

    def test_a_file_without_notes_shows_an_error_instead(self):
        path = write_midi(self.dir / "silence.mid", [], end_beat=4)
        self.window.open_midi_file(str(path))
        QTest.qWait(50)
        self.assertIsNone(self.window._midi_file_dialog)
        self.assertIn("silence.mid has no notes", self.status())

    def channels(self, dialog) -> list[str]:
        return [dialog._channel.itemText(i) for i in range(dialog._channel.count())]

    def select_channel(self, dialog, channel: int) -> None:
        dialog._channel.setCurrentIndex(dialog._channel.findData(channel))
        QTest.qWait(50)

    def song(self):
        return write_tracks(self.dir / "song.mid",
                            [(0, DRUMS, KICK), (1, DRUMS, SNARE)],
                            [(0, PIANO, 60), (1, PIANO, 62), (2, PIANO, 60), (3, BASS, 40)])

    def test_the_channel_list_shows_channels_with_notes(self):
        dialog = self.open_panel(self.song())
        self.assertEqual(self.channels(dialog),
                         ["Channel 1: 3 hits", "Channel 2: 1 hit", "Channel 10 (drums): 2 hits"])

    def test_the_drum_channel_is_chosen_first(self):
        dialog = self.open_panel(self.song())
        self.assertEqual(dialog._channel.currentData(), DRUMS)
        self.assertEqual(self.rows(dialog), [KICK, SNARE])

    def test_choosing_another_channel_lists_its_notes(self):
        dialog = self.open_panel(self.song())
        self.select_channel(dialog, PIANO)
        self.assertEqual(self.rows(dialog), [60, 62])

    def test_choosing_another_channel_starts_its_choices_over(self):
        dialog = self.open_panel(self.song())
        self.choose(dialog, KICK, Effect.RIPPLE)
        self.select_channel(dialog, PIANO)
        self.assertEqual(dialog.assignments(), {})
        self.assertFalse(dialog._start_button.isEnabled())
        self.select_channel(dialog, DRUMS)
        self.assertEqual(dialog._effect_choices[KICK].currentText(), NO_EFFECT)

    def test_only_the_chosen_channel_plays(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        # Both channels have a note 60 at the start.
        path = write_tracks(self.dir / "both.mid", [(0, PIANO, 60)], [(1, BASS, 60)])
        dialog = self.open_panel(path)
        self.select_channel(dialog, BASS)
        self.choose(dialog, 60, Effect.BLACK_AND_WHITE)
        dialog._start_button.click()
        QTest.qWait(100)
        self.assertFalse(self.window._view._black_and_white)  # The piano's note didn't count.
        QTest.qWait(500)
        self.assertTrue(self.window._view._black_and_white)

    def test_a_drum_loop_on_channel_1_plays(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel(REAL_DRUM_LOOP)
        self.assertEqual(self.channels(dialog), ["Channel 1: 22 hits"])
        self.assertEqual(self.rows(dialog), [HI_HAT, KICK, SNARE])
        self.choose(dialog, KICK, Effect.BLACK_AND_WHITE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertTrue(self.window._view._black_and_white)
        self.assertIn("Playing basic_edm_beat.mid", self.window._midi_status.text())

    def test_opening_the_panel_pauses_the_video_and_resets_effects(self):
        self.play_video()
        self.set_effect(Effect.BLUR, 1.0)
        self.open_panel()
        self.assertTrue(self.window._view.is_paused())
        self.assertEqual(self.status(), "clip.mp4 (paused)")
        self.assertEqual(self.window._view._blur, 0.0)

    def test_controllers_are_ignored_while_the_panel_is_open(self):
        self.open_panel()
        self.set_effect(Effect.BLUR, 1.0)
        self.assertEqual(self.window._view._blur, 0.0)

    def test_starting_resumes_the_video(self):
        self.play_video()
        dialog = self.open_panel()
        self.choose(dialog, KICK, Effect.RIPPLE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertFalse(self.window._view.is_paused())
        self.assertEqual(self.status(), "clip.mp4")

    def test_cancelling_resumes_the_video_too(self):
        self.play_video()
        self.open_panel().reject()
        QTest.qWait(50)
        self.assertFalse(self.window._view.is_paused())
        self.assertIsNone(self.window._midi_file_player)

    def test_a_paused_video_stays_paused(self):
        self.play_video()
        self.set_effect(Effect.PAUSE, 1.0)
        dialog = self.open_panel()
        self.assertTrue(self.window._view.is_paused())
        self.choose(dialog, KICK, Effect.RIPPLE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertTrue(self.window._view.is_paused())
        self.assertEqual(self.status(), "clip.mp4 (paused)")

    def test_assigned_notes_trigger_their_effects(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel()
        # The kick on beat 1 plays the moment it starts.
        self.choose(dialog, KICK, Effect.BLACK_AND_WHITE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertTrue(self.window._view._black_and_white)
        self.assertIn("Playing beat.mid", self.window._midi_status.text())

    def test_it_keeps_playing_in_time(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel()
        self.choose(dialog, SNARE, Effect.FLASH)
        played = []
        self.window._view.start_animation = played.append
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertEqual(played, [])  # The first snare is half a second in.
        QTest.qWait(500)
        self.assertEqual(played, [Effect.FLASH])
        QTest.qWait(2050)  # Past the second snare, and the first of the next loop at 2.5 s.
        self.assertEqual(played, [Effect.FLASH] * 3)

    def test_unassigned_notes_do_nothing(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel()
        self.choose(dialog, SNARE, Effect.BLACK_AND_WHITE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertFalse(self.window._view._black_and_white)

    def test_cancelling_keeps_the_file_already_playing(self):
        dialog = self.open_panel(self.beat("first.mid"))
        self.choose(dialog, KICK, Effect.RIPPLE)
        dialog._start_button.click()
        QTest.qWait(50)
        first = self.window._midi_file_player
        self.open_panel(self.beat("second.mid")).reject()
        QTest.qWait(50)
        self.assertIs(self.window._midi_file_player, first)
        self.assertTrue(first._timer.isActive())
        self.assertIn("Playing first.mid", self.window._midi_status.text())

    def test_a_new_file_replaces_the_old_one(self):
        dialog = self.open_panel(self.beat("first.mid"))
        self.choose(dialog, KICK, Effect.RIPPLE)
        dialog._start_button.click()
        QTest.qWait(50)
        first = self.window._midi_file_player
        dialog = self.open_panel(self.beat("second.mid"))
        self.choose(dialog, SNARE, Effect.SHAKE)
        dialog._start_button.click()
        QTest.qWait(50)
        self.assertFalse(isValid(first))
        self.assertEqual(self.window._midi_file_effects, {SNARE: Effect.SHAKE})
        self.assertIn("Playing second.mid", self.window._midi_status.text())
        self.assertNotIn("first.mid", self.window._midi_status.text())

    def test_the_file_is_ignored_while_controllers_are_being_set_up(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel()
        self.choose(dialog, KICK, Effect.FLASH)
        dialog._start_button.click()
        QTest.qWait(50)
        self.window.open_controller_config()
        QTest.qWait(50)
        played = []
        self.window._view.start_animation = played.append
        QTest.qWait(1100)  # Two kicks.
        self.window._config_dialog.reject()
        self.assertEqual(played, [])

    def start_beat(self, effect: Effect = Effect.FLASH, note: int = KICK):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel()
        self.choose(dialog, note, effect)
        dialog._start_button.click()
        QTest.qWait(50)

    def test_there_is_no_remove_button_until_a_file_plays(self):
        self.assertFalse(self.window._remove_midi_file_button.isVisible())
        self.open_panel().reject()
        QTest.qWait(50)
        self.assertFalse(self.window._remove_midi_file_button.isVisible())

    def test_the_remove_button_appears_once_a_file_plays(self):
        self.start_beat()
        self.assertTrue(self.window._remove_midi_file_button.isVisible())

    def test_removing_stops_the_file(self):
        self.start_beat()
        player = self.window._midi_file_player
        self.window._remove_midi_file_button.click()
        played = []
        self.window._view.start_animation = played.append
        QTest.qWait(1100)  # Two kicks.
        self.assertEqual(played, [])
        self.assertIsNone(self.window._midi_file_player)
        self.assertFalse(isValid(player))
        self.assertNotIn("Playing", self.window._midi_status.text())
        self.assertFalse(self.window._remove_midi_file_button.isVisible())

    def test_removing_turns_off_toggles_the_file_left_on(self):
        self.start_beat(Effect.BLACK_AND_WHITE)
        self.assertTrue(self.window._view._black_and_white)
        self.window._remove_midi_file_button.click()
        self.assertFalse(self.window._view._black_and_white)

    def test_removing_leaves_effects_the_file_didnt_use(self):
        self.start_beat(Effect.REMOVE_RED)
        self.set_effect(Effect.BLACK_AND_WHITE, 1.0)
        self.set_effect(Effect.BLUR, 1.0)
        self.window._remove_midi_file_button.click()
        self.assertTrue(self.window._view._black_and_white)
        self.assertEqual(self.window._view._blur, 1.0)
        self.assertEqual(self.window._view._channels, [1.0, 1.0, 1.0])

    def test_a_file_can_be_added_again_after_removing(self):
        self.start_beat()
        self.window._remove_midi_file_button.click()
        self.start_beat(Effect.BLACK_AND_WHITE)
        self.assertTrue(self.window._view._black_and_white)
        self.assertTrue(self.window._remove_midi_file_button.isVisible())

    def test_dropping_a_video_and_a_midi_file_loads_both(self):
        video = self.play_video()
        midi = self.beat()
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(midi)), QUrl.fromLocalFile(str(video))])
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, data,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        # Qt only delivers a drop during a real drag, so hand it over directly.
        self.window.dropEvent(event)
        QTest.qWait(300)
        self.assertEqual(self.window._media_name, "clip.mp4")
        self.assertIsNotNone(self.window._midi_file_dialog)
        self.assertTrue(self.window._view.is_paused())
        self.window._midi_file_dialog.done(QDialog.DialogCode.Rejected)


if __name__ == "__main__":
    unittest.main()
