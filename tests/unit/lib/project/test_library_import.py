"""Synthetic library bundles exercise the existing project asset transaction boundary."""

import copy
import hashlib
import io
import json
import wave

import pytest
from PIL import Image
from pydantic import ValidationError

from lib.artifacts.generation_input import project_input_observation, storyboard_image_input
from lib.infra.api_errors import ConflictError, UnprocessableError
from lib.project.data_validator import DataValidator
from lib.project.library_import import apply_import, preview_import
from lib.project.library_manifest import LibraryManifest
from lib.project.project_manager import ProjectManager


def _image(color="red"):
    result = io.BytesIO()
    Image.new("RGB", (8, 12), color).save(result, format="PNG")
    return result.getvalue()


def _audio(sample=b"\0\0"):
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(sample * 800)
    return result.getvalue()


def _file(content, name="front.png", **overrides):
    return {"file": name, "sha256": hashlib.sha256(content).hexdigest(), **overrides}


def _entry(content, **overrides):
    return {
        "asset_type": "character",
        "external_id": "person-demo",
        "name": "Example character",
        "baseline": "baseline-001",
        "look": "look-001",
        "action": "action-000",
        "archive_version": "v001",
        "status": "pending",
        "views": [_file(content, role="identity", view="front", framing="headshot", confirmed=True)],
        **overrides,
    }


def _manifest(*entries):
    return LibraryManifest.model_validate(
        {"schema_version": 1, "library_id": "synthetic-library", "entries": list(entries)}
    )


def _project(tmp_path, characters=None):
    manager = ProjectManager(tmp_path)
    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    (directory / "project.json").write_text(json.dumps({"characters": characters or {}, "scenes": {}, "metadata": {}}))
    return manager, directory


def _apply(manager, manifest, uploads):
    preview = preview_import(manager, "demo", manifest, uploads)
    return apply_import(manager, "demo", manifest, uploads, preview["preview_token"])


