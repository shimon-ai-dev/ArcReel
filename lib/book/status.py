"""Book readiness and export freshness, independent of video workflow requirements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.book.domain import BookValidationError, all_segments, book_fingerprint, selected_audio, validate_coverage
from lib.book.models import BookDocument, validate_resource_path
from lib.infra.json_io import load_json
from lib.infra.path_safety import safe_join


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
    missing_audio = []
    for segment in all_segments(book):
        audio = selected_audio(book, segment)
        if audio is None or segment.status != "succeeded" or not Path(safe_join(project_dir, audio.path)).is_file():
            missing_audio.append(segment.id)
    missing_images = []
    if illustrated:
        if not book.keyframes:
            missing_images.append("keyframes")
        missing_images.extend(
            frame.id
            for frame in book.keyframes
            if frame.status != "succeeded" or not frame.path or not Path(safe_join(project_dir, frame.path)).is_file()
        )
    missing_effects = [effect.id for effect in book.effects if not Path(safe_join(project_dir, effect.path)).is_file()]
    export_current = False
    receipt = project_dir / "book" / "export.json"
    if receipt.is_file():
        try:
            record = load_json(receipt)
            files = record.get("files") if isinstance(record, dict) else None
            export_current = bool(
                isinstance(record, dict)
                and record.get("fingerprint") == book_fingerprint(book)
                and record.get("illustrated", False) == illustrated
                and isinstance(files, list)
                and files
                and all(
                    isinstance(path, str) and Path(safe_join(project_dir, validate_resource_path(path))).is_file()
                    for path in files
                )
            )
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
