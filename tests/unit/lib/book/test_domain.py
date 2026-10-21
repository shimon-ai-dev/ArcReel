"""Book fidelity, audio identity and anchored retiming contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.book.domain import (
    BookValidationError,
    all_segments,
    book_fingerprint,
    build_timeline,
    import_book,
    invalidate_changed_audio,
    segment_fingerprint,
    selected_audio,
    spoken_text,
    validate_coverage,
)
from lib.book.models import AudioVersion, Keyframe, PronunciationOverride, SoundEffect, VoiceProfile
from lib.book.status import book_status
from lib.book.store import BookConflictError, BookStore
from lib.infra.content_digest import sha256_file
from lib.infra.json_io import atomic_write_json
from lib.project.project_manager import ProjectManager


def test_import_preserves_original_normalizes_and_keeps_chapter_headings() -> None:
    text = "第一章 雨夜\r\n小明说：“谁在那里？”\r\n小红喘息着说：“是我！”\r\n第二章 门外\r\n风吹过 cafe\u0301。"
    book = import_book(text, "雨夜", max_segment_chars=12)
    assert book.original_text == text
    assert book.normalized_text == text.replace("\r\n", "\n").replace("e\u0301", "é")
    assert "".join(segment.text for segment in all_segments(book)) == book.normalized_text
    assert len(book.chapters) == 2
    assert book.chapters[0].title == "第一章 雨夜"
    assert [segment.id for segment in all_segments(book)] == [
        segment.id for segment in all_segments(import_book(text, "雨夜", max_segment_chars=12))
    ]
    assert all(not segment.speaker_confirmed for segment in all_segments(book))


@pytest.mark.parametrize("fault", ["gap", "duplicate", "reorder", "rewrite", "tail"])
def test_export_coverage_rejects_source_damage(fault: str) -> None:
    book = import_book("他说你好。她说再见。", max_segment_chars=5)
    segments = book.chapters[0].segments
    if fault == "gap":
        segments[1].source_start += 1
    elif fault == "duplicate":
        segments[1].id = segments[0].id
    elif fault == "reorder":
        segments.reverse()
    elif fault == "rewrite":
        segments[0].text = "你好。"
    else:
        segments.pop()
    with pytest.raises(BookValidationError):
        validate_coverage(book)


def test_pronunciation_remains_aligned_and_performance_is_not_spoken() -> None:
    book = import_book("他在重庆。")
    segment = all_segments(book)[0]
    segment.pronunciation = [PronunciationOverride(source_start=2, source_end=4, original="重庆", spoken="重慶")]
    segment.performance.emotion = "surprised"
    segment.performance.nonverbal = "gasp"
    validate_coverage(book)
    assert spoken_text(segment) == "他在重慶。"
    assert segment.text == "他在重庆。"
    segment.pronunciation[0].original = "北京"
    with pytest.raises(BookValidationError, match="mismatch"):
        validate_coverage(book)


def test_voice_and_text_cache_invalidate_only_affected_speech_and_retime_events() -> None:
    book = import_book("甲说你好。乙说再见。", max_segment_chars=5)
    first, second = all_segments(book)
    first.speaker_id, second.speaker_id = "a", "b"
    book.voices = {key: VoiceProfile(id=key, model="local", voice=key) for key in ("a", "b")}
    for segment in (first, second):
        segment.audio_versions.append(
            AudioVersion(
                id="v1",
                path=f"book/{segment.id}.wav",
                duration_seconds=2,
                fingerprint=segment_fingerprint(book, segment),
            )
        )
        segment.selected_audio_version = "v1"
        segment.status = "succeeded"
    first.pause_after_seconds = 0.5
    book.effects = [SoundEffect(id="steps", segment_id=second.id, path="book/steps.wav", duration_seconds=1)]
    book.keyframes = [Keyframe(id="frame", segment_id=second.id)]
    timeline = build_timeline(book, require_audio=True)
    assert timeline.effects[0].start_seconds == 2.5
    assert timeline.keyframes[0].start_seconds == 2.5
    before = book_fingerprint(book)
    first.pause_after_seconds = 1
    assert selected_audio(book, first) is not None
    assert build_timeline(book, require_audio=True).keyframes[0].start_seconds == 3
    assert book_fingerprint(book) != before
    book.voices["a"].voice = "replacement"
    assert invalidate_changed_audio(book) == [first.id]
    assert selected_audio(book, second) is not None
    assert len(first.audio_versions) == 1
    with pytest.raises(BookValidationError, match="missing or stale"):
        build_timeline(book, require_audio=True)
    first.audio_versions.append(
        AudioVersion(id="v2", path="book/new.wav", duration_seconds=4, fingerprint=segment_fingerprint(book, first))
    )
    first.selected_audio_version = "v2"
    assert build_timeline(book, require_audio=True).effects[0].start_seconds == 5


def test_store_revision_conflict_and_failed_segment_survive_reopen(tmp_path: Path) -> None:
    projects = ProjectManager(tmp_path)
    (projects.projects_dir / "test-book").mkdir(parents=True)
    store = BookStore(projects, "test-book")
    book = store.save(import_book("第一句。第二句。", max_segment_chars=4))
    assert book.revision == 1
    stale = book.model_copy(deep=True)
    book.chapters[0].segments[1].status = "failed"
    book.chapters[0].segments[1].error = "service unavailable"
    store.save(book)
    reopened = BookStore(projects, "test-book").load()
    assert reopened.chapters[0].segments[1].error == "service unavailable"
    with pytest.raises(BookConflictError):
        store.save(stale)
    result = store.update(lambda current: setattr(current.chapters[0].segments[1], "status", "queued"))
    assert result.revision == 3
    assert result.chapters[0].segments[1].status == "queued"


def test_completion_requires_successful_current_export_not_just_audio(tmp_path: Path) -> None:
    book = import_book("你好。")
    segment = all_segments(book)[0]
    segment.audio_versions = [
        AudioVersion(id="v1", path="speech.wav", duration_seconds=1, fingerprint=segment_fingerprint(book, segment))
    ]
    segment.selected_audio_version = "v1"
    segment.status = "succeeded"
    (tmp_path / "speech.wav").write_bytes(b"audio")
    (tmp_path / "chapter.wav").write_bytes(b"export")
    assert book_status(book, tmp_path)["ready_to_export"]
    assert not book_status(book, tmp_path)["complete"]
    (tmp_path / "book").mkdir()
    atomic_write_json(
        tmp_path / "book/export.json",
        {
            "fingerprint": book_fingerprint(book),
            "files": ["chapter.wav"],
            "illustrated": False,
            "resource_digests": {name: sha256_file(tmp_path / name) for name in ("chapter.wav", "speech.wav")},
        },
    )
    assert book_status(book, tmp_path)["complete"]
    assert book_status(book, tmp_path)["speech_quality"] == "not_assessed"
    segment.pause_after_seconds = 1
    assert not book_status(book, tmp_path)["complete"]


@pytest.mark.parametrize("path", ["../secret", "/tmp/secret", "book/../secret", "book\\secret"])
def test_media_paths_cannot_escape_project(path: str) -> None:
    with pytest.raises(ValidationError):
        Keyframe(id="frame", segment_id="segment", path=path)


def test_text_edit_preserves_ids_other_audio_and_original_history(tmp_path: Path) -> None:
    from lib.book.domain import replace_segment_text

    projects = ProjectManager(tmp_path)
    (projects.projects_dir / "book").mkdir(parents=True)
    store = BookStore(projects, "book")
    book = import_book("他说你好。她说再见。", max_segment_chars=5)
    for segment in all_segments(book):
        segment.audio_versions = [
            AudioVersion(
                id="v1", path=f"{segment.id}.wav", duration_seconds=1, fingerprint=segment_fingerprint(book, segment)
            )
        ]
        segment.selected_audio_version = "v1"
        segment.status = "succeeded"
    book = store.save(book)
    first, second = all_segments(book)
    revised = replace_segment_text(book, first.id, "他说早上好。")
    store.save(revised)
    changed, unchanged = all_segments(store.load())
    assert changed.id == first.id
    assert unchanged.id == second.id
    assert selected_audio(revised, changed) is None
    assert selected_audio(revised, unchanged) is not None
    assert unchanged.source_start == 6
    assert [path.read_text() for path in (store.path.parent / "source_history").glob("*.txt")] == [book.original_text]


def test_long_source_edit_updates_offsets_without_transient_invalid_ranges() -> None:
    from lib.book.domain import replace_segment_text

    book = import_book("你好。再见。", max_segment_chars=3)
    first, second = all_segments(book)
    updated = replace_segment_text(book, first.id, "这是比原句长得多的一段话。")
    validate_coverage(updated)
    assert all_segments(updated)[1].id == second.id
    assert all_segments(updated)[1].source_start == len("这是比原句长得多的一段话。")


def test_quote_import_keeps_attribution_separate_without_guessing_speaker() -> None:
    book = import_book("小明说：“你是谁？”小红说：“是我。”")
    assert [segment.text for segment in all_segments(book)] == ["小明说：", "“你是谁？”", "小红说：", "“是我。”"]
    assert all(segment.speaker_id == "narrator" and not segment.speaker_confirmed for segment in all_segments(book))


def test_book_store_rejects_symlink_parent(tmp_path: Path) -> None:
    projects = ProjectManager(tmp_path)
    project_dir = projects.projects_dir / "book"
    project_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_dir / "book").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        BookStore(projects, "book")
    assert list(outside.iterdir()) == []


def test_status_rejects_changed_speech_bytes(tmp_path: Path) -> None:
    book = import_book("你好。")
    segment = all_segments(book)[0]
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"original speech")
    segment.audio_versions = [
        AudioVersion(
            id="v1",
            path="speech.wav",
            duration_seconds=1,
            fingerprint=segment_fingerprint(book, segment),
            content_digest=sha256_file(audio),
        )
    ]
    segment.selected_audio_version = "v1"
    segment.status = "succeeded"
    assert book_status(book, tmp_path)["ready_to_export"]
    audio.write_bytes(b"replaced speech")
    assert book_status(book, tmp_path)["missing_audio"] == [segment.id]
