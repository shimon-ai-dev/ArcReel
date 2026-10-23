"""Synthetic existing-library layouts exercise parsing and conservative selection."""

import hashlib
import json
import wave
from pathlib import Path

import pytest
from PIL import Image

from lib.library_bundle.converter import prepare_library
from lib.library_bundle.safe_io import LibraryReadError
from lib.project.library_import import verify_contents
from lib.project.library_manifest import LibraryManifest
from scripts.book.prepare_library_bundle import main


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _image(root: Path, *, version: str = "v001", product_version: str = "V1", color: str = "red") -> dict:
    base = f"characters/person-9001/packs/baseline-001_look-001_action-000/{version}"
    filename = "character-assets/identity/identity-01-front-neutral.png"
    archive = root / base / filename
    archive.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 48), color).save(archive)
    product = f"成品/人物/person-9001/基础视图/大头照正面_{product_version}.png"
    (root / product).parent.mkdir(parents=True, exist_ok=True)
    (root / product).symlink_to(archive)
    approval = {
        "status": "approved",
        "asset_id": "person-9001",
        "baseline": "baseline-001",
        "look": "look-001",
        "action": "action-000",
        "archive_version": version,
        "product_version": product_version,
        "coverage": {"required": 1, "confirmed": 1, "pending": 0, "missing": 0},
        "frozen": True,
        "files": [
            {
                "slot": "大头照正面",
                "archive": filename,
                "source_candidate": "work/run-002/private.env",
                "product": product,
                "product_filename": Path(product).name,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "width": 32,
                "height": 48,
                "frozen": True,
                "user_confirmed": True,
            }
        ],
    }
    _write(root / base / "approval.json", json.dumps(approval))
    return {
        "base": base,
        "source": f"{base}/{filename}",
        "product": product,
        "approval": approval,
        "row": f"| 基础视图 | [大头照](基础视图/大头照正面_{product_version}.png) | {product_version} | person-9001 / baseline-001 / look-001 / action-000 / {version} / {filename} | 七张整体确认；已冻结 |",
    }


def _person_index(root: Path, rows: list[str], *, recommendation: str = "") -> None:
    _write(
        root / "成品/人物/person-9001/索引.md",
        "\n".join(
            [
                "# person-9001",
                recommendation,
                "| 分类 | 文件 | 成品V | 精确来源版本 | 确认范围 |",
                "| --- | --- | --- | --- | --- |",
                *rows,
            ]
        ),
    )


def _voice(root: Path, *, voice_id: str = "voice-001") -> str:
    base = f"characters/person-9001/voices/{voice_id}/v003"
    audio = root / base / "voice-assets/audio/clip-001.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\0\0" * 2400)
    transcript = root / base / "voice-assets/transcripts/clip-001.txt"
    _write(transcript, "Synthetic transcript only.")
    product = f"成品/人物/person-9001/声音资产/自然说话_{voice_id}_克隆主参考_V2.wav"
    (root / product).parent.mkdir(parents=True, exist_ok=True)
    (root / product).symlink_to(audio)
    approval = {
        "person": "person-9001",
        "voice": voice_id,
        "version": "v003",
        "product_version": "V2",
        "set_name": "自然说话",
        "status": "approved",
        "technical_pass": True,
        "agent_listened": False,
        "model_adapted": False,
        "clone_tested": False,
        "frozen": True,
        "published": True,
        "files": [
            {
                "role": "main_reference",
                "path": "voice-assets/audio/clip-001.wav",
                "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                "product": "/Users/synthetic/Documents/old-root/成品/人物/person-9001/声音资产/old.wav",
            },
            {
                "role": "transcript",
                "path": "voice-assets/transcripts/clip-001.txt",
                "sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
                "product": "/Users/synthetic/Documents/old-root/transcript.txt",
            },
        ],
    }
    _write(root / base / "approval.json", json.dumps(approval))
    _write(
        root / "characters/person-9001/character.md",
        "\n".join(
            [
                "| 声音设定 | 适用 baseline | 当前工作版本 | 最后已批准版本 | 当前推荐成品 |",
                "| --- | --- | --- | --- | --- |",
                f"| {voice_id} | 待定（图片baseline-001已建立，声音适用关系未另行裁定） | [v003](voices/{voice_id}/v003/pack.md) | [v003](voices/{voice_id}/v003/pack.md) | 自然说话 V2 |",
            ]
        ),
    )
    return f"| 声音资产 | [自然说话](声音资产/{Path(product).name}) | V2 | person-9001 / {voice_id} / v003 / audio/clip-001.wav | 技术通过；未试听 |"


