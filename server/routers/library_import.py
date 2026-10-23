"""Explicit preview/apply boundary for portable external asset library bundles."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import ValidationError

from lib.infra.api_errors import NotFoundError
from lib.infra.async_thread import run_sync_transaction
from lib.project.library_import import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    apply_import,
    invalid_import,
    preview_import,
)
from lib.project.library_manifest import LibraryManifest
from lib.project.project_manager import get_project_manager

router = APIRouter(prefix="/projects/{project_name}/assets/library-import", tags=["项目资产库导入"])


def _parse_manifest(raw: str) -> LibraryManifest:
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise invalid_import("Manifest must be at most 1 MiB")
    try:
        return LibraryManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise invalid_import(str(exc)) from exc


async def _read_uploads(files: list[UploadFile]) -> dict[str, bytes]:
    if len(files) > MAX_FILES:
        raise invalid_import("At most 200 content files can be uploaded")
    uploads: dict[str, bytes] = {}
    total = 0
    for file in files:
        name = file.filename or ""
        if not name or name in uploads:
            raise invalid_import("Content filenames must be nonempty and unique")
        content = await file.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise invalid_import("The upload bundle exceeds the supported size")
        uploads[name] = content
    return uploads


@router.post("/preview")
async def preview_library_import(
    project_name: str,
    manifest: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
):
    parsed = await asyncio.to_thread(_parse_manifest, manifest)
    uploads = await _read_uploads(files)
    try:
        return await asyncio.to_thread(preview_import, get_project_manager(), project_name, parsed, uploads)
    except FileNotFoundError as exc:
        raise NotFoundError("project_not_found", name=project_name) from exc


@router.post("/apply")
async def apply_library_import(
    project_name: str,
    manifest: Annotated[str, Form()],
    preview_token: Annotated[str, Form(min_length=64, max_length=64)],
    files: Annotated[list[UploadFile], File()],
):
    parsed = await asyncio.to_thread(_parse_manifest, manifest)
    uploads = await _read_uploads(files)
    try:
        return await run_sync_transaction(
            apply_import, get_project_manager(), project_name, parsed, uploads, preview_token
        )
    except FileNotFoundError as exc:
        raise NotFoundError("project_not_found", name=project_name) from exc
