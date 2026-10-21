"""Authenticated book editing, durable generation and export endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lib.book.models import BookDocument
from lib.book.store import BookConflictError
from lib.generation.generation_queue import GenerationQueue, get_generation_queue
from lib.infra.async_thread import run_sync_transaction
from lib.project.project_manager import ProjectManager, get_project_manager
from server.auth import CurrentUser
from server.services.book.service import (
    book_store,
    enqueue_export,
    enqueue_keyframe,
    enqueue_speech,
    import_source,
    media_path,
    save_document,
    snapshot,
)

Projects = Annotated[ProjectManager, Depends(get_project_manager)]
Queue = Annotated[GenerationQueue, Depends(get_generation_queue)]

router = APIRouter(prefix="/projects/{project_name}/book")


class SourceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000_000)
    title: str = ""


class GenerateRequest(BaseModel):
    segment_ids: list[str] | None = None
    force: bool = False


class SegmentTextRequest(BaseModel):
    text: str = Field(min_length=1)


class ExportRequest(BaseModel):
    format: Literal["wav", "mp3"] = "wav"


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, BookConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def get_book(project_name: str, projects: Projects, queue: Queue):
    try:
        result = await asyncio.to_thread(snapshot, project_name, projects=projects)
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc
    result["tasks"] = (await queue.list_tasks(project_name=project_name, page_size=200)).get("items", [])
    return result


@router.put("/source")
async def put_source(project_name: str, request: SourceRequest, projects: Projects):
    try:
        book = await run_sync_transaction(import_source, project_name, request.text, request.title, projects=projects)
        return book.model_dump(mode="json")
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.put("/document")
async def put_document(project_name: str, request: BookDocument, projects: Projects):
    try:
        book = await run_sync_transaction(save_document, project_name, request, projects=projects)
        return book.model_dump(mode="json")
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.put("/segments/{segment_id}/text")
async def put_segment_text(project_name: str, segment_id: str, request: SegmentTextRequest, projects: Projects):
    from lib.book.domain import replace_segment_text

    try:
        store = await asyncio.to_thread(book_store, project_name, projects=projects)
        document = await run_sync_transaction(
            store.update, lambda book: replace_segment_text(book, segment_id, request.text)
        )
        return document.model_dump(mode="json")
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.post("/generate")
async def generate_book(
    project_name: str, request: GenerateRequest, user: CurrentUser, projects: Projects, queue: Queue
):
    try:
        return await enqueue_speech(
            project_name, request.segment_ids, force=request.force, projects=projects, queue=queue, user_id=user.id
        )
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.post("/keyframes/{frame_id}/generate")
async def generate_keyframe(project_name: str, frame_id: str, user: CurrentUser, projects: Projects, queue: Queue):
    try:
        return await enqueue_keyframe(project_name, frame_id, projects=projects, queue=queue, user_id=user.id)
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.post("/export")
async def export_book(project_name: str, request: ExportRequest, user: CurrentUser, projects: Projects, queue: Queue):
    try:
        return await enqueue_export(project_name, request.format, projects=projects, queue=queue, user_id=user.id)
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.get("/export")
async def download_book(project_name: str, projects: Projects):
    try:
        data = await asyncio.to_thread(snapshot, project_name, projects=projects)
        if not data["status"]["complete"]:
            raise ValueError("Generate all required media and export the current book first")
        store = await asyncio.to_thread(book_store, project_name, projects=projects)
        receipt = data.get("exports") or {}
        archive = receipt.get("archive_path")
        if not isinstance(archive, str):
            raise FileNotFoundError("Book export is not ready")
        path = await asyncio.to_thread(media_path, store.project_dir, archive)
        if not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError("Book export is not ready")
        return FileResponse(path, media_type="application/zip", filename=f"{project_name}-book.zip")
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.get("/media/{relative:path}")
async def get_media(project_name: str, relative: str, projects: Projects):
    try:
        store = await asyncio.to_thread(book_store, project_name, projects=projects)
        if not relative.startswith("book/"):
            raise ValueError("Only book media can be downloaded here")
        path = await asyncio.to_thread(media_path, store.project_dir, relative)
        if path.suffix.lower() not in {".wav", ".mp3", ".png", ".jpg", ".jpeg", ".webp", ".ogg"}:
            raise ValueError("Unsupported book media type")
        if not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError("Book media not found")
        return FileResponse(path)
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc


@router.post("/assets")
async def upload_asset(project_name: str, projects: Projects, file: UploadFile = File(...)):
    try:
        store = await asyncio.to_thread(book_store, project_name, projects=projects)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".wav", ".mp3", ".ogg", ".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Upload an audio or image asset")
        data = await file.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("Asset exceeds 32 MiB")
        relative = f"book/assets/{uuid4().hex}{suffix}"

        def write() -> None:
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                from io import BytesIO

                from PIL import Image, UnidentifiedImageError

                try:
                    with Image.open(BytesIO(data)) as image:
                        image.verify()
                except (UnidentifiedImageError, OSError, SyntaxError) as exc:
                    raise ValueError("Uploaded image cannot be decoded") from exc
            path = media_path(store.project_dir, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await run_sync_transaction(write)
        if suffix in {".wav", ".mp3", ".ogg"}:
            from lib.speech.audio_utils import probe_existing_audio_duration_seconds

            duration = await probe_existing_audio_duration_seconds(store.project_dir / relative)
            if duration is None or duration <= 0:
                raise ValueError("Uploaded audio cannot be decoded")
            return {"path": relative, "duration_seconds": duration}
        return {"path": relative}
    except (ValueError, FileNotFoundError) as exc:
        raise _error(exc) from exc
