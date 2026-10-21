"""Export audio envelopes and failure gates at actual file boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import UnidentifiedImageError

from lib.book.domain import all_segments, import_book, segment_fingerprint
from lib.book.models import AudioVersion, Keyframe, SoundEffect
from lib.book_audio.export import export_book
from lib.book_audio.mixer import MixEffect, SpeechClip, mix_chapter, read_audio, write_wav


def _book(root: Path):
    book = import_book("第一章 旁白。\n第二章 对白。", "边界测试")
    write_wav(root / "speech.wav", np.zeros(24000, dtype=np.float32))
    for segment in all_segments(book):
        segment.audio_versions = [
            AudioVersion(id="v", path="speech.wav", duration_seconds=1, fingerprint=segment_fingerprint(book, segment))
        ]
        segment.selected_audio_version = "v"
        segment.status = "succeeded"
    return book


def test_cross_chapter_fades_and_loop_phase_match_unsplit_render(tmp_path: Path):
    book = _book(tmp_path)
    write_wav(tmp_path / "rain.wav", np.linspace(-0.2, 0.2, 14400, dtype=np.float32))
    book.effects = [
        SoundEffect(
            id="rain",
            segment_id=all_segments(book)[0].id,
            path="rain.wav",
            duration_seconds=2,
            loop=True,
            fade_in_seconds=1.5,
            fade_out_seconds=1.5,
            track="ambience",
            ducking=1,
        )
    ]
    export_book(book, tmp_path, tmp_path / "book/export")
    receipt = json.loads((tmp_path / "book/export.json").read_text())
    expected = mix_chapter(
        [SpeechClip(tmp_path / "speech.wav"), SpeechClip(tmp_path / "speech.wav")],
        [
            MixEffect(
                tmp_path / "rain.wav",
                0,
                2,
                fade_in_seconds=1.5,
                fade_out_seconds=1.5,
                loop=True,
                track="ambience",
                duck_db=0,
            )
        ],
        tmp_path / "unsplit.wav",
    )
    np.testing.assert_allclose(
        read_audio(tmp_path / receipt["whole_book_path"]), read_audio(expected.path), atol=0.00007
    )
    chapters = [read_audio(tmp_path / chapter["path"]) for chapter in receipt["chapters"]]
    assert abs(chapters[0][-1] - chapters[1][0]) < 0.001


def test_digest_mismatch_blocks_export_before_receipt(tmp_path: Path):
    book = _book(tmp_path)
    all_segments(book)[0].audio_versions[0].content_digest = hashlib.sha256(b"different bytes").hexdigest()
    with pytest.raises(ValueError, match="content changed"):
        export_book(book, tmp_path, tmp_path / "book/export")
    assert not (tmp_path / "book/export.json").exists()


def test_invalid_image_does_not_publish_success_receipt(tmp_path: Path):
    book = _book(tmp_path)
    (tmp_path / "invalid.png").write_bytes(b"not a PNG")
    book.keyframes = [Keyframe(id="image", segment_id=all_segments(book)[0].id, path="invalid.png", status="succeeded")]
    with pytest.raises(UnidentifiedImageError):
        export_book(book, tmp_path, tmp_path / "book/export", illustrated=True)
    assert not (tmp_path / "book/export.json").exists()


def test_effect_beyond_book_is_not_silently_truncated(tmp_path: Path):
    book = _book(tmp_path)
    book.effects = [
        SoundEffect(id="rain", segment_id=all_segments(book)[0].id, path="speech.wav", duration_seconds=3, loop=True)
    ]
    with pytest.raises(ValueError, match="beyond book"):
        export_book(book, tmp_path, tmp_path / "book/export")
    assert not (tmp_path / "book/export.json").exists()


def test_late_first_image_rejected_instead_of_empty_initial_playback(tmp_path: Path):
    from PIL import Image

    book = _book(tmp_path)
    Image.new("RGB", (8, 8), "red").save(tmp_path / "image.png")
    book.keyframes = [
        Keyframe(
            id="image", segment_id=all_segments(book)[0].id, offset_seconds=0.5, path="image.png", status="succeeded"
        )
    ]
    with pytest.raises(ValueError, match="no keyframe"):
        export_book(book, tmp_path, tmp_path / "book/export", illustrated=True)
