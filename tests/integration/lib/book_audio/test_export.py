"""Real ffmpeg export validation with synthetic input, not a real speech model test."""

import json
import zipfile
from pathlib import Path

import numpy as np

from lib.book.domain import import_book, segment_fingerprint
from lib.book.models import AudioVersion
from lib.book.status import book_status
from lib.book_audio.export import export_book
from lib.book_audio.mixer import read_audio, write_wav


def test_mp3_package_receipt_and_whole_book_audio(tmp_path: Path):
    book = import_book("第一章\n测试声音。", "音频测试")
    write_wav(tmp_path / "speech.wav", np.sin(np.arange(24000) * 0.1).astype(np.float32) * 0.1)
    for chapter in book.chapters:
        for segment in chapter.segments:
            segment.audio_versions = [
                AudioVersion(
                    id="v1", path="speech.wav", duration_seconds=1, fingerprint=segment_fingerprint(book, segment)
                )
            ]
            segment.selected_audio_version = "v1"
            segment.status = "succeeded"
    archive = export_book(book, tmp_path, tmp_path / "book/export", format="mp3")
    receipt = json.loads((tmp_path / "book/export.json").read_text())
    assert book_status(book, tmp_path)["complete"] is True
    assert len(read_audio(tmp_path / receipt["whole_book_path"])) > 0
    with zipfile.ZipFile(archive) as package:
        assert {"index.html", "manifest.json", "audio/book.mp3", "audio/chapter-1.mp3"} <= set(package.namelist())
