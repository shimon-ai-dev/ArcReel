"""The original chapter and storyboard remain the book production source of truth."""

import json

import pytest

from lib.book.domain import all_segments, import_book, validate_coverage
from lib.book.episode_bridge import build_episode_book, stale_episodes
from lib.book.store import BookStore
from lib.infra.json_io import atomic_write_json
from lib.project.project_manager import ProjectManager
from server.services.book.service import edit_segment, save_document, sync_episode


def original_project(tmp_path):
    manager = ProjectManager(tmp_path)
    manager.create_project("novel")
    manager.create_project_metadata("novel", "Rain", extras={"output_mode": "illustrated_audiobook"})
    directory = manager.get_project_path("novel")
    project = manager.load_project("novel")
    project["episodes"] = [{"episode": 1, "title": "Rain", "source_origin": "own", "script_file": "episode_1.json"}]
    project["characters"] = {"Alice": {"description": "A woman", "reference_audio": "characters/alice.wav"}}
    atomic_write_json(directory / "project.json", project)
    (directory / "characters").mkdir(exist_ok=True)
    (directory / "characters/alice.wav").write_bytes(b"fixture voice")
    (directory / "source").mkdir(exist_ok=True)
    (directory / "source/episode_1.txt").write_text("第一章\n她说：你好。\n雨落下。", encoding="utf-8")
    script = {
        "episode": 1,
        "title": "Rain",
        "content_mode": "narration",
        "segments": [
            {
                "segment_id": "E1S01",
                "novel_text": "她说：你好。",
                "duration_seconds": 4,
                "book_speech": [
                    {
                        "source_start": 3,
                        "source_end": 6,
                        "text": "你好。",
                        "speaker_id": "Alice",
                        "performance": {"emotion": "温柔"},
                    }
                ],
                "generated_assets": {"storyboard_image": "storyboards/E1S01.png"},
            },
            {
                "segment_id": "E1S02",
                "novel_text": "雨落下。",
                "duration_seconds": 4,
                "book_sound_cues": [
                    {
                        "cue_id": "rain",
                        "description": "窗外雨声",
                        "track": "ambience",
                        "source_start": 0,
                        "source_end": 4,
                    }
                ],
                "generated_assets": {"storyboard_image": "storyboards/E1S02.png"},
            },
        ],
    }
    atomic_write_json(directory / "scripts/episode_1.json", script)
    return manager, directory, script


def test_original_source_storyboards_speakers_and_sound_intentions(tmp_path):
    manager, directory, _ = original_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    validate_coverage(book)
    assert "".join(s.text for s in all_segments(book)) == (directory / "source/episode_1.txt").read_text()
    assert book.chapters[0].episode == 1
    assert [f.path for f in book.keyframes] == ["storyboards/E1S01.png", "storyboards/E1S02.png"]
    spoken = next(s for s in all_segments(book) if s.speaker_id == "Alice")
    assert spoken.text == "你好。\n"
    assert all(segment.text.strip() for segment in all_segments(book))
    assert spoken.performance.emotion == "温柔"
    assert book.voices["Alice"].adapter == "voxcpm2"
    assert book.voices["Alice"].reference_audio == "characters/alice.wav"
    assert book.sound_cues[0].description == "窗外雨声"
    assert not book.effects  # A sound intention is not an invented audio artifact.
    assert stale_episodes(manager, "novel", book) == []


def test_sync_preserves_legacy_full_document_and_rejects_parallel_source_edits(tmp_path):
    manager, directory, _ = original_project(tmp_path)
    store = BookStore(manager, "novel")
    old = store.save(import_book("旧版不可丢失。"))
    synced = sync_episode("novel", 1, projects=manager)
    assert synced.legacy_archive
    archive = json.loads((directory / synced.legacy_archive).read_text())
    assert archive["original_text"] == old.original_text
    with pytest.raises(ValueError, match="original chapter"):
        edit_segment("novel", synced.chapters[0].segments[0].id, "修改", projects=manager)
    tampered = synced.model_copy(deep=True)
    tampered.keyframes[0].path = "book/assets/new.png"
    with pytest.raises(ValueError, match="storyboard images"):
        save_document("novel", tampered, projects=manager)


def test_resync_preserves_manual_performance_but_new_original_annotations_replace_it(tmp_path):
    manager, directory, script = original_project(tmp_path)
    book = sync_episode("novel", 1, projects=manager)
    speech = next(s for s in all_segments(book) if s.speaker_id == "Alice")
    speech.performance.style = "放轻声音"
    save_document("novel", book, projects=manager)
    same = sync_episode("novel", 1, projects=manager)
    assert next(s for s in all_segments(same) if s.speaker_id == "Alice").performance.style == "放轻声音"
    script["segments"][0]["book_speech"][0]["performance"]["emotion"] = "悲伤"
    atomic_write_json(directory / "scripts/episode_1.json", script)
    assert stale_episodes(manager, "novel", same) == [1]
    changed = sync_episode("novel", 1, projects=manager)
    assert next(s for s in all_segments(changed) if s.speaker_id == "Alice").performance.emotion == "悲伤"


def test_changed_original_source_or_missing_script_fails_loud(tmp_path):
    manager, directory, script = original_project(tmp_path)
    script["segments"][0]["novel_text"] = "改写摘要"
    atomic_write_json(directory / "scripts/episode_1.json", script)
    with pytest.raises(ValueError, match="absent"):
        build_episode_book(manager, "novel", 1, None)


@pytest.mark.parametrize("span", [(-1, 2), (0, 100), (True, 2), (3, 2)])
def test_scene_sound_cues_reject_invalid_original_spans(tmp_path, span):
    manager, directory, script = original_project(tmp_path)
    cue = script["segments"][1]["book_sound_cues"][0]
    cue["source_start"], cue["source_end"] = span
    atomic_write_json(directory / "scripts/episode_1.json", script)
    with pytest.raises(ValueError, match="offsets"):
        build_episode_book(manager, "novel", 1, None)


def test_scene_sound_intention_cannot_silently_disappear_from_export(tmp_path):
    from lib.book.status import book_status
    from lib.book_audio.export import build_book_package

    manager, directory, _ = original_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    assert book.sound_cues[0].id in book_status(book, directory)["missing_effects"]
    with pytest.raises(ValueError, match="Scene sound cues need audio"):
        build_book_package(book, directory, directory / "book/export")
