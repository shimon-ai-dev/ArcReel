"""Create a clearly labelled synthetic audio/image package for player and mixing QA.

Run: uv run python scripts/book/make_fixture.py /tmp/book-fixture
This is not TTS output and is never evidence of model integration.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from lib.book.domain import import_book, segment_fingerprint
from lib.book.models import AudioVersion, Keyframe, SoundEffect
from lib.book_audio.export import export_book
from lib.book_audio.mixer import write_wav


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    book = import_book(
        "第一章\n这是播放器验证。\n第二章\n这是第二章节。", "合成测试音，不是真实模型语音", max_segment_chars=12
    )
    write_wav(root / "speech.wav", np.sin(np.arange(48000) * 0.05).astype(np.float32) * 0.05)
    write_wav(root / "ambience.wav", np.sin(np.arange(24000) * 0.01).astype(np.float32) * 0.02)
    for index, color in enumerate(["red", "blue"]):
        Image.new("RGB", (640, 360), color).save(root / f"image-{index}.png")
    for index, chapter in enumerate(book.chapters):
        for segment in chapter.segments:
            segment.audio_versions = [
                AudioVersion(
                    id="v1", path="speech.wav", duration_seconds=2, fingerprint=segment_fingerprint(book, segment)
                )
            ]
            segment.selected_audio_version = "v1"
            segment.status = "succeeded"
            segment.pause_after_seconds = 0.25
        book.keyframes.append(
            Keyframe(
                id=f"frame{index}", segment_id=chapter.segments[0].id, path=f"image-{index}.png", status="succeeded"
            )
        )
        if len(chapter.segments) > 1:
            book.keyframes.append(
                Keyframe(
                    id=f"frame{index}b",
                    segment_id=chapter.segments[1].id,
                    path=f"image-{1 - index}.png",
                    status="succeeded",
                )
            )
    book.effects.append(
        SoundEffect(
            id="ambience",
            track="ambience",
            segment_id=book.chapters[0].segments[0].id,
            path="ambience.wav",
            duration_seconds=2,
            loop=True,
            source="synthetic sine-wave QA fixture",
        )
    )
    print(export_book(book, root, root / "book/export", illustrated=True))


if __name__ == "__main__":
    main()
