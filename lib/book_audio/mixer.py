"""Sample-clock chapter mixing with explicit silence and non-destructive source tracks."""

from __future__ import annotations

import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from lib.infra.ffmpeg import ffmpeg_executable, local_file_input

SAMPLE_RATE = 24000


@dataclass(frozen=True)
class SpeechClip:
    path: Path
    pause_after_seconds: float = 0


@dataclass(frozen=True)
class MixEffect:
    path: Path
    start_seconds: float
    duration_seconds: float | None = None
    gain_db: float = 0
    fade_in_seconds: float = 0
    fade_out_seconds: float = 0
    loop: bool = False
    track: Literal["sfx", "ambience", "music"] = "sfx"
    duck_db: float = -12
    source_offset_seconds: float = 0
    envelope_duration_seconds: float | None = None


@dataclass(frozen=True)
class MixResult:
    path: Path
    duration_seconds: float
    speech_starts: tuple[float, ...]
    speech_durations: tuple[float, ...]
    clipped_samples: int


def read_audio(path: Path, sample_rate: int = SAMPLE_RATE) -> NDArray[np.float32]:
    """Decode local media to mono PCM with network protocols disabled."""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as source:
                if source.getsampwidth() == 2 and source.getframerate() == sample_rate:
                    channels = source.getnchannels()
                    samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32)
                    return (samples.reshape(-1, channels).mean(axis=1) / 32768).astype(np.float32)
        except (wave.Error, EOFError):
            # IEEE float WAV and other formats unsupported by stdlib go through ffmpeg.
            pass
    result = subprocess.run(
        [
            ffmpeg_executable(),
            "-nostdin",
            "-v",
            "error",
            *local_file_input(path),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def write_wav(path: Path, samples: NDArray[np.float32], sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def mix_chapter(
    speech: list[SpeechClip],
    effects: list[MixEffect],
    output_path: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> MixResult:
    """Render from actual decoded frame counts. Background ducking follows voiced intervals.

    Source files are never changed. Effects outside the chapter are rejected rather
    than silently truncated; a loop requires an explicit duration. PCM output is
    peak-normalized only when necessary, and the pre-normalization clipping count
    is returned separately from any human speech-quality review.
    """
    if not speech:
        raise ValueError("A chapter must contain speech")
    clips = []
    starts = []
    durations = []
    cursor = 0
    intervals = []
    for clip in speech:
        if not math.isfinite(clip.pause_after_seconds) or not 0 <= clip.pause_after_seconds <= 120:
            raise ValueError("Invalid explicit pause")
        samples = read_audio(clip.path, sample_rate)
        if not len(samples) or not np.isfinite(samples).all():
            raise ValueError("Speech audio is empty or invalid")
        starts.append(cursor / sample_rate)
        durations.append(len(samples) / sample_rate)
        intervals.append((cursor, cursor + len(samples)))
        pause = np.zeros(round(clip.pause_after_seconds * sample_rate), dtype=np.float32)
        clips.extend([samples, pause])
        cursor += len(samples) + len(pause)
    output = np.concatenate(clips)
    for effect in effects:
        numeric = [
            effect.start_seconds,
            effect.gain_db,
            effect.fade_in_seconds,
            effect.fade_out_seconds,
            effect.duck_db,
            effect.source_offset_seconds,
        ]
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Effect parameters must be finite")
        if (
            effect.start_seconds < 0
            or effect.fade_in_seconds < 0
            or effect.fade_out_seconds < 0
            or effect.source_offset_seconds < 0
        ):
            raise ValueError("Effect times cannot be negative")
        if not -120 <= effect.gain_db <= 24 or not -120 <= effect.duck_db <= 0:
            raise ValueError("Invalid gain or ducking")
        if effect.loop and effect.duration_seconds is None:
            raise ValueError("Looping effects require a duration")
        samples = read_audio(effect.path, sample_rate)
        if not len(samples) or not np.isfinite(samples).all():
            raise ValueError("Effect audio is empty or invalid")
        start = round(effect.start_seconds * sample_rate)
        duration = effect.duration_seconds
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise ValueError("Effect duration must be positive")
        count = round(duration * sample_rate) if duration is not None else len(samples)
        if start + count > len(output):
            raise ValueError("Effect extends beyond the chapter; shorten its duration")
        offset = round(effect.source_offset_seconds * sample_rate)
        if effect.loop:
            offset %= len(samples)
            samples = np.tile(samples, math.ceil((count + offset) / len(samples)))[offset : offset + count]
        else:
            samples = samples[offset : offset + count]
            samples = np.pad(samples, (0, max(0, count - len(samples))))
        samples = samples * (10 ** (effect.gain_db / 20))
        envelope_duration = effect.envelope_duration_seconds
        if envelope_duration is not None and (not math.isfinite(envelope_duration) or envelope_duration <= 0):
            raise ValueError("Effect envelope duration must be positive")
        total_frames = round(envelope_duration * sample_rate) if envelope_duration is not None else count
        envelope_offset = round(effect.source_offset_seconds * sample_rate) if envelope_duration is not None else 0
        positions = np.arange(count) + envelope_offset
        fade_in = min(total_frames, round(effect.fade_in_seconds * sample_rate))
        fade_out = min(total_frames, round(effect.fade_out_seconds * sample_rate))
        if fade_in:
            samples *= np.clip(positions / max(1, fade_in - 1), 0, 1)
        if fade_out:
            samples *= np.clip((total_frames - 1 - positions) / max(1, fade_out - 1), 0, 1)
        if effect.track in ("ambience", "music"):
            for speech_start, speech_end in intervals:
                left, right = max(start, speech_start), min(start + count, speech_end)
                if right > left:
                    samples[left - start : right - start] *= 10 ** (effect.duck_db / 20)
        output[start : start + count] += samples
    clipped = int(np.count_nonzero(np.abs(output) > 1))
    peak = float(np.max(np.abs(output)))
    if peak > 1:
        output /= peak
    write_wav(output_path, output, sample_rate)
    return MixResult(output_path, len(output) / sample_rate, tuple(starts), tuple(durations), clipped)


def concatenate_chapters(paths: list[Path], output_path: Path, *, sample_rate: int = SAMPLE_RATE) -> float:
    """Stream chapters to a whole-book WAV without holding the whole book in memory."""
    if not paths:
        raise ValueError("No chapter audio to concatenate")
    frames = 0
    with wave.open(str(output_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        for path in paths:
            samples = read_audio(path, sample_rate)
            target.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            frames += len(samples)
    return frames / sample_rate


def encode_mp3(source: Path, output: Path) -> None:
    subprocess.run(
        [
            ffmpeg_executable(),
            "-nostdin",
            "-v",
            "error",
            "-y",
            *local_file_input(source),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
