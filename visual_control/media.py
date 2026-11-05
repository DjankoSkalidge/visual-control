"""Loads images and videos and hands out frames as NumPy arrays at the right time."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_LONG_SIDE = 1920
MAX_SHORT_SIDE = 1080
FALLBACK_FRAME_SECONDS = 1 / 25
QUEUE_SIZE = 8


class MediaError(Exception):
    """The file could not be opened as an image or video."""


def _describe_failure(exc: Exception) -> str:
    if isinstance(exc, MediaError):
        return str(exc)
    if isinstance(exc, av.error.DecoderNotFoundError):
        return "its video format can't be decoded, or it may be copy-protected"
    return "it's damaged or isn't a supported image or video"


def fit_size(width: int, height: int) -> tuple[int, int]:
    """Scale down to fit 1080p in either orientation; never scale up."""
    scale = min(
        MAX_LONG_SIDE / max(width, height),
        MAX_SHORT_SIDE / min(width, height),
        1.0,
    )
    return max(1, round(width * scale)), max(1, round(height * scale))


class ImageSource:
    """A still image: one frame, delivered once."""

    error: str | None = None

    def __init__(self, pixels: np.ndarray) -> None:
        self._pixels: np.ndarray | None = pixels

    def next_frame(self, now: float) -> np.ndarray | None:
        pixels, self._pixels = self._pixels, None
        return pixels

    def toggle_pause(self, now: float) -> bool | None:
        return None  # A still image has nothing to pause.

    def set_speed(self, speed: float, now: float) -> None:
        pass  # A still image has nothing to speed up.

    def stop(self) -> None:
        pass


@dataclass(frozen=True)
class _TimedFrame:
    pixels: np.ndarray
    time: float


class VideoSource:
    """Decodes a video on a background thread and loops it forever."""

    def __init__(self, path: str) -> None:
        self.error: str | None = None
        self._path = path
        self._frames: queue.Queue[_TimedFrame] = queue.Queue(maxsize=QUEUE_SIZE)
        self._stopping = threading.Event()
        self._pending: _TimedFrame | None = None
        # The clock: how far into the video playback has got, in the video's own
        # seconds, as of the last time it was brought up to date.
        self._position: float | None = None  # None until the first frame arrives.
        self._position_updated: float = 0.0
        self._last_shown_time: float | None = None
        self._speed = 1.0
        self._paused = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def next_frame(self, now: float) -> np.ndarray | None:
        """Return the newest frame that is due, dropping any that are late."""
        self._update_position(now)
        if self._paused:
            return None
        latest = None
        while True:
            if self._pending is None:
                try:
                    self._pending = self._frames.get_nowait()
                except queue.Empty:
                    # The decoder is behind. Don't let the clock run ahead of it, or
                    # slowing down later wouldn't take effect until it had caught up.
                    if self._last_shown_time is not None:
                        self._position = min(self._position, self._last_shown_time)
                    return latest
            if self._position is None:
                self._position = self._pending.time
            if self._pending.time > self._position:
                return latest
            latest = self._pending.pixels
            self._last_shown_time = self._pending.time
            self._pending = None

    def toggle_pause(self, now: float) -> bool:
        """Pause or resume, and return whether it's now paused.

        While paused, the frame queue fills up, which holds the decoder without using CPU.
        """
        self._update_position(now)
        self._paused = not self._paused
        return self._paused

    def set_speed(self, speed: float, now: float) -> None:
        """Change how fast the clock runs, where 1.0 is normal. Takes effect immediately."""
        self._update_position(now)
        self._speed = speed

    def _update_position(self, now: float) -> None:
        if self._position is not None and not self._paused:
            self._position += (now - self._position_updated) * self._speed
        self._position_updated = now

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        loop_start = 0.0
        try:
            while not self._stopping.is_set():
                # Reopening rather than seeking loops every format reliably,
                # including ones that can't seek, such as GIF.
                loop_length = self._play_once(loop_start)
                if loop_length is None:
                    return
                loop_start += loop_length
        except Exception as exc:
            self.error = _describe_failure(exc)

    def _play_once(self, loop_start: float) -> float | None:
        """Queue one pass of the file. Returns its length, or None if stopped."""
        with av.open(self._path) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            rate = float(stream.average_rate or 0)
            frame_seconds = 1 / rate if rate > 0 else FALLBACK_FRAME_SECONDS

            first_time = None
            count = 0
            end = 0.0
            for frame in container.decode(stream):
                time = frame.time if frame.time is not None else count * frame_seconds
                if first_time is None:
                    first_time = time
                offset = time - first_time
                end = offset + frame_seconds
                count += 1
                if not self._put(_TimedFrame(_to_pixels(frame), loop_start + offset)):
                    return None
            if count == 0:
                raise MediaError("the video contains no frames")
            return end

    def _put(self, frame: _TimedFrame) -> bool:
        while not self._stopping.is_set():
            try:
                self._frames.put(frame, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False


def _to_pixels(frame: av.VideoFrame) -> np.ndarray:
    width, height = fit_size(frame.width, frame.height)
    pixels = frame.reformat(width, height, format="rgb24").to_ndarray()
    # Phone videos are often stored sideways, with their rotation in metadata.
    quarter_turns = round(frame.rotation / 90) % 4
    if quarter_turns:
        pixels = np.rot90(pixels, quarter_turns)
    # The decoder pads rows to a memory alignment, which the GPU upload can't take.
    # This only copies when the rows aren't already tightly packed.
    return np.ascontiguousarray(pixels)


def _load_image(image: Image.Image) -> ImageSource:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail(fit_size(*image.size), Image.Resampling.LANCZOS)
    # Flatten transparency onto black so every frame reaches the filters as RGB.
    background = Image.new("RGBA", image.size, "black")
    return ImageSource(np.asarray(Image.alpha_composite(background, image).convert("RGB")))


def open_media(path: str) -> ImageSource | VideoSource:
    """Open a file by its contents, so its extension doesn't matter."""
    try:
        try:
            with Image.open(path) as image:
                if not getattr(image, "is_animated", False):
                    return _load_image(image)
        except UnidentifiedImageError:
            pass  # Not an image, so try it as a video.

        with av.open(path) as container:
            if not container.streams.video:
                raise MediaError("it has no video")
            # Opening only reads the header, so decode a frame to prove the file
            # plays before it replaces whatever is on screen.
            first_frame = next(container.decode(container.streams.video[0]), None)
            if first_frame is None:
                raise MediaError("the video contains no frames")
            _to_pixels(first_frame)
        return VideoSource(path)
    except Exception as exc:
        raise MediaError(f"Can't open {Path(path).name}: {_describe_failure(exc)}") from exc
