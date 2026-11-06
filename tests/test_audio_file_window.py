"""Setting up and playing an audio file in a real window. Needs a display.

The sound is muted. Waits use tests.gui.wait, not QTest.qWait, which can hang
once an audio file has stopped.
"""

import os
import subprocess
import unittest

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from tests.gui import GuiTestCase, wait
from tests.test_audio_file import beat, write_mp3, write_wav
from tests.test_midi_file import KICK, write_midi
from visual_control.audio_file import Band
from visual_control.audio_file_window import NO_EFFECT
from visual_control.effects import Effect


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class AudioFileWindowTests(GuiTestCase):
    def song(self, name: str = "beat.wav"):
        # Kicks at 0.5, 1.5, 2.5 and 3.5 s, snares at 1 and 3 s, hi-hats in between.
        return write_wav(self.dir / name, beat(np.random.default_rng(1)))

    def play_video(self):
        path = self.dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        self.window.load(str(path))
        wait(300)
        return path

    def open_panel(self, path=None):
        self.window.open_audio_file(str(path or self.song()))
        wait(100)
        return self.window._audio_file_dialog

    def choose(self, dialog, band: Band, effect: Effect | None) -> None:
        choice = dialog._effect_choices[band]
        choice.setCurrentIndex(choice.findData(effect))

    def start(self, band: Band = Band.LOW, effect: Effect = Effect.BLACK_AND_WHITE, path=None):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        dialog = self.open_panel(path)
        self.choose(dialog, band, effect)
        dialog._start_button.click()
        wait(50)

    def drop(self, *paths) -> None:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, data,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        # Qt only delivers a drop during a real drag, so hand it over directly.
        self.window.dropEvent(event)
        wait(300)

    def status(self) -> str:
        return self.window._status.text()

    def test_the_panel_lists_three_bands_with_their_hits(self):
        dialog = self.open_panel()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(list(dialog._effect_choices), [Band.LOW, Band.MID, Band.HIGH])
        self.assertEqual(dialog._counts[Band.LOW].text(), "4 hits, 1.0 per second")
        self.assertEqual(dialog._counts[Band.MID].text(), "2 hits, 0.5 per second")
        self.assertEqual(dialog._counts[Band.HIGH].text(), "6 hits, 1.5 per second")

    def test_every_band_starts_with_no_effect(self):
        dialog = self.open_panel()
        for choice in dialog._effect_choices.values():
            self.assertEqual(choice.currentText(), NO_EFFECT)

    def test_the_same_effects_as_midi_files_are_offered(self):
        choice = self.open_panel()._effect_choices[Band.LOW]
        offered = [choice.itemData(i) for i in range(1, choice.count())]
        self.assertNotIn(Effect.PAUSE, offered)
        self.assertNotIn(Effect.BLUR, offered)
        for effect in (Effect.BLACK_AND_WHITE, Effect.FLASH, Effect.RIPPLE, Effect.STUTTER):
            self.assertIn(effect, offered)

    def test_start_needs_at_least_one_effect(self):
        dialog = self.open_panel()
        self.assertFalse(dialog._start_button.isEnabled())
        self.choose(dialog, Band.HIGH, Effect.FLASH)
        self.assertTrue(dialog._start_button.isEnabled())
        self.choose(dialog, Band.HIGH, None)
        self.assertFalse(dialog._start_button.isEnabled())

    def test_moving_a_sensitivity_slider_updates_its_count(self):
        dialog = self.open_panel()
        slider = dialog._sensitivities[Band.HIGH]
        slider.setValue(0)
        low = dialog._counts[Band.HIGH].text()
        slider.setValue(100)
        self.assertNotEqual(dialog._counts[Band.HIGH].text(), low)

    def test_only_assigned_bands_get_a_sensitivity(self):
        dialog = self.open_panel()
        self.choose(dialog, Band.MID, Effect.RIPPLE)
        dialog._sensitivities[Band.MID].setValue(80)
        self.assertEqual(dialog.assignments(), {Band.MID: Effect.RIPPLE})
        self.assertEqual(dialog.sensitivities(), {Band.MID: 80})

    def test_a_silent_file_shows_an_error_instead(self):
        path = write_wav(self.dir / "silence.wav", np.zeros(44100))
        self.window.open_audio_file(str(path))
        wait(50)
        self.assertIsNone(self.window._audio_file_dialog)
        self.assertIn("silence.wav is silent", self.status())

    def test_assigned_bands_trigger_their_effects_in_time(self):
        self.start(Band.LOW, Effect.BLACK_AND_WHITE)
        wait(250)
        self.assertFalse(self.window._view._black_and_white)  # The first kick is at 0.5 s.
        wait(500)
        self.assertTrue(self.window._view._black_and_white)
        self.assertIn("Playing beat.wav", self.window._midi_status.text())

    def test_unassigned_bands_do_nothing(self):
        self.start(Band.MID, Effect.FLASH)
        played = []
        self.window._view.start_animation = played.append
        wait(800)  # Past the first kick and hi-hat, before the first snare.
        self.assertEqual(played, [])
        wait(400)
        self.assertEqual(played, [Effect.FLASH])

    def test_mp3_files_play(self):
        self.start(path=write_mp3(self.dir / "beat.mp3", beat(np.random.default_rng(1))))
        wait(700)
        self.assertTrue(self.window._view._black_and_white)

    def test_an_audio_file_doesnt_replace_the_picture(self):
        self.show_image(np.full((90, 160, 3), 100, np.uint8))
        self.drop(self.song())
        self.assertEqual(self.window._media_name, "image.png")
        self.assertIsNotNone(self.window._audio_file_dialog)
        self.window._audio_file_dialog.done(QDialog.DialogCode.Rejected)

    def test_opening_the_panel_pauses_the_video_and_starting_resumes_it(self):
        self.play_video()
        self.set_effect(Effect.BLUR, 1.0)
        dialog = self.open_panel()
        self.assertTrue(self.window._view.is_paused())
        self.assertEqual(self.window._view._blur, 0.0)
        self.choose(dialog, Band.LOW, Effect.RIPPLE)
        dialog._start_button.click()
        wait(50)
        self.assertFalse(self.window._view.is_paused())
        self.assertEqual(self.status(), "clip.mp4")

    def test_controllers_are_ignored_while_the_panel_is_open(self):
        self.open_panel()
        self.window._midi_inputs[0].effect_changed.emit(Effect.BLUR, 1.0)
        wait(50)
        self.assertEqual(self.window._view._blur, 0.0)

    def test_cancelling_keeps_the_file_already_playing(self):
        self.start(path=self.song("first.wav"))
        first = self.window._audio_file_player
        self.open_panel(self.song("second.wav")).reject()
        wait(50)
        self.assertIs(self.window._audio_file_player, first)
        self.assertIn("Playing first.wav", self.window._midi_status.text())

    def test_a_new_file_replaces_the_old_one(self):
        self.start(path=self.song("first.wav"))
        first = self.window._audio_file_player
        dialog = self.open_panel(self.song("second.wav"))
        self.choose(dialog, Band.HIGH, Effect.SHAKE)
        dialog._start_button.click()
        wait(50)
        self.assertFalse(isValid(first))
        self.assertEqual(self.window._audio_file_effects, {Band.HIGH: Effect.SHAKE})
        self.assertIn("Playing second.wav", self.window._midi_status.text())
        self.assertNotIn("first.wav", self.window._midi_status.text())

    def test_there_is_no_remove_button_until_a_file_plays(self):
        self.assertFalse(self.window._remove_audio_file_button.isVisible())
        self.start()
        self.assertTrue(self.window._remove_audio_file_button.isVisible())

    def test_removing_stops_the_file_and_its_toggles(self):
        self.start(Band.LOW, Effect.BLACK_AND_WHITE)
        wait(700)
        self.assertTrue(self.window._view._black_and_white)
        player = self.window._audio_file_player
        self.window._remove_audio_file_button.click()
        self.assertFalse(self.window._view._black_and_white)
        played = []
        self.window._view.start_animation = played.append
        self.window._view.toggle_black_and_white = lambda: played.append("toggle")
        wait(1100)  # Past the next kick.
        self.assertEqual(played, [])
        self.assertIsNone(self.window._audio_file_player)
        self.assertFalse(isValid(player))
        self.assertNotIn("Playing", self.window._midi_status.text())
        self.assertFalse(self.window._remove_audio_file_button.isVisible())

    def test_a_midi_file_and_an_audio_file_can_play_together(self):
        self.start(Band.MID, Effect.FLASH)
        self.window.open_midi_file(str(write_midi(self.dir / "kick.mid", [(0, KICK)], end_beat=1)))
        wait(100)
        dialog = self.window._midi_file_dialog
        choice = dialog._effect_choices[KICK]
        choice.setCurrentIndex(choice.findData(Effect.RIPPLE))
        dialog._start_button.click()
        wait(50)
        status = self.window._midi_status.text()
        self.assertIn("Playing kick.mid", status)
        self.assertIn("Playing beat.wav", status)

    def test_dropping_a_video_and_an_audio_file_loads_both(self):
        video = self.play_video()
        self.drop(self.song(), video)
        self.assertEqual(self.window._media_name, "clip.mp4")
        self.assertIsNotNone(self.window._audio_file_dialog)
        self.assertTrue(self.window._view.is_paused())
        self.window._audio_file_dialog.done(QDialog.DialogCode.Rejected)


if __name__ == "__main__":
    unittest.main()
