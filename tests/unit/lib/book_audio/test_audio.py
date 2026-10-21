"""Book audio contracts, independent of any live model service."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.book_audio.mixer import MixEffect, SpeechClip, concatenate_chapters, mix_chapter, read_audio, write_wav
from lib.book_audio.tts import BookSynthesisRequest, IndexTTS2HTTPAdapter, UnsupportedSpeechControl, validate_controls


def test_sample_clock_pauses_and_ducking(tmp_path: Path):
    voice = tmp_path / "voice.wav"
    background = tmp_path / "rain.wav"
    write_wav(voice, np.full(24000, 0.25, dtype=np.float32))
    write_wav(background, np.full(24000, 0.25, dtype=np.float32))
    result = mix_chapter(
        [SpeechClip(voice, 0.5), SpeechClip(voice, 0.25)],
        [MixEffect(background, 0, 2.75, loop=True, track="ambience", duck_db=-20)],
        tmp_path / "chapter.wav",
    )
    samples = read_audio(result.path)
    assert result.duration_seconds == 2.75
    assert result.speech_starts == (0, 1.5)
    assert result.speech_durations == (1, 1)
    assert samples[100] == pytest.approx(0.275, abs=0.0001)
    assert samples[25000] == pytest.approx(0.25, abs=0.0001)
    assert concatenate_chapters([result.path, result.path], tmp_path / "book.wav") == 5.5


def test_explicit_pause_is_silence_and_fades_are_measurable(tmp_path: Path):
    voice = tmp_path / "voice.wav"
    write_wav(voice, np.full(2400, 0.2, dtype=np.float32))
    mixed = mix_chapter([SpeechClip(voice, 0.1)], [], tmp_path / "out.wav")
    assert np.count_nonzero(read_audio(mixed.path)[2400:]) == 0
    with pytest.raises(ValueError, match="beyond"):
        mix_chapter([SpeechClip(voice)], [MixEffect(voice, 0.2)], tmp_path / "bad.wav")


def test_index_controls_reject_unreleased_speed_and_nonverbal(tmp_path: Path):
    adapter = IndexTTS2HTTPAdapter("http://127.0.0.1:7861")
    with pytest.raises(UnsupportedSpeechControl, match="speed"):
        validate_controls(BookSynthesisRequest("正文", tmp_path / "a.wav", speed=1.2), adapter.capabilities)
    with pytest.raises(UnsupportedSpeechControl, match="nonverbal"):
        validate_controls(BookSynthesisRequest("正文", tmp_path / "a.wav", nonverbal="gasp"), adapter.capabilities)
    with pytest.raises(ValueError, match="eight"):
        validate_controls(BookSynthesisRequest("正文", tmp_path / "a.wav", emotion_vector=(1,)), adapter.capabilities)


def test_export_requires_complete_audio_and_retimes_keyframes(tmp_path: Path):
    from lib.book.domain import import_book, segment_fingerprint
    from lib.book.models import AudioVersion, Keyframe
    from lib.book_audio.export import build_book_package

    book = import_book("第一章\n你好。\n第二章\n再见。", "示例", max_segment_chars=6)
    with pytest.raises(ValueError, match="not ready"):
        build_book_package(book, tmp_path, tmp_path / "missing")
    write_wav(tmp_path / "speech.wav", np.full(2400, 0.1, dtype=np.float32))
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "image.png")
    for chapter in book.chapters:
        for segment in chapter.segments:
            segment.audio_versions = [
                AudioVersion(
                    id="v1", path="speech.wav", duration_seconds=99, fingerprint=segment_fingerprint(book, segment)
                )
            ]
            segment.selected_audio_version = "v1"
            segment.status = "succeeded"
        book.keyframes.append(
            Keyframe(id=chapter.id, segment_id=chapter.segments[0].id, path="image.png", status="succeeded")
        )
    manifest = build_book_package(book, tmp_path, tmp_path / "export", illustrated=True)
    assert len(manifest["chapters"]) == 2
    assert manifest["chapters"][0]["duration_seconds"] < 1
    assert all(chapter["keyframes"][0]["time"] == 0 for chapter in manifest["chapters"])
    assert manifest["validation"]["speech_quality"] == "not_reviewed"
    assert (tmp_path / "export/index.html").is_file()
    assert (tmp_path / "export/audio/book.wav").is_file()


def test_fade_endpoints_and_loop_period_are_measured_samples(tmp_path: Path):
    write_wav(tmp_path / "silence.wav", np.zeros(24000, dtype=np.float32))
    write_wav(tmp_path / "constant.wav", np.full(6000, 0.5, dtype=np.float32))
    result = mix_chapter(
        [SpeechClip(tmp_path / "silence.wav")],
        [MixEffect(tmp_path / "constant.wav", 0, 1, loop=True, fade_in_seconds=0.25, fade_out_seconds=0.25)],
        tmp_path / "faded.wav",
    )
    samples = read_audio(result.path)
    assert samples[0] == samples[-1] == 0
    assert samples[3000] == pytest.approx(0.25, abs=0.0001)
    assert samples[9000] == samples[15000] == pytest.approx(0.5, abs=0.0001)
    assert samples[21000] == pytest.approx(0.25, abs=0.0001)
