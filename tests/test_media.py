import random
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from visual_control.media import ImageSource, MediaError, VideoSource, fit_size, open_media


def make_video(path: Path, *options: str, size: str = "64x48", seconds: str = "0.5") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=red:s={size}:r=20:d={seconds}", *options, str(path)],
        check=True,
    )


def make_damaged_late_video(path: Path) -> None:
    """A video whose start plays normally and whose middle is overwritten with noise."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=s=1280x720:r=30:d=2", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-g", "30", str(path)],
        check=True,
    )
    data = bytearray(path.read_bytes())
    third = len(data) // 3
    data[third : 2 * third] = random.Random(1).randbytes(third)
    path.write_bytes(data)


def wait_for_frame(source, timeout: float = 5.0) -> np.ndarray:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = source.next_frame(time.monotonic())
        if frame is not None:
            return frame
        time.sleep(0.002)
    raise AssertionError(f"no frame arrived; source error: {source.error}")


class FitSizeTests(unittest.TestCase):
    def test_keeps_small_media_unchanged(self):
        self.assertEqual(fit_size(640, 480), (640, 480))

    def test_scales_4k_landscape_to_1080p(self):
        self.assertEqual(fit_size(3840, 2160), (1920, 1080))

    def test_scales_4k_portrait_to_1080p(self):
        self.assertEqual(fit_size(2160, 3840), (1080, 1920))


class OpenMediaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def open_video(self, path: Path) -> VideoSource:
        source = open_media(str(path))
        self.addCleanup(source.stop)
        self.assertIsInstance(source, VideoSource)
        return source

    def test_image_is_delivered_once(self):
        path = self.dir / "still.png"
        Image.new("RGB", (8, 4), "blue").save(path)
        source = open_media(str(path))
        self.assertIsInstance(source, ImageSource)
        frame = source.next_frame(0.0)
        self.assertEqual(frame.shape, (4, 8, 3))
        self.assertEqual(tuple(frame[0, 0]), (0, 0, 255))
        self.assertIsNone(source.next_frame(1.0))

    def test_image_is_identified_by_contents_not_extension(self):
        path = self.dir / "still.mp4"
        Image.new("RGB", (8, 4), "blue").save(path, format="PNG")
        self.assertIsInstance(open_media(str(path)), ImageSource)

    def test_large_image_is_scaled_to_1080p(self):
        path = self.dir / "large.png"
        Image.new("RGB", (3840, 2160), "blue").save(path)
        self.assertEqual(open_media(str(path)).next_frame(0.0).shape, (1080, 1920, 3))

    def test_transparent_image_is_flattened_onto_black(self):
        path = self.dir / "transparent.png"
        Image.new("RGBA", (4, 4), (255, 255, 255, 128)).save(path)
        red, green, blue = open_media(str(path)).next_frame(0.0)[0, 0]
        self.assertTrue(red == green == blue)
        self.assertAlmostEqual(int(red), 128, delta=2)

    def test_video_colors_survive_decoding(self):
        path = self.dir / "red.mp4"
        make_video(path, "-pix_fmt", "yuv420p")
        red, green, blue = wait_for_frame(self.open_video(path))[10, 10]
        self.assertGreater(red, 230)
        self.assertLess(green, 25)
        self.assertLess(blue, 25)

    def test_video_loops_seamlessly(self):
        path = self.dir / "short.mp4"
        make_video(path, "-pix_fmt", "yuv420p", seconds="0.25")
        source = self.open_video(path)
        arrivals = []
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            if source.next_frame(time.monotonic()) is not None:
                arrivals.append(time.monotonic())
            time.sleep(0.002)
        self.assertIsNone(source.error)
        self.assertGreater(len(arrivals), 15, "should keep playing past several loops")
        self.assertLess(max(np.diff(arrivals)), 0.2, "loop point should not stall")

    def test_frames_are_tightly_packed_at_any_width(self):
        # Decoders pad rows to a memory alignment, and the GPU upload can't take padding.
        for width, height in ((854, 480), (426, 240), (1080, 1920), (1918, 1080), (640, 360)):
            with self.subTest(width=width, height=height):
                path = self.dir / f"{width}x{height}.mp4"
                make_video(path, "-pix_fmt", "yuv420p", size=f"{width}x{height}", seconds="0.1")
                frame = wait_for_frame(self.open_video(path))
                self.assertEqual(frame.shape, (height, width, 3))
                self.assertTrue(frame.flags["C_CONTIGUOUS"])

    def test_padded_frames_match_ffmpegs_own_decode(self):
        # A detailed picture, so misread rows would be far from FFmpeg's result.
        width, height = 854, 480
        path = self.dir / "detailed.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"testsrc2=s={width}x{height}:r=20:d=0.1", "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        raw = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(path), "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            check=True, capture_output=True,
        ).stdout
        expected = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
        frame = wait_for_frame(self.open_video(path))
        self.assertLess(np.abs(frame.astype(int) - expected).mean(), 5)

    def test_animated_gif_plays_as_video(self):
        path = self.dir / "anim.gif"
        frames = [Image.new("RGB", (8, 8), color) for color in ("red", "lime", "blue")]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=50)
        self.assertEqual(wait_for_frame(self.open_video(path)).shape, (8, 8, 3))

    def test_rotated_video_is_displayed_upright(self):
        # Red on the left, blue on the right. A -90 rotation turns the picture
        # clockwise, which moves the left side to the top.
        plain = self.dir / "plain.mp4"
        rotated = self.dir / "rotated.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=red:s=64x48:r=20:d=0.5",
             "-f", "lavfi", "-i", "color=blue:s=32x48:r=20:d=0.5",
             "-filter_complex", "[0][1]overlay=32:0", "-pix_fmt", "yuv444p", str(plain)],
            check=True,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "-90",
             "-i", str(plain), "-c", "copy", str(rotated)],
            check=True,
        )
        frame = wait_for_frame(self.open_video(rotated))
        self.assertEqual(frame.shape, (64, 48, 3))
        self.assertGreater(frame[2, 24][0], 230, "top should be red")
        self.assertGreater(frame[-3, 24][2], 230, "bottom should be blue")

    def test_non_media_file_is_rejected_with_its_name(self):
        path = self.dir / "notes.txt"
        path.write_text("not media")
        with self.assertRaisesRegex(MediaError, "notes.txt"):
            open_media(str(path))

    def assert_rejected(self, path: Path, reason: str) -> None:
        with self.assertRaisesRegex(MediaError, f"{path.name}.*{reason}"):
            open_media(str(path))

    def test_truncated_video_is_rejected(self):
        path = self.dir / "cut.mp4"
        make_video(path, "-pix_fmt", "yuv420p")
        path.write_bytes(path.read_bytes()[:500])
        self.assert_rejected(path, "damaged")

    def test_video_with_destroyed_frames_is_rejected(self):
        path = self.dir / "zeroed.mp4"
        make_video(path, "-pix_fmt", "yuv420p", size="640x360", seconds="2")
        data = bytearray(path.read_bytes())
        start = data.index(b"mdat") + 4
        data[start : start + 4000] = bytes(4000)
        path.write_bytes(data)
        self.assert_rejected(path, "damaged")

    def test_undecodable_codec_is_rejected(self):
        path = self.dir / "protected.m4v"
        make_video(path, "-pix_fmt", "yuv420p", "-c:v", "libx264", "-f", "mp4")
        path.write_bytes(path.read_bytes().replace(b"avc1", b"drms"))
        self.assert_rejected(path, "copy-protected")

    def test_damage_later_in_a_video_ends_playback_with_a_readable_error(self):
        path = self.dir / "late_damage.mp4"
        make_damaged_late_video(path)
        source = self.open_video(path)
        deadline = time.monotonic() + 10
        while source.error is None and time.monotonic() < deadline:
            source.next_frame(time.monotonic())
            time.sleep(0.003)
        self.assertIn("damaged", source.error)
        source._thread.join(timeout=2)
        self.assertFalse(source._thread.is_alive())

    def test_pausing_a_video_holds_its_frames_and_resuming_loses_none(self):
        path = self.dir / "steady.mp4"
        make_video(path, "-pix_fmt", "yuv420p", seconds="2")
        source = self.open_video(path)
        wait_for_frame(source)

        self.assertTrue(source.toggle_pause(time.monotonic()))
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            self.assertIsNone(source.next_frame(time.monotonic()))
            time.sleep(0.01)
        self.assertFalse(source.toggle_pause(time.monotonic()))

        # 20 frames per second. Had the clock kept running through the pause, the queued
        # frames would all be late and get dropped.
        delivered = 0
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            delivered += source.next_frame(time.monotonic()) is not None
            time.sleep(0.002)
        self.assertGreaterEqual(delivered, 8)
        self.assertLessEqual(delivered, 12)

    def test_stop_ends_the_decoder_thread(self):
        path = self.dir / "short.mp4"
        make_video(path, "-pix_fmt", "yuv420p")
        source = open_media(str(path))
        wait_for_frame(source)
        source.stop()
        self.assertFalse(source._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
