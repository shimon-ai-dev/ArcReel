"""Book edits and delayed HTTP completions cannot steal newer production state."""

from __future__ import annotations

import asyncio
import io
import wave

import httpx
import pytest
import respx

from lib.book.domain import all_segments, import_book
from lib.book.models import VoiceProfile
from lib.book.store import BookStore
from lib.project.project_manager import get_project_manager
from server.services.book.service import edit_segment, enqueue_speech, execute_book_task


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    return buffer.getvalue()


def _book() -> BookStore:
    manager = get_project_manager()
    manager.create_project("race-book")
    manager.create_project_metadata("race-book", extras={"output_mode": "audiobook"})
    store = BookStore(manager, "race-book")
    book = import_book("她说你好。")
    book.voices["narrator"] = VoiceProfile(
        id="narrator",
        adapter="indextts2",
        model="indextts2",
        base_url="http://127.0.0.1:7861",
        reference_audio="narrator.wav",
    )
    store.save(book)
    return store


@pytest.mark.parametrize("succeed", [True, False])
async def test_edit_during_synthesis_keeps_new_pending_state(generation_queue, succeed: bool) -> None:
    store = await asyncio.to_thread(_book)
    book = await asyncio.to_thread(store.load)
    segment_id = all_segments(book)[0].id
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(200, content=_wav()) if succeed else httpx.Response(503, text="old generation failed")

    with respx.mock() as mock:
        mock.post("http://127.0.0.1:7861/synthesize").mock(side_effect=respond)
        await enqueue_speech("race-book")
        task = await generation_queue.claim_next_task(media_type="audio")
        execution = asyncio.create_task(execute_book_task(task))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await asyncio.to_thread(edit_segment, "race-book", segment_id, "她说早上好。")
            release.set()
            if succeed:
                await execution
            else:
                with pytest.raises(httpx.HTTPStatusError):
                    await execution
        finally:
            release.set()
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
    current = all_segments(await asyncio.to_thread(store.load))[0]
    assert current.text == "她说早上好。"
    assert current.status == "pending"
    assert current.task_id is None
    assert current.error is None
    assert current.selected_audio_version is None
    assert len(current.audio_versions) == (1 if succeed else 0)


async def test_edit_of_successful_speech_can_fail_and_retry_with_history(generation_queue) -> None:
    store = await asyncio.to_thread(_book)
    with respx.mock() as mock:
        endpoint = mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(200, content=_wav()))
        await enqueue_speech("race-book")
        task = await generation_queue.claim_next_task(media_type="audio")
        result = await execute_book_task(task)
        await generation_queue.mark_task_succeeded(task["task_id"], result)
        previous = all_segments(await asyncio.to_thread(store.load))[0]
        await asyncio.to_thread(edit_segment, "race-book", previous.id, "她说再见。")
        endpoint.mock(return_value=httpx.Response(503, text="model unavailable"))
        await enqueue_speech("race-book")
        queued = all_segments(await asyncio.to_thread(store.load))[0]
        assert queued.status == "queued"
        task = await generation_queue.claim_next_task(media_type="audio")
        with pytest.raises(httpx.HTTPStatusError):
            await execute_book_task(task)
        await generation_queue.mark_task_failed(task["task_id"], "model unavailable")
        failed = all_segments(await asyncio.to_thread(store.load))[0]
        assert failed.status == "failed"
        assert failed.error
        assert failed.selected_audio_version is None
        assert [version.id for version in failed.audio_versions] == [version.id for version in previous.audio_versions]
        endpoint.mock(return_value=httpx.Response(200, content=_wav()))
        await enqueue_speech("race-book")
        task = await generation_queue.claim_next_task(media_type="audio")
        await execute_book_task(task)
    recovered = all_segments(await asyncio.to_thread(store.load))[0]
    assert recovered.status == "succeeded"
    assert len(recovered.audio_versions) == 2
    assert recovered.selected_audio_version != previous.selected_audio_version


async def test_stale_queued_voice_cannot_call_a_different_provider(generation_queue) -> None:
    from server.services.book.service import save_document

    store = await asyncio.to_thread(_book)
    await enqueue_speech("race-book")
    current = await asyncio.to_thread(store.load)
    current.voices["narrator"].adapter = "provider"
    current.voices["narrator"].model = "different-provider/new-model"
    current.voices["narrator"].base_url = ""
    await asyncio.to_thread(save_document, "race-book", current)
    task = await generation_queue.claim_next_task(media_type="audio")
    with respx.mock() as mock, pytest.raises(ValueError, match=r"(?i)(stale|changed|superseded)"):
        await execute_book_task(task)
    assert not mock.calls
    after = all_segments(await asyncio.to_thread(store.load))[0]
    assert after.status == "pending"
    assert after.task_id is None
    assert after.error is None
    assert after.audio_versions == []


async def test_fast_worker_completion_is_not_downgraded_by_late_enqueue_receipt(file_db_factory) -> None:
    from lib.generation.generation_queue import GenerationQueue

    class CompletingQueue(GenerationQueue):
        async def enqueue_task(self, **kwargs):
            receipt = await super().enqueue_task(**kwargs)
            claimed = await self.claim_next_task(media_type="audio")
            result = await execute_book_task(claimed)
            await self.mark_task_succeeded(claimed["task_id"], result)
            return receipt

    store = await asyncio.to_thread(_book)
    queue = CompletingQueue(session_factory=file_db_factory)
    with respx.mock() as mock:
        mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(200, content=_wav()))
        await enqueue_speech("race-book", queue=queue)
    current = all_segments(await asyncio.to_thread(store.load))[0]
    assert current.status == "succeeded"
    assert current.selected_audio_version is not None
    assert current.task_id is not None


async def test_reimport_retains_ownership_of_unchanged_running_segment(generation_queue) -> None:
    from server.services.book.service import import_source

    store = await asyncio.to_thread(_book)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(200, content=_wav())

    with respx.mock() as mock:
        mock.post("http://127.0.0.1:7861/synthesize").mock(side_effect=respond)
        await enqueue_speech("race-book")
        task = await generation_queue.claim_next_task(media_type="audio")
        execution = asyncio.create_task(execute_book_task(task))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await asyncio.to_thread(import_source, "race-book", "她说你好。新的尾声。")
            release.set()
            await execution
        finally:
            release.set()
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
    first, added = all_segments(await asyncio.to_thread(store.load))
    assert first.status == "succeeded"
    assert first.selected_audio_version is not None
    assert added.status == "pending"
    assert added.selected_audio_version is None
