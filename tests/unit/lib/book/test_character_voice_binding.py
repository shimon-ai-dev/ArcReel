"""Original character audio remains authoritative for explicitly bound book voices."""

import json

import pytest

from lib.book.domain import all_segments, segment_fingerprint
from lib.book.episode_bridge import build_episode_book, character_reference, stale_episodes
from lib.infra.json_io import atomic_write_json
from lib.project.project_manager import ProjectManager


def fixture_project(tmp_path):
    manager = ProjectManager(tmp_path)
    manager.create_project("novel")
    manager.create_project_metadata("novel", "Novel", extras={"output_mode": "audiobook"})
    root = manager.get_project_path("novel")
    project = manager.load_project("novel")
    project["characters"] = {"Alice": {"reference_audio": "characters/alice.wav"}}
    project["episodes"] = [{"episode": 1, "source_origin": "own", "script_file": "episode_1.json"}]
    atomic_write_json(root / "project.json", project)
    (root / "characters").mkdir(exist_ok=True)
    (root / "characters/alice.wav").write_bytes(b"reference-v1")
    (root / "source").mkdir(exist_ok=True)
    (root / "source/episode_1.txt").write_text("你好。", encoding="utf-8")
    atomic_write_json(
        root / "scripts/episode_1.json",
        {
            "episode": 1,
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "E1S01",
                    "novel_text": "你好。",
                    "duration_seconds": 4,
                    "book_speech": [{"source_start": 0, "source_end": 3, "text": "你好。", "speaker_id": "Alice"}],
                }
            ],
        },
    )
    return manager, root


def test_bound_reference_replacement_invalidates_current_inputs(tmp_path):
    manager, root = fixture_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    voice = book.voices["Alice"]
    assert voice.source_character == "Alice"
    fingerprint = segment_fingerprint(book, all_segments(book)[0])
    voice.settings = {"seed": 7}
    (root / "characters/alice.wav").write_bytes(b"reference-v2")
    assert stale_episodes(manager, "novel", book) == [1]
    updated = build_episode_book(manager, "novel", 1, book)
    assert updated.voices["Alice"].reference_audio_digest != voice.reference_audio_digest
    assert updated.voices["Alice"].settings == {"seed": 7}
    assert segment_fingerprint(updated, all_segments(updated)[0]) != fingerprint
    assert stale_episodes(manager, "novel", updated) == []
    assert book.voices["Alice"].reference_audio_digest == voice.reference_audio_digest


def test_manual_reference_is_not_overwritten_by_original_character(tmp_path):
    manager, _ = fixture_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    book.voices["Alice"].source_character = None
    book.voices["Alice"].reference_audio = "manual/voice.wav"
    updated = build_episode_book(manager, "novel", 1, book)
    assert updated.voices["Alice"].reference_audio == "manual/voice.wav"
    assert updated.voices["Alice"].source_character is None


def test_bound_missing_and_symlink_reference_fail_closed(tmp_path):
    manager, root = fixture_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    (root / "characters/alice.wav").unlink()
    assert stale_episodes(manager, "novel", book) == [1]
    with pytest.raises((ValueError, OSError)):
        build_episode_book(manager, "novel", 1, book)
    (root / "characters/alice.wav").symlink_to(root / "source/episode_1.txt")
    with pytest.raises(ValueError, match="symbolic"):
        character_reference(manager, "novel", "Alice")


def test_same_path_storyboard_replacement_and_removal_are_stale(tmp_path):
    manager, root = fixture_project(tmp_path)
    script_path = root / "scripts/episode_1.json"
    script = json.loads(script_path.read_text())
    script["segments"][0]["generated_assets"] = {"storyboard_image": "storyboards/first.png"}
    atomic_write_json(script_path, script)
    # An unfinished original image does not prevent preparing speech.
    book = build_episode_book(manager, "novel", 1, None)
    assert stale_episodes(manager, "novel", book) == []
    (root / "storyboards").mkdir(exist_ok=True)
    image = root / "storyboards/first.png"
    image.write_bytes(b"first image")
    assert stale_episodes(manager, "novel", book) == [1]
    book = build_episode_book(manager, "novel", 1, book)
    image.write_bytes(b"replacement image")
    assert stale_episodes(manager, "novel", book) == [1]
    book = build_episode_book(manager, "novel", 1, book)
    image.unlink()
    assert stale_episodes(manager, "novel", book) == [1]


def test_imported_transcript_is_bound_and_replacement_invalidates_book(tmp_path):
    manager, root = fixture_project(tmp_path)
    project = manager.load_project("novel")
    project["characters"]["Alice"]["reference_audio_transcript"] = "Exact reference words."
    atomic_write_json(root / "project.json", project)
    book = build_episode_book(manager, "novel", 1, None)
    assert book.voices["Alice"].reference_text == "Exact reference words."
    project["characters"]["Alice"]["reference_audio_transcript"] = "Corrected reference words."
    atomic_write_json(root / "project.json", project)
    assert stale_episodes(manager, "novel", book) == [1]
    updated = build_episode_book(manager, "novel", 1, book)
    assert updated.voices["Alice"].reference_text == "Corrected reference words."
    assert stale_episodes(manager, "novel", updated) == []


def test_legacy_character_without_imported_transcript_keeps_manual_reference_text(tmp_path):
    manager, _ = fixture_project(tmp_path)
    book = build_episode_book(manager, "novel", 1, None)
    book.voices["Alice"].reference_text = "Manually transcribed reference."
    updated = build_episode_book(manager, "novel", 1, book)
    assert updated.voices["Alice"].reference_text == "Manually transcribed reference."
    assert stale_episodes(manager, "novel", updated) == []
