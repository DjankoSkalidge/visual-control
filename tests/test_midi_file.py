"""Reading notes from MIDI files, and playing them back on a fake clock."""

import tempfile
import unittest
from pathlib import Path

import mido
from PySide6.QtCore import QCoreApplication

from visual_control.midi_file import (
    LATE_LIMIT,
    ChannelPart,
    MidiFileError,
    MidiFilePlayer,
    describe_channel,
    describe_drum,
    is_midi_file,
    read_midi_file,
)

TICKS_PER_BEAT = 480
DRUMS = 9  # Channel 10, as mido counts.
PIANO = 0
BASS = 1
KICK, SNARE, HI_HAT = 36, 38, 42
# A drum loop someone downloaded, which has its drums on channel 1, not 10.
REAL_DRUM_LOOP = Path(__file__).parent / "data" / "basic_edm_beat.mid"


def read_drum_part(path):
    return read_midi_file(path).on_channel(DRUMS)


def write_tracks(path: Path, *tracks: list[tuple[int, int, int]]) -> Path:
    """Each track is a list of beat, channel and note, in time order."""
    midi = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    for notes in tracks:
        track = mido.MidiTrack()
        tick = 0
        for beat, channel, note in notes:
            track.append(mido.Message("note_on", channel=channel, note=note, velocity=90,
                                      time=beat * TICKS_PER_BEAT - tick))
            tick = beat * TICKS_PER_BEAT
        track.append(mido.MetaMessage("end_of_track", time=4 * TICKS_PER_BEAT - tick))
        midi.tracks.append(track)
    midi.save(path)
    return path


def write_midi(
    path: Path,
    notes: list[tuple[int, int]],  # Beat and note.
    channel: int = DRUMS,
    end_beat: int | None = None,
    tempo: int = 500_000,  # 120 bpm, so a beat is half a second.
    velocity: int = 100,
) -> Path:
    events = [(round(beat * TICKS_PER_BEAT), note) for beat, note in sorted(notes)]
    track = mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=tempo, time=0)])
    tick = 0
    for at, note in events:
        track.append(mido.Message("note_on", channel=channel, note=note, velocity=velocity,
                                  time=at - tick))
        track.append(mido.Message("note_off", channel=channel, note=note, time=0))
        tick = at
    if end_beat is not None:
        track.append(mido.MetaMessage("end_of_track", time=end_beat * TICKS_PER_BEAT - tick))
    midi = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    midi.tracks.append(track)
    midi.save(path)
    return path


class ReadMidiFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_most_played_notes_come_first(self):
        path = write_midi(self.dir / "beat.mid", [
            (0, KICK), (1, SNARE), (2, KICK), (3, SNARE), (0.5, HI_HAT),
            (1.5, HI_HAT), (2.5, HI_HAT), (3.5, HI_HAT),
        ], end_beat=4)
        part = read_drum_part(path)
        self.assertEqual(part.most_played(), [(HI_HAT, 4), (KICK, 2), (SNARE, 2)])

    def test_ties_go_to_the_lower_note(self):
        path = write_midi(self.dir / "tie.mid", [(0, 50), (1, 40), (2, 45)], end_beat=4)
        self.assertEqual(read_drum_part(path).most_played(), [(40, 1), (45, 1), (50, 1)])

    def test_only_the_ten_most_played_are_listed(self):
        # Notes 40-51, where a higher note is played more often.
        notes = [(beat, note) for note in range(40, 52) for beat in range(note - 39)]
        part = read_drum_part(write_midi(self.dir / "many.mid", notes))
        self.assertEqual([note for note, _ in part.most_played()], list(range(51, 41, -1)))

    def test_fewer_than_ten_notes_lists_just_those(self):
        part = read_drum_part(write_midi(self.dir / "two.mid", [(0, KICK), (1, SNARE)]))
        self.assertEqual(part.most_played(), [(KICK, 1), (SNARE, 1)])

    def test_a_single_note_is_enough(self):
        part = read_drum_part(write_midi(self.dir / "one.mid", [(0, KICK)], end_beat=1))
        self.assertEqual(part.most_played(), [(KICK, 1)])

    def test_each_channel_only_has_its_own_notes(self):
        path = write_tracks(self.dir / "mixed.mid",
                            [(0, DRUMS, KICK)], [(0, PIANO, 60), (1, PIANO, KICK)])
        notes = read_midi_file(path)
        self.assertEqual(notes.on_channel(DRUMS).most_played(), [(KICK, 1)])
        self.assertEqual(notes.on_channel(PIANO).most_played(), [(KICK, 1), (60, 1)])

    def test_channels_are_listed_in_order_with_their_hits(self):
        path = write_tracks(self.dir / "song.mid", [(0, DRUMS, KICK)],
                            [(0, PIANO, 60), (1, PIANO, 62), (2, BASS, 40)])
        self.assertEqual(read_midi_file(path).channels(), [(PIANO, 2), (BASS, 1), (DRUMS, 1)])

    def test_the_drum_channel_is_chosen_first_even_when_it_isnt_busiest(self):
        path = write_tracks(self.dir / "song.mid", [(0, DRUMS, KICK)],
                            [(0, PIANO, 60), (1, PIANO, 62), (2, PIANO, 64)])
        self.assertEqual(read_midi_file(path).default_channel(), DRUMS)

    def test_without_a_drum_channel_the_busiest_is_chosen(self):
        path = write_tracks(self.dir / "song.mid", [(0, BASS, 40), (1, BASS, 40), (2, PIANO, 60)])
        self.assertEqual(read_midi_file(path).default_channel(), BASS)

    def test_equally_busy_channels_go_to_the_lower_one(self):
        path = write_tracks(self.dir / "song.mid", [(0, BASS, 40), (1, PIANO, 60)])
        self.assertEqual(read_midi_file(path).default_channel(), PIANO)

    def test_a_drum_loop_on_channel_1_can_be_used(self):
        notes = read_midi_file(REAL_DRUM_LOOP)
        self.assertEqual(notes.channels(), [(0, 22)])
        self.assertEqual(notes.default_channel(), 0)
        part = notes.on_channel(0)
        self.assertEqual(part.most_played(), [(HI_HAT, 16), (KICK, 4), (SNARE, 2)])
        self.assertAlmostEqual(part.length, 2.286, places=3)

    def test_note_on_without_velocity_is_not_a_hit(self):
        path = self.dir / "release.mid"
        track = mido.MidiTrack([
            mido.Message("note_on", channel=DRUMS, note=KICK, velocity=90),
            mido.Message("note_on", channel=DRUMS, note=KICK, velocity=0, time=240),
        ])
        mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT, tracks=[track]).save(path)
        self.assertEqual(read_drum_part(path).most_played(), [(KICK, 1)])

    def test_times_are_in_seconds(self):
        part = read_drum_part(write_midi(self.dir / "t.mid", [(0, KICK), (1, SNARE), (3, KICK)],
                                         end_beat=4))
        self.assertEqual([round(t, 6) for t, _ in part.hits], [0.0, 0.5, 1.5])
        self.assertAlmostEqual(part.length, 2.0)

    def test_tempo_changes_are_followed(self):
        path = self.dir / "tempo.mid"
        track = mido.MidiTrack([
            mido.MetaMessage("set_tempo", tempo=500_000),
            mido.Message("note_on", channel=DRUMS, note=KICK, velocity=90),
            mido.MetaMessage("set_tempo", tempo=1_000_000, time=480),  # 60 bpm from beat 1.
            mido.Message("note_on", channel=DRUMS, note=SNARE, velocity=90, time=480),
        ])
        mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT, tracks=[track]).save(path)
        self.assertEqual([round(t, 6) for t, _ in read_drum_part(path).hits], [0.0, 1.5])

    def test_the_loop_lasts_until_the_end_of_the_file(self):
        part = read_drum_part(write_midi(self.dir / "bar.mid", [(0, KICK)], end_beat=4))
        self.assertAlmostEqual(part.length, 2.0)

    def test_an_empty_file_is_an_error(self):
        path = write_midi(self.dir / "empty.mid", [], end_beat=4)
        with self.assertRaisesRegex(MidiFileError, r"empty\.mid has no notes"):
            read_midi_file(path)

    def test_a_file_with_no_length_is_an_error(self):
        path = write_midi(self.dir / "instant.mid", [(0, KICK)])
        with self.assertRaisesRegex(MidiFileError, "too short to loop"):
            read_drum_part(path)

    def test_a_damaged_file_is_an_error(self):
        path = self.dir / "broken.mid"
        path.write_bytes(b"MThd\x00\x00\x00\x06garbage")
        with self.assertRaisesRegex(MidiFileError, r"broken\.mid: can't read it"):
            read_drum_part(path)

    def test_a_missing_file_is_an_error(self):
        with self.assertRaisesRegex(MidiFileError, "can't read it"):
            read_midi_file(self.dir / "missing.mid")

    def test_type_2_files_are_an_error(self):
        path = self.dir / "type2.mid"
        track = mido.MidiTrack([mido.Message("note_on", channel=DRUMS, note=KICK, velocity=90)])
        mido.MidiFile(type=2, ticks_per_beat=TICKS_PER_BEAT, tracks=[track]).save(path)
        with self.assertRaisesRegex(MidiFileError, "type 2"):
            read_drum_part(path)


