"""Illustrated books use the production ComfyUI resolver/assembler without any video model."""

from __future__ import annotations

import asyncio
import io
import json
import wave

import httpx
import pytest
import respx
from PIL import Image

from lib.book.domain import all_segments, build_timeline, import_book, segment_fingerprint
from lib.book.models import AudioVersion, Keyframe, SoundEffect
from lib.book.store import BookStore
from lib.config.resolver import ConfigResolver
from lib.custom_provider import make_provider_id
from lib.db.models.custom_endpoint import CustomEndpoint
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from lib.project.project_manager import get_project_manager
from server.services.book.service import enqueue_export, enqueue_keyframe, execute_book_task, snapshot
from tests.factories import comfyui_endpoint_definition


def _wav(seconds=0.25):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\0\0" * int(seconds * 24000))
    return stream.getvalue()


async def _image_provider(factory):
    definition = comfyui_endpoint_definition(media_type="image")
    definition["workflow"]["9"] = {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "Book"}}
    definition["bindings"]["output"] = [{"node": "9", "class_type": "SaveImage"}]
    async with factory() as session:
        endpoint = CustomEndpoint(
            definition=definition,
            kind="comfyui",
            schema_version="1.0.0",
            media_type="image",
            display_name="Book images",
        )
        provider = CustomProvider(
            display_name="Local ComfyUI", discovery_format="comfyui", base_url="http://book-comfy.test:8188", api_key=""
        )
        session.add_all([endpoint, provider])
        await session.flush()
        session.add(
            CustomProviderModel(
                provider_id=provider.id,
                model_id="book-image-workflow",
                display_name="Book image",
                endpoint=f"ce-{endpoint.id}",
                is_default=True,
                is_enabled=True,
            )
        )
        await session.commit()
        return make_provider_id(provider.id)


def _create(provider):
    manager = get_project_manager()
    manager.create_project("illustrated-test")
    manager.create_project_metadata("illustrated-test", "图声书", extras={"output_mode": "illustrated_audiobook"})
    store = BookStore(manager, "illustrated-test")
    book = import_book("第一章 雨夜\n她说：“是谁？”\n他说：“是我。”", max_segment_chars=8)
    audio = store.project_dir / "book" / "fixture.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_wav())
    for segment in all_segments(book):
        segment.audio_versions = [
            AudioVersion(
                id="v1", path="book/fixture.wav", duration_seconds=0.25, fingerprint=segment_fingerprint(book, segment)
            )
        ]
        segment.selected_audio_version = "v1"
        segment.status = "succeeded"
    segments = all_segments(book)
    book.keyframes = [
        Keyframe(
            id="rain", segment_id=segments[0].id, prompt="雨夜，门外", provider=provider, model="book-image-workflow"
        ),
        Keyframe(
            id="door", segment_id=segments[1].id, prompt="门缓缓打开", provider=provider, model="book-image-workflow"
        ),
    ]
    book.effects = [
        SoundEffect(
            id="footstep",
            segment_id=segments[1].id,
            path="book/fixture.wav",
            duration_seconds=0.1,
            source="synthetic test fixture",
        )
    ]
    store.save(book)
    return store


async def test_comfyui_images_export_and_audio_retiming_without_video(db_factory, generation_queue):
    provider = await _image_provider(db_factory)
    resolver = ConfigResolver(db_factory)
    store = await asyncio.to_thread(_create, provider)
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
    with respx.mock() as mock:
        submit = mock.post("http://book-comfy.test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "book-prompt", "node_errors": {}})
        )
        mock.get("http://book-comfy.test:8188/history/book-prompt").mock(
            return_value=httpx.Response(
                200,
                json={
                    "book-prompt": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"9": {"images": [{"filename": "book.png", "subfolder": "", "type": "output"}]}},
                    }
                },
            )
        )
        mock.get("http://book-comfy.test:8188/view").mock(return_value=httpx.Response(200, content=image.getvalue()))
        for frame_id in ("rain", "door"):
            await enqueue_keyframe("illustrated-test", frame_id)
            task = await generation_queue.claim_next_task(media_type="image")
            assert task is not None
            result = await execute_book_task(task, resolver=resolver)
            await generation_queue.mark_task_succeeded(task["task_id"], result)
        assert submit.call_count == 2
        prompts = [json.loads(call.request.content)["prompt"]["6"]["inputs"]["text"] for call in submit.calls]
        assert prompts == ["雨夜，门外", "门缓缓打开"]
        assert all("video" not in str(call.request.url) for call in mock.calls)
    book = await asyncio.to_thread(store.load)
    assert all(frame.status == "succeeded" and frame.path for frame in book.keyframes)
    await enqueue_export("illustrated-test", "wav")
    task = await generation_queue.claim_next_task(media_type="render")
    result = await execute_book_task(task, resolver=resolver)
    await generation_queue.mark_task_succeeded(task["task_id"], result)
    assert (await asyncio.to_thread(snapshot, "illustrated-test"))["status"]["complete"] is True
    before = build_timeline(book, require_audio=True)
    first = all_segments(book)[0]
    first.audio_versions[0].duration_seconds = 0.75
    after = build_timeline(book, require_audio=True)
    assert after.keyframes[1].start_seconds == pytest.approx(before.keyframes[1].start_seconds + 0.5)
    assert after.effects[0].start_seconds == pytest.approx(before.effects[0].start_seconds + 0.5)
    longer = store.project_dir / "book/longer.wav"
    await asyncio.to_thread(longer.write_bytes, _wav(0.75))
    first.audio_versions[0].path = "book/longer.wav"
    await asyncio.to_thread(store.save, book)
    assert (await asyncio.to_thread(snapshot, "illustrated-test"))["status"]["complete"] is False
    await enqueue_export("illustrated-test", "wav")
    task = await generation_queue.claim_next_task(media_type="render")
    result = await execute_book_task(task, resolver=resolver)
    await generation_queue.mark_task_succeeded(task["task_id"], result)
    state = await asyncio.to_thread(snapshot, "illustrated-test")
    manifest = json.loads(await asyncio.to_thread((store.project_dir / state["exports"]["manifest_path"]).read_text))
    assert manifest["chapters"][0]["keyframes"][1]["time"] == pytest.approx(0.75)
    assert state["status"]["complete"] is True
