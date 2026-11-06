"""Finding hits in audio files, and timing them against the playing position."""

import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import av
import numpy as np
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QApplication

from tests.gui import wait
from visual_control.audio_file import (
    LATE_LIMIT,
    RESYNC_LIMIT,
    AudioClock,
    AudioFileError,
    AudioFilePlayer,
    Band,
    HitSchedule,
    is_audio_file,
    read_audio_file,
)

RATE = 44100
# How far a found hit may be from where the sound starts. The analysis steps
# about 12 ms at a time, and a spectrum covers about 46 ms.
TOLERANCE = 0.03


def kick(rng) -> np.ndarray:
    """A low thump that dies away, like a kick drum."""
    t = np.arange(int(0.25 * RATE)) / RATE
    return np.sin(2 * np.pi * 55 * t) * np.exp(-t * 18)


def band_noise(rng, low: float, high: float, seconds: float, decay: float) -> np.ndarray:
    """Noise between two frequencies that dies away, like a snare or a hi-hat."""
    size = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(size))
    freqs = np.fft.rfftfreq(size, 1 / RATE)
    spectrum[(freqs < low) | (freqs > high)] = 0
    noise = np.fft.irfft(spectrum, size)
    noise /= np.abs(noise).max()
    return noise * np.exp(-np.arange(size) / RATE * decay)


def snare(rng) -> np.ndarray:
    return band_noise(rng, 400, 3000, 0.2, 25)


def hi_hat(rng) -> np.ndarray:
    return band_noise(rng, 7000, 10500, 0.06, 80)


def mix(length: float, sounds: list[tuple[float, np.ndarray]]) -> np.ndarray:
    out = np.zeros(int(length * RATE))
    for at, sound in sounds:
        start = int(at * RATE)
        end = min(len(out), start + len(sound))
        out[start:end] += sound[: end - start]
    return out


def write_wav(path: Path, samples: np.ndarray) -> Path:
    stereo = np.repeat((np.clip(samples * 0.5, -1, 1) * 32767).astype(np.int16)[:, None], 2, 1)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(stereo.tobytes())
    return path


def write_mp3(path: Path, samples: np.ndarray) -> Path:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mp3", rate=RATE, layout="mono")
        data = (np.clip(samples * 0.5, -1, 1)).astype(np.float32)
        for start in range(0, len(data), 1152):
            frame = av.AudioFrame.from_ndarray(data[None, start : start + 1152],
                                               format="flt", layout="mono")
            frame.sample_rate = RATE
            container.mux(stream.encode(frame))
        container.mux(stream.encode(None))
    return path


KICKS = [0.5, 1.5, 2.5, 3.5]
SNARES = [1.0, 3.0]
HI_HATS = [0.75, 1.25, 1.75, 2.25, 2.75, 3.25]


def beat(rng) -> np.ndarray:
    """Four seconds of a kick, snare and hi-hat pattern, at 120 bpm."""
    return mix(4.0, [(t, kick(rng)) for t in KICKS] + [(t, snare(rng)) for t in SNARES]
               + [(t, hi_hat(rng)) for t in HI_HATS])


class ReadAudioFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.rng = np.random.default_rng(1)

    def assert_hits_at(self, found: np.ndarray, expected: list[float]) -> None:
        self.assertEqual(len(found), len(expected), f"found {np.round(found, 3)}")
        for got, want in zip(found, expected):
            self.assertAlmostEqual(got, want, delta=TOLERANCE)

    def test_each_band_finds_its_own_drum(self):
        analysis = read_audio_file(write_wav(self.dir / "beat.wav", beat(self.rng)))
        self.assert_hits_at(analysis.hits(Band.LOW), KICKS)
        self.assert_hits_at(analysis.hits(Band.MID), SNARES)
        self.assert_hits_at(analysis.hits(Band.HIGH), HI_HATS)

    def test_mp3_files_work(self):
        analysis = read_audio_file(write_mp3(self.dir / "beat.mp3", beat(self.rng)))
        # An mp3 starts with a few milliseconds of encoder padding, well within tolerance.
        self.assert_hits_at(analysis.hits(Band.LOW), KICKS)
        self.assert_hits_at(analysis.hits(Band.HIGH), HI_HATS)

    def test_the_length_is_the_whole_file(self):
        analysis = read_audio_file(write_wav(self.dir / "beat.wav", beat(self.rng)))
        self.assertAlmostEqual(analysis.length, 4.0, delta=0.01)
        self.assertEqual(analysis.name, "beat.wav")

    def test_higher_sensitivity_finds_quieter_hits(self):
        loud = [(t, kick(self.rng)) for t in (0.5, 2.5)]
        quiet = [(t, kick(self.rng) * 0.15) for t in (1.5, 3.5)]  # 16 dB quieter.
        analysis = read_audio_file(write_wav(self.dir / "kicks.wav", mix(4.0, loud + quiet)))
        self.assert_hits_at(analysis.hits(Band.LOW, 0), [0.5, 2.5])
        self.assert_hits_at(analysis.hits(Band.LOW, 100), [0.5, 1.5, 2.5, 3.5])

    def test_sensitivity_never_lowers_the_count(self):
        analysis = read_audio_file(write_wav(self.dir / "beat.wav", beat(self.rng)))
        for band in Band:
            counts = [len(analysis.hits(band, s)) for s in range(0, 101, 10)]
            self.assertEqual(counts, sorted(counts), band)

    def test_a_hit_isnt_counted_twice(self):
        # A long, rumbling kick still makes one hit.
        rumble = kick(self.rng) * (1 + 0.3 * np.sin(np.arange(int(0.25 * RATE)) / RATE * 2 * np.pi * 30))
        analysis = read_audio_file(write_wav(self.dir / "rumble.wav", mix(2.0, [(0.5, rumble)])))
        self.assertEqual(len(analysis.hits(Band.LOW, 100)), 1)

    def test_a_silent_file_is_an_error(self):
        path = write_wav(self.dir / "silence.wav", np.zeros(RATE * 2))
        with self.assertRaisesRegex(AudioFileError, "silence.wav is silent"):
            read_audio_file(path)

    def test_a_tiny_file_is_an_error(self):
        path = write_wav(self.dir / "click.wav", np.ones(100))
        with self.assertRaisesRegex(AudioFileError, "click.wav is too short to loop"):
            read_audio_file(path)

    def test_a_damaged_file_is_an_error(self):
        path = self.dir / "broken.mp3"
        path.write_bytes(b"not really an mp3" * 100)
        with self.assertRaisesRegex(AudioFileError, "broken.mp3: can't read it as an audio file"):
            read_audio_file(path)

    def test_a_missing_file_is_an_error(self):
        with self.assertRaises(AudioFileError):
            read_audio_file(self.dir / "missing.mp3")

    def test_audio_files_are_recognized_by_extension(self):
        for name in ("song.mp3", "SONG.MP3", "song.wav", "song.flac", "song.ogg", "song.m4a"):
            self.assertTrue(is_audio_file(name), name)
        for name in ("song.mid", "clip.mp4", "image.png", "mp3"):
            self.assertFalse(is_audio_file(name), name)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class AudioClockTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeClock()
        self.clock = AudioClock(10.0, clock=self.time)

    def test_there_is_no_position_before_the_first_report(self):
        self.assertIsNone(self.clock.position())

    def test_between_reports_it_follows_the_system_clock(self):
        self.clock.report(2.0)
        self.time.now += 0.03
        self.assertAlmostEqual(self.clock.position(), 2.03)

    def test_report_jitter_is_smoothed_out(self):
        self.clock.report(2.0)
        self.time.now += 0.05
        self.clock.report(2.07)  # 20 ms ahead of the clock.
        self.assertAlmostEqual(self.clock.position(), 2.052)

    def test_steady_reports_correct_drift(self):
        self.clock.report(0.0)
        for step in range(1, 100):
            self.time.now += 0.05
            self.clock.report(step * 0.05 * 1.004)  # The sound card runs 0.4% fast.
        self.assertAlmostEqual(self.clock.position(), 99 * 0.05 * 1.004, delta=0.005)

    def test_a_big_jump_is_followed_at_once(self):
        self.clock.report(2.0)
        self.time.now += 0.05
        self.clock.report(5.0)
        self.assertAlmostEqual(self.clock.position(), 5.0)

    def test_it_wraps_at_the_end_of_the_song(self):
        self.clock.report(9.98)
        self.time.now += 0.05
        self.assertAlmostEqual(self.clock.position(), 0.03)
        # Qt's report after looping agrees, so it isn't treated as a jump.
        self.clock.report(0.031)
        self.assertAlmostEqual(self.clock.position(), 0.0301)