class NamingTests(unittest.TestCase):
    def test_midi_files_are_recognized_by_extension(self):
        self.assertTrue(is_midi_file("beat.mid"))
        self.assertTrue(is_midi_file("/a/b/Beat.MIDI"))
        self.assertFalse(is_midi_file("clip.mp4"))
        self.assertFalse(is_midi_file("mid"))

    def test_drum_notes_have_their_general_midi_names(self):
        self.assertEqual(describe_drum(38), "Acoustic Snare (38)")
        self.assertEqual(describe_drum(90), "Note 90")

    def test_channels_are_numbered_from_1(self):
        self.assertEqual(describe_channel(0), "Channel 1")
        self.assertEqual(describe_channel(DRUMS), "Channel 10 (drums)")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class MidiFilePlayerTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.clock = FakeClock()
        # A two-second loop: kick on the beat, snare halfway.
        part = ChannelPart("beat.mid", ((0.0, KICK), (1.0, SNARE)), 2.0)
        self.player = MidiFilePlayer(part, clock=self.clock)
        self.addCleanup(self.player.stop)
        self.played = []
        self.player.note_played.connect(self.played.append)

    def run_until(self, now: float) -> None:
        """Move the clock along, playing whatever the player would have by then."""
        while self.clock.now < now:
            self.clock.now = min(now, self.clock.now + 0.01)
            self.player.play_due()

    def test_starting_plays_notes_at_the_start_straight_away(self):
        self.player.start()
        self.assertEqual(self.played, [KICK])

    def test_notes_play_when_they_are_due_and_not_before(self):
        self.player.start()
        self.run_until(1000.99)
        self.assertEqual(self.played, [KICK])
        self.run_until(1001.0)
        self.assertEqual(self.played, [KICK, SNARE])

    def test_it_loops(self):
        self.player.start()
        self.run_until(1004.0)
        self.assertEqual(self.played, [KICK, SNARE, KICK, SNARE, KICK])

    def test_it_waits_until_the_next_note(self):
        self.player.start()
        self.assertEqual(self.player._timer.interval(), 1000)
        self.assertTrue(self.player._timer.isActive())

    def test_loops_dont_drift(self):
        self.player.start()
        for _ in range(500):
            self.clock.now += 1.003  # Always woken a little late.
            self.player.play_due()
        self.assertAlmostEqual(self.player._loop_start % 2.0, 1000.0 % 2.0)

    def test_slightly_late_notes_still_play(self):
        self.player.start()
        self.clock.now = 1001.0 + LATE_LIMIT / 2
        self.player.play_due()
        self.assertEqual(self.played, [KICK, SNARE])

    def test_after_a_stall_missed_notes_are_skipped(self):
        self.player.start()
        self.clock.now = 1000 + 2.0 * 1000 + 0.5  # A thousand loops later.
        self.player.play_due()
        self.assertEqual(self.played, [KICK])
        self.run_until(1000 + 2.0 * 1000 + 1.0)
        self.assertEqual(self.played, [KICK, SNARE])

    def test_stopping_stops_the_timer(self):
        self.player.start()
        self.player.stop()
        self.assertFalse(self.player._timer.isActive())

    def test_starting_again_starts_from_the_beginning(self):
        self.player.start()
        self.run_until(1001.5)
        self.player.stop()
        self.played.clear()
        self.player.start()
        self.assertEqual(self.played, [KICK])


if __name__ == "__main__":
    unittest.main()
