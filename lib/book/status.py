"""Book readiness and export freshness, independent of video workflow requirements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.book.domain import BookValidationError, all_segments, book_fingerprint, selected_audio, validate_coverage
from lib.book.models import BookDocument
from lib.book.paths import book_media_path
from lib.infra.content_digest import sha256_file
from lib.infra.json_io import load_json


def book_status(book: BookDocument, project_dir: Path, *, illustrated: bool = False) -> dict[str, Any]:
    """Require fresh assets and a matching persisted export receipt to call the book complete.

    The exporter writes book/export.json with fingerprint and project-relative files after success.
    Text fidelity is reported separately from speech quality, which requires listening/model review.
    """
    errors: list[str] = []
    coverage_valid = True
    try:
        validate_coverage(book)
    except BookValidationError as exc:
        coverage_valid = False
        errors.append(str(exc))

    def valid_file(relative: str, digest: str | None = None) -> bool:
        try:
            path = book_media_path(project_dir, relative, require_file=True)
            return digest is None or sha256_file(path) == digest.removeprefix("sha256:").removeprefix("sha256-v1:")
        except (OSError, ValueError):
            return False

    missing_audio = []
    for segment in all_segments(book):
        audio = selected_audio(book, segment)
        if audio is None or segment.status != "succeeded" or not valid_file(audio.path, audio.content_digest):
            missing_audio.append(segment.id)
    missing_images = []
    if illustrated:
        if not book.keyframes:
            missing_images.append("keyframes")
        missing_images.extend(
            frame.id
            for frame in book.keyframes
            if frame.status != "succeeded" or not frame.path or not valid_file(frame.path)
        )
    missing_effects = [effect.id for effect in book.effects if not valid_file(effect.path)]
    export_current = False
    try:
        receipt = book_media_path(project_dir, "book/export.json")
    except ValueError as exc:
        receipt = None
        errors.append(str(exc))
    if receipt is not None and receipt.is_file():
        try:
            record = load_json(receipt)
            files = record.get("files") if isinstance(record, dict) else None
            export_current = bool(
                isinstance(record, dict)
                and record.get("fingerprint") == book_fingerprint(book)
                and record.get("illustrated", False) == illustrated
                and isinstance(files, list)
                and files
                and all(isinstance(path, str) and valid_file(path) for path in files)
            )
            digests = record.get("resource_digests", {}) if isinstance(record, dict) else {}
            if (
                not isinstance(digests, dict)
                or not digests
                or not all(
                    isinstance(path, str) and isinstance(digest, str) and valid_file(path, digest)
                    for path, digest in digests.items()
                )
            ):
                export_current = False
            if isinstance(digests, dict) and isinstance(files, list):
                required = set(files)
                required.update(
                    audio.path for segment in all_segments(book) if (audio := selected_audio(book, segment))
                )
                required.update(effect.path for effect in book.effects)
                if illustrated:
                    required.update(frame.path for frame in book.keyframes if frame.path)
                if not required.issubset(digests):
                    export_current = False
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    ready = coverage_valid and not missing_audio and not missing_images and not missing_effects
    return {
        "complete": ready and export_current,
        "ready_to_export": ready,
        "coverage_valid": coverage_valid,
        "missing_audio": missing_audio,
        "missing_images": missing_images,
        "missing_effects": missing_effects,
        "export_current": export_current,
        "speech_quality": "not_assessed",
        "errors": errors,
    }