class HitScheduleTests(unittest.TestCase):
    def setUp(self):
        self.schedule = HitSchedule([(0.0, Band.LOW), (1.0, Band.MID), (1.0, Band.HIGH),
                                     (1.5, Band.LOW)], 2.0)

    def test_hits_at_the_start_play_straight_away(self):
        self.assertEqual(self.schedule.advance(0.01), [Band.LOW])

    def test_hits_play_once_they_are_reached(self):
        self.schedule.advance(0.01)
        self.assertEqual(self.schedule.advance(0.99), [])
        self.assertEqual(self.schedule.advance(1.0), [Band.MID, Band.HIGH])
        self.assertEqual(self.schedule.advance(1.05), [])

    def test_it_loops(self):
        for position in np.arange(0.01, 2.0, 0.05):
            self.schedule.advance(position)
        self.assertEqual(self.schedule.advance(0.02), [Band.LOW])

    def test_small_steps_back_play_nothing_twice(self):
        self.schedule.advance(0.01)
        self.schedule.advance(1.01)
        self.assertEqual(self.schedule.advance(0.995), [])
        self.assertEqual(self.schedule.advance(1.02), [])

    def test_slightly_late_hits_still_play(self):
        self.schedule.advance(0.95)
        self.assertEqual(self.schedule.advance(0.95 + LATE_LIMIT * 0.9), [Band.MID, Band.HIGH])

    def test_after_a_stall_missed_hits_are_skipped(self):
        self.schedule.advance(0.9)
        self.assertEqual(self.schedule.advance(1.6), [])
        self.assertEqual(self.schedule.advance(1.62), [])

    def test_resetting_starts_from_the_beginning(self):
        self.schedule.advance(1.2)
        self.schedule.reset()
        self.assertEqual(self.schedule.advance(0.01), [Band.LOW])


class AudioFilePlayerTests(unittest.TestCase):
    """Plays real audio, muted, so it needs a working sound system."""

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        if not QMediaDevices.audioOutputs():
            self.skipTest("needs a sound output, which build servers often lack")
        patcher = mock.patch("visual_control.audio_file.MUTED", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = write_wav(Path(temp.name) / "beat.wav", beat(np.random.default_rng(1)))

    # Build servers have no sound card, and their stand-in output stalls at the start,
    # so the player rightly skips the first hits. Timing is only meaningful on a real machine.
    @unittest.skipIf(os.environ.get("CI"), "audio timing is unreliable on build servers")
    def test_hits_are_reported_in_time_with_the_sound(self):
        analysis = read_audio_file(self.path)
        player = AudioFilePlayer(analysis, {Band.LOW: 50, Band.HIGH: 50})
        self.addCleanup(player.deleteLater)
        self.addCleanup(player.stop)
        heard = []
        player.hit.connect(lambda band: heard.append((player._clock.position(), band)))
        player.start()
        wait(2200)
        bands = [band for _, band in heard]
        self.assertEqual(bands[:4], [Band.LOW, Band.HIGH, Band.HIGH, Band.LOW])
        self.assertNotIn(Band.MID, bands)  # No effect was chosen for it.
        for (position, band), expected in zip(heard, [0.5, 0.75, 1.25, 1.5]):
            # Reported within a tick or two of where the sound is.
            self.assertAlmostEqual(position, expected, delta=TOLERANCE + 0.015)

    def test_stopping_stops_the_hits(self):
        player = AudioFilePlayer(read_audio_file(self.path), {Band.LOW: 50})
        self.addCleanup(player.deleteLater)
        heard = []
        player.hit.connect(heard.append)
        player.start()
        wait(300)
        player.stop()
        wait(400)  # Past the first kick.
        self.assertEqual(heard, [])


if __name__ == "__main__":
    unittest.main()