def _scene(root: Path, *, map_only: bool = False, display: str = "scene-9001", source_id: str = "scene-9002") -> str:
    base = f"scenes/{source_id}/state-001-v002"
    archive = root / base / "scene-assets/views/scene-01-main.png"
    archive.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 32), "blue").save(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    _write(root / base / "pack.md", "包状态：`validated`；用户尚未批准整包。整包批准 0/1。")
    product = f"成品/场景/{display}/空间视图/合成场景_主空景_V1.png"
    (root / product).parent.mkdir(parents=True, exist_ok=True)
    (root / product).symlink_to(archive)
    if map_only:
        _write(
            root / base / "scene-assets/asset-map.md",
            "\n".join(
                [
                    f"# {source_id}/state-001-v002",
                    "## scene-01-main.png",
                    "- 文件/职责：[views/scene-01-main.png](views/scene-01-main.png)",
                    f"- 校验：64x32 PNG SHA-256 `{digest}`",
                    "- 确认/冻结：用户确认此原图视图；已冻结，不可本版本覆盖。",
                    f"- 已发布入口：[old.png](../../../../成品/场景/{display}/空间视图/old-does-not-exist.png)",
                ]
            ),
        )
        index = "\n".join(
            [
                "| 分类 | 文件 | 成品版本 | 确认范围 | 来源与记录 |",
                "| --- | --- | --- | --- | --- |",
                f"| 空间视图 | [合成场景](空间视图/{Path(product).name}) | V1 | 用户确认按照片原貌入库；单文件冻结；整包未单独批准 | [资产地图](../../../{base}/scene-assets/asset-map.md) |",
            ]
        )
    else:
        index = "\n".join(
            [
                "| 成品文件 | 精确来源包与文件 | SHA-256 |",
                "| --- | --- | --- |",
                f"| [合成场景](空间视图/{Path(product).name}) | [{source_id}/state-001-v002](../../../{base}/pack.md) · [views/scene-01-main.png](../../../{base}/scene-assets/views/scene-01-main.png) | `{digest}` |",
            ]
        )
    _write(root / f"成品/场景/{display}/索引.md", index)
    return product


def test_convert_existing_library_without_user_authored_manifest(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]], recommendation="当前推荐：**基础视图 V1（7/7齐套）**。")
    _write(root / ".env", "SYNTHETIC_SECRET=must-not-enter-bundle")
    _write(root / image["base"] / "work/run-002/private.env", "unrelated")
    before = (root / image["base"] / "approval.json").read_bytes()
    output = tmp_path / "bundle"

    preview = prepare_library(root, library_id="synthetic-library", output=output)

    assert preview.ready, preview.report()
    manifest = json.loads((output / "library-manifest.json").read_text())
    entry = manifest["entries"][0]
    assert (entry["external_id"], entry["archive_version"], entry["product_version"]) == ("person-9001", "v001", "V1")
    assert entry["views"][0]["view"] == "front"
    assert entry["views"][0]["framing"] == "headshot"
    assert entry["views"][0]["confirmed"] is True
    assert {path.name for path in output.iterdir()} == {
        "library-manifest.json",
        "preview.json",
        entry["views"][0]["file"],
    }
    assert "SYNTHETIC_SECRET" not in (output / "library-manifest.json").read_text()
    assert (root / image["product"]).is_symlink()
    assert (root / image["base"] / "approval.json").read_bytes() == before


def test_explicit_recommendation_selects_not_highest_version(tmp_path: Path):
    root = tmp_path / "source"
    first = _image(root)
    later = _image(root, version="v009", product_version="V3", color="green")
    _person_index(root, [later["row"], first["row"]], recommendation="当前推荐：**基础视图 V1（7/7齐套）**。")
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    assert preview.entries[0]["archive_version"] == "v001"
    assert len(preview.content) == 1
    assert any(issue.code == "not_current" for issue in preview.warnings)


def test_multiple_current_versions_block_without_guessing(tmp_path: Path):
    root = tmp_path / "source"
    first = _image(root)
    later = _image(root, version="v009", product_version="V3", color="green")
    _person_index(root, [later["row"], first["row"]])
    output = tmp_path / "bundle"
    preview = prepare_library(root, output=output)
    assert not preview.ready
    assert any("Multiple published versions" in issue.message for issue in preview.blockers)
    assert [path.name for path in output.iterdir()] == ["preview.json"]


