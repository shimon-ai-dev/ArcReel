"""Book service and real durable queue boundaries with an intercepted HTTP model."""

from __future__ import annotations

import asyncio
import io
import wave

import httpx
import pytest
import respx

from lib.book.domain import all_segments, import_book, replace_segment_text
from lib.book.models import VoiceProfile
from lib.book.store import BookStore
from lib.generation.generation_worker import CapacityTable, GenerationWorker
from lib.project.project_manager import get_project_manager
from server.services.book.service import (
    enqueue_export,
    enqueue_speech,
    execute_book_task,
    save_document,
    snapshot,
)
from server.services.tasks.generation_tasks import execute_generation_task
from tests.fakes import refuse_resume_execution


def _wav(seconds: float = 0.25) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * int(seconds * 24000))
    return buffer.getvalue()


def _create_book(mode: str = "audiobook") -> BookStore:
    manager = get_project_manager()
    manager.create_project("book-test")
    manager.create_project_metadata("book-test", "测试", extras={"output_mode": mode})
    store = BookStore(manager, "book-test")
    book = import_book("第一章 雨夜\n她说：“谁？”\n他说：“是我。”\n第二章 门外\n脚步声停了。", max_segment_chars=8)
    book.voices = {
        "narrator": VoiceProfile(
            id="narrator",
            adapter="indextts2",
            model="indextts2",
            base_url="http://127.0.0.1:7861",
            reference_audio="narrator.wav",
        )
    }
    store.save(book)
    return store


async def _run_pending(queue, media_type: str) -> list[dict]:
    results = []
    while task := await queue.claim_next_task(media_type=media_type):
        result = await execute_generation_task(task)
        await queue.mark_task_succeeded(task["task_id"], result)
        results.append(result)
    return results


async def test_audio_only_real_queue_export_and_local_invalidation(generation_queue) -> None:
    store = await asyncio.to_thread(_create_book)
    with respx.mock() as mock:
        endpoint = mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(200, content=_wav()))
        queued = await enqueue_speech("book-test")
        assert queued["task_ids"]
        assert len(queued["task_ids"]) == len(set(queued["task_ids"]))
        outputs = await _run_pending(generation_queue, "audio")
        assert len(outputs) == len(queued["task_ids"])
        assert all(item["duration_seconds"] == pytest.approx(0.25) for item in outputs)
        assert endpoint.call_count == len(outputs)
        assert (await enqueue_speech("book-test"))["task_ids"] == []
        await enqueue_export("book-test", "wav")
        await _run_pending(generation_queue, "render")
        result = await asyncio.to_thread(snapshot, "book-test")
        assert result["status"]["complete"] is True
        assert result["status"]["speech_quality"] == "not_assessed"
        assert len(result["exports"]["chapters"]) == 2
        assert await asyncio.to_thread((store.project_dir / result["exports"]["archive_path"]).is_file)
        book = await asyncio.to_thread(store.load)
        old_ids = [item.selected_audio_version for item in all_segments(book)]
        first = all_segments(book)[0].id
        await asyncio.to_thread(store.update, lambda current: replace_segment_text(current, first, "序章 雨夜\n"))
        changed = await enqueue_speech("book-test")
        assert len(changed["task_ids"]) == 1
        await _run_pending(generation_queue, "audio")
        updated = await asyncio.to_thread(store.load)
        assert [item.selected_audio_version for item in all_segments(updated)][1:] == old_ids[1:]
        assert (await asyncio.to_thread(snapshot, "book-test"))["status"]["complete"] is False


async def test_failure_reopen_retry_preserves_completed_segments(generation_queue) -> None:
    store = await asyncio.to_thread(_create_book)
    book = await asyncio.to_thread(store.load)
    ids = [item.id for item in all_segments(book)]
    with respx.mock() as mock:
        endpoint = mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(200, content=_wav()))
        await enqueue_speech("book-test", ids[:1])
        await _run_pending(generation_queue, "audio")
        endpoint.mock(return_value=httpx.Response(503, text="model unavailable"))
        await enqueue_speech("book-test", ids[1:2])
        failed = await generation_queue.claim_next_task(media_type="audio")
        with pytest.raises(httpx.HTTPStatusError):
            await execute_book_task(failed)
        await generation_queue.mark_task_failed(failed["task_id"], "model unavailable")
        reopened = await asyncio.to_thread(BookStore(get_project_manager(), "book-test").load)
        assert all_segments(reopened)[0].status == "succeeded"
        assert all_segments(reopened)[1].status == "failed"
        version = all_segments(reopened)[0].selected_audio_version
        endpoint.mock(return_value=httpx.Response(200, content=_wav(0.5)))
        await enqueue_speech("book-test", ids[1:2])
        await _run_pending(generation_queue, "audio")
        completed = await asyncio.to_thread(store.load)
        assert all_segments(completed)[0].selected_audio_version == version
        assert all_segments(completed)[1].status == "succeeded"
        assert all_segments(completed)[1].audio_versions[-1].duration_seconds == pytest.approx(0.5)


async def test_capability_failure_is_visible_and_not_silently_ignored(generation_queue) -> None:
    store = await asyncio.to_thread(_create_book)
    book = await asyncio.to_thread(store.load)
    all_segments(book)[0].performance.nonverbal = "gasp"
    await asyncio.to_thread(store.save, book)
    await enqueue_speech("book-test", [all_segments(book)[0].id])
    task = await generation_queue.claim_next_task(media_type="audio")
    with respx.mock() as mock, pytest.raises(ValueError, match="nonverbal"):
        await execute_book_task(task)
    assert not mock.calls
    current = await asyncio.to_thread(store.load)
    assert all_segments(current)[0].status == "failed"
    assert "nonverbal" in (all_segments(current)[0].error or "")


def test_document_save_cannot_forge_audio_or_change_source() -> None:
    store = _create_book()
    book = store.load()
    all_segments(book)[0].status = "succeeded"
    saved = save_document("book-test", book)
    assert all_segments(saved)[0].status == "pending"
    saved.normalized_text = "changed"
    with pytest.raises(ValueError, match="source"):
        save_document("book-test", saved)


async def test_worker_admits_book_audio_without_any_video_provider(file_db_factory) -> None:
    from lib.generation.generation_queue import GenerationQueue

    store = await asyncio.to_thread(_create_book)
    book = await asyncio.to_thread(store.load)
    queue = GenerationQueue(session_factory=file_db_factory)
    task = await queue.enqueue_task(
        project_name="book-test",
        task_type="book_tts",
        media_type="audio",
        resource_type="book_tts",
        resource_id=all_segments(book)[0].id,
        provider_id="book-indextts2",
        payload={},
    )
    capacity = CapacityTable.from_env()
    finished = asyncio.Event()

    async def execute(task, *, claimed_provider_id=None):
        try:
            return await execute_generation_task(task, claimed_provider_id=claimed_provider_id)
        finally:
            finished.set()

    worker = GenerationWorker(queue=queue, capacity=capacity, executor=execute, resume_executor=refuse_resume_execution)
    with respx.mock() as mock:
        mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(200, content=_wav()))
        await worker.start()
        try:
            await asyncio.wait_for(finished.wait(), timeout=10)
        finally:
            await worker.stop()
    recorded = await queue.get_task(task["task_id"])
    assert recorded["status"] == "succeeded"