class TestLibraryImport:
    def test_preview_is_read_only_then_apply_is_idempotent(self, tmp_path):
        manager, directory = _project(tmp_path)
        image = _image()
        manifest = _manifest(_entry(image))
        before = (directory / "project.json").read_bytes()
        preview = preview_import(manager, "demo", manifest, {"front.png": image})
        assert preview["summary"]["added"] == 1
        assert preview["can_apply"] is True
        assert (directory / "project.json").read_bytes() == before
        assert list(directory.iterdir()) == [directory / "project.json"]
        result = apply_import(manager, "demo", manifest, {"front.png": image}, preview["preview_token"])
        assert result["applied"] is True
        character = manager.load_project("demo")["characters"]["Example character"]
        assert character["external_library"]["status"] == "pending"
        assert character["reference_views"][0]["confirmed"] is True
        assert (directory / character["reference_views"][0]["path"]).read_bytes() == image
        assert "character_sheet" not in character
        assert preview_import(manager, "demo", manifest, {"front.png": image})["summary"]["unchanged"] == 1

    @pytest.mark.parametrize("confirmed", [True, False])
    def test_applied_original_assets_reach_storyboard_inputs_without_generated_sheets(self, tmp_path, confirmed):
        manager, directory = _project(tmp_path)
        character = _entry(_image())
        character["views"][0]["confirmed"] = confirmed
        scene_image = _image("green")
        scene = _entry(
            scene_image,
            asset_type="scene",
            external_id="scene-demo",
            name="Example room",
            baseline=None,
            look=None,
            action=None,
            state="state-001",
            views=[_file(scene_image, "room.png", role="space", view="front", framing="wide", confirmed=True)],
        )
        _apply(manager, _manifest(character, scene), {"front.png": _image(), "room.png": scene_image})
        project = manager.load_project("demo")
        assert DataValidator().validate_asset_definitions(project).valid
        script = {
            "episode": 1,
            "content_mode": "ad",
            "shots": [
                {
                    "shot_id": "E1S01",
                    "image_prompt": "@[Example character] in @[Example room]",
                    "characters_in_shot": ["Example character"],
                    "scenes": ["Example room"],
                    "props": [],
                    "products_in_shot": [],
                }
            ],
        }
        assembled = storyboard_image_input(
            project,
            script,
            episode=1,
            resource_id="E1S01",
            observation=project_input_observation(directory),
        )
        if not confirmed:
            assert "reference_views_unconfirmed" in {gap.code for gap in assembled.gaps}
            assert assembled.refusal is not None
            return
        assert not assembled.gaps
        assert [reference.visual.logical_type for reference in assembled.references] == ["character", "scene"]
        with assembled.freeze(
            max_reference_images=4, model="configured-workflow", bind_claims=lambda claims, digests: ()
        ) as frozen:
            assert len(frozen.references.visual_references) == 2
            assert "Example character" in frozen.prompt
            assert "Example room" in frozen.prompt
            assert all(reference.path.is_file() for reference in frozen.references.visual_references)

    def test_shared_media_is_deduplicated_without_merging_external_identities(self, tmp_path):
        manager, directory = _project(tmp_path)
        image = _image()
        scene = _entry(
            image,
            name="Example room",
            asset_type="scene",
            external_id="scene-demo",
            baseline=None,
            look=None,
            action=None,
            state="state-001",
        )
        scene["views"][0]["role"] = "space"
        manifest = _manifest(_entry(image), scene)
        preview = _apply(manager, manifest, {"front.png": image})
        assert preview["summary"]["deduplicated_files"] == 1
        project = manager.load_project("demo")
        character = project["characters"]["Example character"]
        scene = project["scenes"]["Example room"]
        assert character["reference_views"][0]["path"] == scene["reference_views"][0]["path"]
        assert scene["external_library"]["external_id"] == "scene-demo"
        assert len(list(directory.rglob("*.png"))) == 1

    def test_stale_preview_does_not_write_files_or_metadata(self, tmp_path):
        manager, directory = _project(tmp_path)
        image = _image()
        manifest = _manifest(_entry(image))
        preview = preview_import(manager, "demo", manifest, {"front.png": image})
        manager.update_project("demo", lambda project: project["characters"].update({"Other": {"description": "keep"}}))
        before = (directory / "project.json").read_bytes()
        with pytest.raises(ConflictError, match="asset_library_import_stale"):
            apply_import(manager, "demo", manifest, {"front.png": image}, preview["preview_token"])
        assert (directory / "project.json").read_bytes() == before
        assert not list(directory.rglob("*.png"))

    def test_frozen_same_version_conflicts_but_explicit_version_change_preserves_history(self, tmp_path):
        manager, directory = _project(tmp_path)
        original = _image()
        first = _entry(original, frozen=True)
        first["views"][0]["frozen"] = True
        _apply(manager, _manifest(first), {"front.png": original})
        changed = _entry(_image("blue"), frozen=True)
        same_version = preview_import(manager, "demo", _manifest(changed), {"front.png": _image("blue")})
        assert same_version["can_apply"] is False
        assert "frozen_view_conflict" in same_version["entries"][0]["conflicts"]
        changed["archive_version"] = "v002"
        changed["product_version"] = "V1"
        _apply(manager, _manifest(changed), {"front.png": _image("blue")})
        entry = manager.load_project("demo")["characters"]["Example character"]
        historical = entry["external_library_history"][0]
        assert historical["external_library"]["archive_version"] == "v001"
        assert historical["reference_views"][0]["frozen"] is True
        assert (directory / historical["reference_views"][0]["path"]).read_bytes() == original
        assert entry["external_library"]["archive_version"] == "v002"
        assert len(list(directory.rglob("*.png"))) == 2

    def test_selecting_old_version_cannot_bypass_its_frozen_history(self, tmp_path):
        manager, _ = _project(tmp_path)
        original = _entry(_image(), frozen=True)
        original["views"][0]["frozen"] = True
        _apply(manager, _manifest(original), {"front.png": _image()})
        _apply(manager, _manifest(_entry(_image("blue"), archive_version="v002")), {"front.png": _image("blue")})
        corrupted = _entry(_image("green"), frozen=True)
        preview = preview_import(manager, "demo", _manifest(corrupted), {"front.png": _image("green")})
        assert preview["can_apply"] is False
        assert "frozen_view_conflict" in preview["entries"][0]["conflicts"]
        restored = preview_import(manager, "demo", _manifest(original), {"front.png": _image()})
        assert restored["can_apply"] is True
        assert restored["entries"][0]["previous_archive_version"] == "v002"
        assert restored["entries"][0]["archive_version"] == "v001"
        assert restored["entries"][0]["view_changes"][0]["operation"] == "update"

    def test_oversized_decoded_image_is_a_validation_error(self, tmp_path, monkeypatch):
        manager, _ = _project(tmp_path)
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 32)
        image = _image()
        with pytest.raises(UnprocessableError, match="asset_library_import_invalid"):
            preview_import(manager, "demo", _manifest(_entry(image)), {"front.png": image})

    def test_missing_source_views_and_entries_are_retained(self, tmp_path):
        manager, _ = _project(tmp_path, {"Unrelated": {"description": "keep"}})
        image = _image()
        entry = _entry(image)
        entry["views"].append(_file(image, role="identity", view="left", framing="headshot", confirmed=True))
        _apply(manager, _manifest(entry), {"front.png": image})
        preview = _apply(manager, _manifest(_entry(image, archive_version="v002")), {"front.png": image})
        assert "source_views_retained" in preview["entries"][0]["warnings"]
        project = manager.load_project("demo")
        assert len(project["characters"]["Example character"]["reference_views"]) == 2
        assert project["characters"]["Unrelated"] == {"description": "keep"}

    @pytest.mark.parametrize(
        "change", [{"baseline": "baseline-002"}, {"look": "look-002"}, {"external_id": "different"}]
    )
    def test_variants_never_overwrite_a_different_identity(self, tmp_path, change):
        manager, _ = _project(tmp_path)
        image = _image()
        _apply(manager, _manifest(_entry(image)), {"front.png": image})
        preview = preview_import(manager, "demo", _manifest(_entry(image, **change)), {"front.png": image})
        assert preview["can_apply"] is False
        assert "identity_conflict" in preview["entries"][0]["conflicts"]

    def test_existing_generated_sheet_is_preserved(self, tmp_path):
        manager, _ = _project(
            tmp_path, {"Example character": {"description": "old", "character_sheet": "characters/generated.png"}}
        )
        image = _image()
        _apply(manager, _manifest(_entry(image)), {"front.png": image})
        assert (
            manager.load_project("demo")["characters"]["Example character"]["character_sheet"]
            == "characters/generated.png"
        )

    @pytest.mark.parametrize("mutation", ["digest", "missing", "extra", "damaged", "dimensions"])
    def test_invalid_content_is_rejected_without_writes(self, tmp_path, mutation):
        manager, directory = _project(tmp_path)
        image = _image()
        entry = _entry(image)
        uploads = {"front.png": image}
        if mutation == "digest":
            entry["views"][0]["sha256"] = "0" * 64
        elif mutation == "missing":
            uploads.clear()
        elif mutation == "extra":
            uploads["unrelated.png"] = image
        elif mutation == "damaged":
            uploads["front.png"] = b"not a png"
            entry["views"][0]["sha256"] = hashlib.sha256(uploads["front.png"]).hexdigest()
        else:
            entry["views"][0]["width"] = 999
        with pytest.raises(UnprocessableError):
            preview_import(manager, "demo", _manifest(entry), uploads)
        assert list(directory.iterdir()) == [directory / "project.json"]

    def test_symlink_destination_rejected_without_outside_write(self, tmp_path):
        manager, directory = _project(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (directory / "characters").symlink_to(outside, target_is_directory=True)
        image = _image()
        with pytest.raises((UnprocessableError, ValueError)):
            _apply(manager, _manifest(_entry(image)), {"front.png": image})
        assert not list(outside.iterdir())
        assert manager.load_project("demo")["characters"] == {}

    def test_json_commit_failure_rolls_back_installed_media(self, tmp_path, monkeypatch):
        manager, directory = _project(tmp_path)
        image = _image()
        before = (directory / "project.json").read_bytes()

        def fail_write(path, data):
            raise OSError("synthetic full disk")

        monkeypatch.setattr("lib.project.project_manager.atomic_write_json", fail_write)
        with pytest.raises(OSError, match="synthetic full disk"):
            _apply(manager, _manifest(_entry(image)), {"front.png": image})
        assert (directory / "project.json").read_bytes() == before
        assert not list(directory.rglob("*.png"))
        assert not list(directory.rglob("*.tmp"))


class TestLibraryVoiceImport:
    def _voice_entry(self, audio, **overrides):
        voice = {
            "voice_id": "voice-001",
            "version": "v001",
            "baseline": "baseline-001",
            "baseline_status": "pending",
            "status": "approved",
            "technical_pass": True,
            "agent_listened": True,
            "model_adapted": True,
            "clone_tested": True,
            "clips": [
                _file(
                    audio,
                    "clip.wav",
                    transcript="Exact words.",
                    confirmed=True,
                    archive_path="voices/voice-001/v001/audio/clip.wav",
                )
            ],
            "selected_clip": "clip.wav",
            **overrides,
        }
        return _entry(_image(), voice=voice)

    def test_technical_checks_do_not_confirm_pending_baseline(self, tmp_path):
        manager, _ = _project(tmp_path)
        audio = _audio()
        preview = _apply(manager, _manifest(self._voice_entry(audio)), {"front.png": _image(), "clip.wav": audio})
        entry = manager.load_project("demo")["characters"]["Example character"]
        assert not entry.get("reference_audio")
        assert entry["external_voice"]["technical_pass"] is True
        assert entry["external_voice"]["baseline_status"] == "pending"
        assert preview["summary"]["pending_voice_bindings"] == 1

    def test_confirmed_baseline_binds_exact_clip_and_transcript(self, tmp_path):
        manager, directory = _project(tmp_path)
        audio = _audio()
        _apply(
            manager,
            _manifest(self._voice_entry(audio, baseline_status="confirmed")),
            {"front.png": _image(), "clip.wav": audio},
        )
        entry = manager.load_project("demo")["characters"]["Example character"]
        assert (directory / entry["reference_audio"]).read_bytes() == audio
        assert entry["reference_audio_transcript"] == "Exact words."
        assert entry["voice_updated_at"]

    @pytest.mark.parametrize(
        "override", [{"baseline": None}, {"baseline": "baseline-002"}, {"status": "pending"}, {"selected_clip": None}]
    )
    def test_ambiguous_or_unapproved_voice_is_never_bound(self, tmp_path, override):
        manager, _ = _project(tmp_path)
        audio = _audio()
        entry = self._voice_entry(audio, baseline_status="confirmed", **override)
        _apply(manager, _manifest(entry), {"front.png": _image(), "clip.wav": audio})
        assert not manager.load_project("demo")["characters"]["Example character"].get("reference_audio")

    def test_withdrawn_confirmation_clears_imported_active_voice(self, tmp_path):
        manager, _ = _project(tmp_path)
        audio = _audio()
        uploads = {"front.png": _image(), "clip.wav": audio}
        _apply(manager, _manifest(self._voice_entry(audio, baseline_status="confirmed")), uploads)
        _apply(manager, _manifest(self._voice_entry(audio)), uploads)
        entry = manager.load_project("demo")["characters"]["Example character"]
        assert entry["reference_audio"] == ""
        assert entry["reference_audio_transcript"] == ""

    def test_pending_voice_preserves_unrelated_manual_binding_and_warns(self, tmp_path):
        manager, _ = _project(tmp_path, {"Example character": {"reference_audio": "characters/refs_audio/manual.wav"}})
        audio = _audio()
        preview = _apply(manager, _manifest(self._voice_entry(audio)), {"front.png": _image(), "clip.wav": audio})
        assert "existing_voice_binding_retained" in preview["entries"][0]["warnings"]
        assert manager.load_project("demo")["characters"]["Example character"]["reference_audio"].endswith("manual.wav")

    def test_frozen_voice_key_uses_archive_path_not_upload_filename(self, tmp_path):
        manager, _ = _project(tmp_path)
        audio = _audio()
        first = self._voice_entry(audio, baseline_status="confirmed")
        first["voice"]["clips"][0]["frozen"] = True
        _apply(manager, _manifest(first), {"front.png": _image(), "clip.wav": audio})
        updated_audio = _audio(b"\1\0")
        updated = self._voice_entry(updated_audio, baseline_status="confirmed", selected_clip="different.wav")
        updated["voice"]["clips"][0]["file"] = "different.wav"
        preview = preview_import(
            manager, "demo", _manifest(updated), {"front.png": _image(), "different.wav": updated_audio}
        )
        assert "frozen_voice_conflict" in preview["entries"][0]["conflicts"]
        updated["voice"]["version"] = "v002"
        _apply(manager, _manifest(updated), {"front.png": _image(), "different.wav": updated_audio})
        entry = manager.load_project("demo")["characters"]["Example character"]
        assert entry["external_voice_history"][0]["version"] == "v001"
        assert entry["external_voice"]["version"] == "v002"

    def test_independent_voice_only_sets_keep_independent_identities(self, tmp_path):
        manager, _ = _project(tmp_path)
        audio = _audio()
        first = self._voice_entry(audio)
        first["views"] = []
        second = copy.deepcopy(first)
        second["name"] = "Second voice set"
        second["voice"]["voice_id"] = "voice-002"
        _apply(manager, _manifest(first, second), {"clip.wav": audio})
        entries = manager.load_project("demo")["characters"]
        assert entries["Example character"]["external_library"]["voice_id"] == "voice-001"
        assert entries["Second voice set"]["external_library"]["voice_id"] == "voice-002"


class TestLibraryManifest:
    @pytest.mark.parametrize("path", ["../secret", "/absolute/file", "a/../file", "C:\\file", "a\\b", "./file"])
    def test_source_paths_are_relative_metadata_only(self, path):
        entry = _entry(_image())
        entry["views"][0]["archive_path"] = path
        with pytest.raises(ValidationError):
            _manifest(entry)

    def test_arbitrary_server_root_is_not_part_of_contract(self):
        with pytest.raises(ValidationError):
            LibraryManifest.model_validate(
                {"schema_version": 1, "library_id": "synthetic", "server_root": "/etc", "entries": [_entry(_image())]}
            )