def test_voice_approval_stays_independent_and_pending_baseline(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"], _voice(root)])
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    entry = next(entry for entry in preview.entries if entry.get("voice"))
    voice = entry["voice"]
    assert entry["views"] == []
    assert entry["baseline"] is None
    assert voice["baseline"] is None
    assert voice["baseline_status"] == "pending"
    assert voice["technical_pass"] is True
    assert voice["agent_listened"] is False
    assert voice["model_adapted"] is False
    assert voice["clone_tested"] is False
    assert voice["clips"][0]["transcript"] == "Synthetic transcript only."
    assert "Users/synthetic" not in json.dumps(preview.manifest())
    assert voice["clips"][0]["archive_path"].endswith("voice-assets/audio/clip-001.wav")


def test_multiple_voice_sets_do_not_overwrite_one_person(tmp_path: Path):
    root = tmp_path / "source"
    rows = [_voice(root, voice_id="voice-001"), _voice(root, voice_id="voice-002")]
    _person_index(root, rows)
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    assert {entry["voice"]["voice_id"] for entry in preview.entries} == {"voice-001", "voice-002"}
    assert len(preview.content) == 1


def test_scene_cross_entry_reference_preserves_source_identity_not_display_group(tmp_path: Path):
    root = tmp_path / "source"
    _scene(root)
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    entry = preview.entries[0]
    assert entry["external_id"] == "scene-9002"
    assert entry["state"] == "state-001"
    assert entry["archive_version"] == "v002"
    assert entry["status"] == "pending"
    assert entry["views"][0]["confirmed"] is False


def test_scene_map_uses_current_symlink_not_stale_product_link(tmp_path: Path):
    root = tmp_path / "source"
    product = _scene(root, map_only=True)
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    entry = preview.entries[0]
    assert entry["status"] == "pending"
    assert entry["frozen"] is False
    view = entry["views"][0]
    assert view["confirmed"] is True
    assert view["frozen"] is True
    assert view["product_path"] == product
    assert "old-does-not-exist" not in json.dumps(preview.manifest())


def test_bad_hash_writes_preview_only_and_leaves_original_untouched(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    (root / image["source"]).write_bytes(b"changed")
    output = tmp_path / "bundle"
    preview = prepare_library(root, output=output)
    assert not preview.ready
    assert any("SHA-256" in issue.message for issue in preview.blockers)
    assert [path.name for path in output.iterdir()] == ["preview.json"]
    assert (root / image["source"]).read_bytes() == b"changed"


def test_product_symlink_escape_is_a_clear_preview_blocker(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    product = root / image["product"]
    product.unlink()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    product.symlink_to(outside)
    preview = prepare_library(root)
    assert not preview.ready
    assert any("complete library" in issue.message for issue in preview.blockers)
    assert not preview.content


def test_unknown_registry_dialect_does_not_claim_success(tmp_path: Path):
    root = tmp_path / "source"
    _write(root / "成品/人物/person-9001/索引.md", "# Current version\nUse the latest modified image.")
    preview = prepare_library(root)
    assert not preview.ready
    assert any("Unsupported product index dialect" in issue.message for issue in preview.blockers)


def test_product_only_root_reports_required_boundary(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    preview = prepare_library(root / "成品")
    assert not preview.ready
    assert any(issue.code == "library_root" for issue in preview.blockers)


def test_cli_preview_is_read_only_and_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    assert main([str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert not (root / "library-manifest.json").exists()
    with pytest.raises(LibraryReadError, match="outside"):
        prepare_library(root, output=root / "new-output")


def test_generated_bundle_matches_real_importer_content_contract(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"], _voice(root)])
    _scene(root, map_only=True)
    output = tmp_path / "bundle"
    preview = prepare_library(root, output=output)
    assert preview.ready, preview.report()
    manifest = LibraryManifest.model_validate_json((output / "library-manifest.json").read_text())
    uploads = {path.name: path.read_bytes() for path in output.iterdir() if path.suffix != ".json"}
    verified = verify_contents(manifest, uploads)
    assert len(verified) == 3
    assert {item.suffix for item in verified.values()} == {".png", ".wav"}
    assert all(name.startswith(item.sha256) for name, item in verified.items())
    assert not any(name.endswith(".txt") for name in uploads)
    assert preview.entries[-1]["status"] == "pending"


def test_registry_last_approved_pointer_wins_over_working_version(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    registry = root / "characters/person-9001/character.md"
    _write(
        registry,
        "\n".join(
            [
                "| 包 | 当前工作版本 | 最后已批准版本 | 交付范围 |",
                "| --- | --- | --- | --- |",
                "| baseline-001_look-001_action-000 | [v009](packs/baseline-001_look-001_action-000/v009/pack.md) | [v001](packs/baseline-001_look-001_action-000/v001/pack.md) | 基础视图 |",
            ]
        ),
    )
    preview = prepare_library(root)
    assert preview.ready, preview.report()
    assert preview.entries[0]["archive_version"] == "v001"
    registry.write_text(
        registry.read_text().replace(
            "[v001](packs/baseline-001_look-001_action-000/v001/pack.md)",
            "[v002](packs/baseline-001_look-001_action-000/v002/pack.md)",
        )
    )
    blocked = prepare_library(root)
    assert not blocked.ready
    assert any("registry last-approved version" in issue.message for issue in blocked.blockers)


def test_explicit_entry_selection_skips_unrelated_unknown_index(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    _person_index(root, [image["row"]])
    _write(root / "成品/场景/scene-9999/索引.md", "Unknown scene registry dialect")
    preview = prepare_library(root, entries={"person-9001"})
    assert preview.ready, preview.report()
    assert len(preview.entries) == 1
    missing = prepare_library(root, entries={"person-9999"})
    assert not missing.ready
    assert any(issue.code == "missing_entry" for issue in missing.blockers)


def test_actual_image_dimensions_must_match_approval(tmp_path: Path):
    root = tmp_path / "source"
    image = _image(root)
    image["approval"]["files"][0]["width"] = 99
    _write(root / image["base"] / "approval.json", json.dumps(image["approval"]))
    _person_index(root, [image["row"]])
    preview = prepare_library(root)
    assert not preview.ready
    assert any("dimensions" in issue.message for issue in preview.blockers)
