"""Preview and atomically import uploaded library content into existing project assets.

The server reads no external library paths. Source paths remain provenance metadata;
only the explicitly uploaded and hash-verified content can become project references.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from lib.infra.api_errors import ConflictError, UnprocessableError
from lib.infra.path_safety import safe_join
from lib.project.asset_types import ASSET_SPECS, find_project_asset_name
from lib.project.library_manifest import LibraryManifest, ManifestEntry, ManifestView, UploadedFile
from lib.project.project_manager import ProjectManager

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 200
IDENTITY_FIELDS = ("library_id", "external_id", "baseline", "look", "action", "state", "voice_id")


@dataclass(frozen=True)
class VerifiedContent:
    data: bytes
    sha256: str
    suffix: str
    width: int | None = None
    height: int | None = None


def invalid_import(reason: str) -> UnprocessableError:
    return UnprocessableError("asset_library_import_invalid").with_diagnostic(reason)


def _all_files(manifest: LibraryManifest) -> list[tuple[UploadedFile, str]]:
    result: list[tuple[UploadedFile, str]] = []
    for entry in manifest.entries:
        result.extend((view, "image") for view in entry.views)
        if entry.voice:
            result.extend((clip, "audio") for clip in entry.voice.clips)
    return result


def verify_contents(manifest: LibraryManifest, uploads: dict[str, bytes]) -> dict[str, VerifiedContent]:
    """Check every declared content hash and supported media before preview or mutation."""
    declared = _all_files(manifest)
    expected = {item.file for item, _kind in declared}
    if set(uploads) != expected:
        raise invalid_import("Uploaded files must match the manifest exactly")
    if len(uploads) > MAX_FILES or sum(map(len, uploads.values())) > MAX_TOTAL_BYTES:
        raise invalid_import("The upload bundle exceeds the supported size")
    result: dict[str, VerifiedContent] = {}
    kinds: dict[str, str] = {}
    for item, kind in declared:
        data = uploads[item.file]
        if not data or len(data) > MAX_FILE_BYTES:
            raise invalid_import("Each content file must be nonempty and at most 20 MiB")
        actual = result[item.file].sha256 if item.file in result else hashlib.sha256(data).hexdigest()
        if actual != item.sha256:
            raise invalid_import(f"SHA-256 mismatch for {item.file}")
        if item.file in result:
            if kinds[item.file] != kind:
                raise invalid_import("One file cannot serve as both image and audio")
            continue
        try:
            if kind == "image":
                with Image.open(io.BytesIO(data)) as image:
                    suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format or "")
                    if suffix is None:
                        raise invalid_import("Images must be PNG, JPEG or WebP")
                    width, height = image.size
                    if width * height > 40_000_000:
                        raise invalid_import("Images must contain at most 40 million pixels")
                    image.load()
                result[item.file] = VerifiedContent(data, actual, suffix, width, height)
            else:
                with wave.open(io.BytesIO(data), "rb") as audio:
                    if audio.getnchannels() not in (1, 2) or audio.getnframes() <= 0:
                        raise invalid_import("Voice clips must contain mono or stereo PCM WAV audio")
                    if len(audio.readframes(audio.getnframes())) != (
                        audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                    ):
                        raise invalid_import("Voice clip audio is truncated")
                result[item.file] = VerifiedContent(data, actual, ".wav")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, wave.Error, EOFError) as exc:
            raise invalid_import(f"Unsupported or damaged {kind} content: {item.file}") from exc
        kinds[item.file] = kind
    return result


def _identity(entry: ManifestEntry, library_id: str) -> dict:
    return {
        "library_id": library_id,
        "voice_id": entry.voice.voice_id if not entry.views and entry.voice else None,
        **entry.model_dump(exclude={"asset_type", "name", "description", "views", "voice"}),
    }


def _same_identity(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key) for key in IDENTITY_FIELDS)


def _view_slot(view: dict) -> tuple:
    return tuple(view.get(key) for key in ("role", "view", "framing"))


def _content_path(content: VerifiedContent, kind: str) -> str:
    # Original media lives in existing public media subdirectories, not generated sheet locations.
    directory = "characters/refs/library" if kind == "image" else "characters/refs_audio/library"
    return f"{directory}/{content.sha256}{content.suffix}"


def _reference_view(view: ManifestView, entry: ManifestEntry, contents: dict[str, VerifiedContent]) -> dict:
    content = contents[view.file]
    if (view.width is not None and view.width != content.width) or (
        view.height is not None and view.height != content.height
    ):
        raise invalid_import(f"Image dimensions do not match the manifest: {view.file}")
    return {
        **view.model_dump(exclude={"file"}),
        "path": _content_path(content, "image"),
        "width": content.width,
        "height": content.height,
        "archive_version": entry.archive_version,
        "product_version": entry.product_version,
    }


def _merge_views(old: dict, incoming: list[dict], warnings: list[str], conflicts: list[str]) -> list[dict]:
    existing = old.get("reference_views", [])
    by_slot = {_view_slot(view): view for view in existing}
    frozen_versions = {
        (view.get("archive_version"), _view_slot(view)): view
        for snapshot in [*old.get("external_library_history", []), old]
        for view in snapshot.get("reference_views", [])
        if view.get("frozen")
    }
    merged = []
    for view in incoming:
        by_slot.pop(_view_slot(view), None)
        frozen_version = frozen_versions.get((view["archive_version"], _view_slot(view)))
        if frozen_version and frozen_version.get("sha256") != view["sha256"]:
            conflicts.append("frozen_view_conflict")
        if frozen_version:
            view = {**view, "frozen": True}
        merged.append(view)
    if by_slot:
        warnings.append("source_views_retained")
        merged.extend(by_slot.values())
    return merged


def _merge_voice(
    entry: ManifestEntry,
    library_id: str,
    updated: dict,
    contents: dict[str, VerifiedContent],
    warnings: list[str],
    conflicts: list[str],
) -> bool:
    if entry.voice is None:
        if updated.get("external_voice"):
            warnings.append("source_voice_retained")
        return False
    voice = entry.voice
    previous = updated.get("external_voice") or {}
    clips = [{**clip.model_dump(), "path": _content_path(contents[clip.file], "audio")} for clip in voice.clips]
    same_voice_version = previous.get("voice_id") == voice.voice_id and previous.get("version") == voice.version
    if previous and not same_voice_version:
        updated.setdefault("external_voice_history", []).append(copy.deepcopy(previous))
    frozen = {
        clip.get("archive_path") or clip.get("slot") or clip.get("file"): clip
        for clip in previous.get("clips", [])
        if clip.get("frozen") and same_voice_version
    }
    historical_frozen = {
        clip.get("archive_path") or clip.get("slot") or clip.get("file"): clip
        for snapshot in updated.get("external_voice_history", [])
        if snapshot.get("voice_id") == voice.voice_id and snapshot.get("version") == voice.version
        for clip in snapshot.get("clips", [])
        if clip.get("frozen")
    }
    for clip in clips:
        key = clip.get("archive_path") or clip.get("slot") or clip["file"]
        historical = historical_frozen.get(key)
        if historical and historical["sha256"] != clip["sha256"]:
            conflicts.append("frozen_voice_conflict")
        earlier = frozen.pop(clip.get("archive_path") or clip.get("slot") or clip["file"], None)
        if earlier and earlier["sha256"] != clip["sha256"]:
            conflicts.append("frozen_voice_conflict")
        if earlier or historical:
            clip["frozen"] = True
    if frozen:
        clips.extend(frozen.values())
        warnings.append("source_voice_clips_retained")
    selected = next((clip for clip in clips if clip["file"] == voice.selected_clip), None)
    active = bool(
        voice.baseline_status == "confirmed"
        and voice.baseline
        and voice.baseline == entry.baseline
        and voice.status == "approved"
        and selected
        and selected["confirmed"]
    )
    updated["external_voice"] = {
        **voice.model_dump(exclude={"clips"}),
        "library_id": library_id,
        "external_id": entry.external_id,
        "clips": clips,
    }
    if active and selected is not None:
        updated["reference_audio"] = selected["path"]
        updated["reference_audio_transcript"] = selected["transcript"]
    else:
        warnings.append("voice_binding_pending")
        # A previously imported binding must not remain active after approval is withdrawn.
        previous_paths = {clip.get("path") for clip in previous.get("clips", [])}
        if updated.get("reference_audio") in previous_paths:
            updated["reference_audio"] = ""
            updated["reference_audio_transcript"] = ""
        elif updated.get("reference_audio"):
            warnings.append("existing_voice_binding_retained")
    return not active


def _view_changes(old: dict, updated: dict, incoming: list[dict]) -> list[dict]:
    previous = {_view_slot(view): view for view in old.get("reference_views", [])}
    supplied = {_view_slot(view) for view in incoming}
    result = []
    for view in updated.get("reference_views", []):
        before = previous.get(_view_slot(view))
        operation = (
            "retain"
            if _view_slot(view) not in supplied
            else "add"
            if before is None
            else "unchanged"
            if before == view
            else "update"
        )
        result.append(
            {
                "role": view["role"],
                "view": view["view"],
                "framing": view["framing"],
                "operation": operation,
                "previous_sha256": before.get("sha256") if before else None,
                "sha256": view["sha256"],
                "archive_version": view["archive_version"],
                "previous_archive_version": before.get("archive_version") if before else None,
            }
        )
    return result


def build_preview(project: dict, manifest: LibraryManifest, contents: dict[str, VerifiedContent]) -> tuple[dict, dict]:
    """Build a deterministic plan. Missing source records never imply deletion."""
    candidate = copy.deepcopy(project)
    rows = []
    pending = 0
    for item in manifest.entries:
        spec = ASSET_SPECS[item.asset_type]
        bucket = candidate.setdefault(spec.bucket_key, {})
        existing_name = find_project_asset_name(candidate, item.name)
        conflicts: list[str] = []
        warnings: list[str] = []
        identity = _identity(item, manifest.library_id)
        old = bucket.get(item.name, {})
        if existing_name and (existing_name.asset_type != item.asset_type or existing_name.name != item.name):
            conflicts.append("name_conflict")
        for registered_name, registered in bucket.items():
            registered_identity = registered.get("external_library") or {}
            if registered_name != item.name and _same_identity(registered_identity, identity):
                conflicts.append("identity_already_mapped")
        if old.get("external_library") and not _same_identity(old["external_library"], identity):
            conflicts.append("identity_conflict")
        updated = copy.deepcopy(old)
        previous_identity = old.get("external_library") or {}
        version_changed = bool(previous_identity and previous_identity.get("archive_version") != item.archive_version)
        if version_changed:
            updated.setdefault("external_library_history", []).append(
                {
                    "external_library": copy.deepcopy(previous_identity),
                    "description": old.get("description", ""),
                    "reference_views": copy.deepcopy(old.get("reference_views", [])),
                }
            )
        updated["description"] = item.description
        updated["external_library"] = identity
        incoming = [_reference_view(view, item, contents) for view in item.views]
        if incoming or old.get("reference_views"):
            updated["reference_views"] = _merge_views(old, incoming, warnings, conflicts)
        if item.asset_type == "character":
            updated.setdefault("voice_style", "")
            confirmed = next((view for view in updated.get("reference_views", []) if view["confirmed"]), None)
            old_view_paths = {view["path"] for view in old.get("reference_views", [])}
            if not old.get("reference_image") or old.get("reference_image") in old_view_paths:
                updated["reference_image"] = confirmed["path"] if confirmed else ""
            pending += int(_merge_voice(item, manifest.library_id, updated, contents, warnings, conflicts))
        changes = sorted(key for key in old.keys() | updated.keys() if old.get(key) != updated.get(key))
        if (
            old.get("external_library", {}).get("frozen")
            and not version_changed
            and any(field in changes for field in ("external_library", "reference_views", "description"))
        ):
            conflicts.append("frozen_pack_conflict")
        for snapshot in old.get("external_library_history", []):
            archived = snapshot.get("external_library") or {}
            if (
                archived.get("frozen")
                and archived.get("archive_version") == item.archive_version
                and any(
                    snapshot.get(field) != updated.get(field)
                    for field in ("external_library", "reference_views", "description")
                )
            ):
                conflicts.append("frozen_pack_conflict")
        if not item.views and item.voice is not None:
            warnings.append("voice_only_entry")
        if item.views and not any(view.confirmed for view in item.views):
            warnings.append("image_confirmation_pending")
        operation = "conflict" if conflicts else "add" if not old else "update" if changes else "unchanged"
        rows.append(
            {
                "asset_type": item.asset_type,
                "name": item.name,
                **identity,
                "operation": operation,
                "previous_archive_version": previous_identity.get("archive_version"),
                "previous_product_version": previous_identity.get("product_version"),
                "view_changes": _view_changes(old, updated, incoming),
                "changes": changes,
                "warnings": sorted(set(warnings)),
                "conflicts": sorted(set(conflicts)),
            }
        )
        if not conflicts:
            bucket[item.name] = updated
    summary = {
        key: sum(row["operation"] == operation for row in rows)
        for key, operation in (
            ("added", "add"),
            ("updated", "update"),
            ("unchanged", "unchanged"),
            ("conflicts", "conflict"),
        )
    }
    summary["pending_voice_bindings"] = pending
    file_refs = _all_files(manifest)
    summary["deduplicated_files"] = len(file_refs) - len({file.sha256 for file, _ in file_refs})
    token_payload = {
        "manifest": manifest.model_dump(),
        "assets": {spec.bucket_key: project.get(spec.bucket_key, {}) for spec in ASSET_SPECS.values()},
    }
    token = hashlib.sha256(json.dumps(token_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "preview_token": token,
        "can_apply": not summary["conflicts"],
        "summary": summary,
        "entries": rows,
    }, candidate


def preview_import(pm: ProjectManager, project_name: str, manifest: LibraryManifest, uploads: dict[str, bytes]) -> dict:
    contents = verify_contents(manifest, uploads)
    preview, _ = build_preview(pm.load_project(project_name), manifest, contents)
    return preview


def _target_path(project_dir: Path, relative: str) -> Path:
    try:
        target = safe_join(project_dir, relative)
    except ValueError as exc:
        raise invalid_import("Library media destinations must remain inside the project") from exc
    cursor = project_dir
    for component in relative.split("/"):
        cursor = cursor / component
        if cursor.is_symlink():
            raise invalid_import("Library media destinations cannot contain symbolic links")
    return target


def apply_import(
    pm: ProjectManager,
    project_name: str,
    manifest: LibraryManifest,
    uploads: dict[str, bytes],
    preview_token: str,
) -> dict:
    contents = verify_contents(manifest, uploads)
    project_dir = pm.get_project_path(project_name)
    writes: list[tuple[bytes, Path]] = []
    result: dict[str, Any] = {}

    def mutate(project: dict) -> None:
        preview, candidate = build_preview(project, manifest, contents)
        if preview["preview_token"] != preview_token:
            raise ConflictError("asset_library_import_stale")
        if not preview["can_apply"]:
            raise ConflictError("asset_library_import_conflict").with_diagnostic(preview["entries"])
        seen: set[str] = set()
        for item, kind in _all_files(manifest):
            content = contents[item.file]
            relative = _content_path(content, kind)
            if relative in seen:
                continue
            seen.add(relative)
            target = _target_path(project_dir, relative)
            if target.exists():
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != content.sha256:
                    raise ConflictError("asset_library_import_content_conflict")
            else:
                writes.append((content.data, target))
        for item in manifest.entries:
            bucket = ASSET_SPECS[item.asset_type].bucket_key
            previous = project.get(bucket, {}).get(item.name, {})
            updated = candidate[bucket][item.name]
            if any(
                previous.get(field) != updated.get(field) for field in ("reference_audio", "reference_audio_transcript")
            ):
                updated["voice_updated_at"] = datetime.now(UTC).isoformat()
            project.setdefault(bucket, {})[item.name] = updated
        result.update(preview)
        result["applied"] = True

    pm.update_project_with_file_writes(project_name, mutate, writes)
    return result
