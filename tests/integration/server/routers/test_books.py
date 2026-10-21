"""Book REST contracts use real scoped storage and the durable SQLite queue."""

import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from lib.generation.generation_queue import get_generation_queue
from lib.project.project_manager import ProjectManager, get_project_manager
from server.auth import CurrentUserInfo, get_current_user
from server.routers import books


@pytest.fixture
async def book_client(tmp_path, generation_queue):
    manager = ProjectManager(tmp_path / "projects")

    def create():
        manager.create_project("novel")
        manager.create_project_metadata("novel", "Novel", extras={"output_mode": "audiobook"})
        manager.create_project("picture-book")
        manager.create_project_metadata("picture-book", "Pictures", extras={"output_mode": "illustrated_audiobook"})

    await asyncio.to_thread(create)
    app = FastAPI()
    app.include_router(books.router)
    app.dependency_overrides[get_project_manager] = lambda: manager
    app.dependency_overrides[get_generation_queue] = lambda: generation_queue
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="book-reader", sub="reader")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


BASE = "/projects/novel/book"


async def test_import_save_conflict_and_source_edit_preserve_coverage(book_client):
    client = book_client
    assert (await client.get(BASE)).json()["book"] is None
    response = await client.put(BASE + "/source", json={"text": "小明说：“你好！”"})
    assert response.status_code == 200
    document = response.json()
    assert document["original_text"] == "小明说：“你好！”"
    saved = await client.put(BASE + "/document", json=document)
    assert saved.status_code == 200
    assert (await client.put(BASE + "/document", json=document)).status_code == 409
    segment = saved.json()["chapters"][0]["segments"][0]
    edited = await client.put(BASE + f"/segments/{segment['id']}/text", json={"text": "小明轻声说："})
    assert edited.status_code == 200
    assert edited.json()["normalized_text"] == "小明轻声说：“你好！”"
    status = (await client.get(BASE)).json()
    assert status["status"]["coverage_valid"] is True
    assert status["status"]["complete"] is False
    forged = edited.json()
    forged["original_text"] = "悄悄删减的原文"
    assert (await client.put(BASE + "/document", json=forged)).status_code == 400


async def test_generation_persists_caller_and_task_listing(book_client, generation_queue):
    client = book_client
    document = (await client.put(BASE + "/source", json={"text": "雨下起来了。"})).json()
    assert (await client.post(BASE + "/generate", json={})).status_code == 400
    document["voices"] = {"narrator": {"id": "narrator", "adapter": "indextts2", "model": "indextts2"}}
    assert (await client.put(BASE + "/document", json=document)).status_code == 200
    assert (await client.post(BASE + "/generate", json={"segment_ids": ["missing"]})).status_code == 400
    queued = await client.post(BASE + "/generate", json={})
    assert queued.status_code == 200
    task_ids = queued.json()["task_ids"]
    assert task_ids
    tasks = (await client.get(BASE)).json()["tasks"]
    assert {task["task_id"] for task in tasks} == set(task_ids)
    assert all(task["user_id"] == "book-reader" and task["source"] == "webui" for task in tasks)
    persisted = await generation_queue.list_tasks(project_name="novel")
    assert persisted["items"][0]["task_id"] in task_ids
    assert (await client.get(BASE)).json()["status"]["complete"] is False


async def test_export_readiness_and_mode_validation(book_client):
    client = book_client
    await client.put(BASE + "/source", json={"text": "尚未配音。"})
    assert (await client.get(BASE + "/export")).status_code == 400
    assert (await client.post(BASE + "/export", json={"format": "m4b"})).status_code == 422
    assert (await client.post(BASE + "/keyframes/missing/generate")).status_code == 400
    response = await client.post(BASE + "/export", json={"format": "wav"})
    assert response.status_code == 200
    tasks = (await client.get(BASE)).json()["tasks"]
    assert tasks[0]["user_id"] == "book-reader"
    assert tasks[0]["task_id"] in response.json()["task_ids"]
    assert (await client.get(BASE + "/export")).status_code == 400


async def test_assets_reject_invalid_bytes_and_media_path_escape(book_client):
    client = book_client
    for name, data in [("secret.txt", b"secret"), ("bad.png", b"not an image"), ("bad.wav", b"not audio")]:
        response = await client.post(BASE + "/assets", files={"file": (name, data)})
        assert response.status_code == 400
    image = BytesIO()
    Image.new("RGB", (4, 4), "red").save(image, format="PNG")
    uploaded = await client.post(BASE + "/assets", files={"file": ("scene.png", image.getvalue())})
    assert uploaded.status_code == 200
    path = uploaded.json()["path"]
    assert (await client.get(BASE + "/media/" + path)).content == image.getvalue()
    for relative in ["project.json", "book/%2e%2e/project.json", "book/missing.wav", "book/assets/no.exe"]:
        assert (await client.get(BASE + "/media/" + relative)).status_code == 400


async def test_generation_requires_authenticated_caller():
    app = FastAPI()
    app.include_router(books.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(BASE + "/generate", json={})
    assert response.status_code == 401


async def test_illustrated_keyframe_queue_preserves_caller(book_client):
    base = "/projects/picture-book/book"
    document = (await book_client.put(base + "/source", json={"text": "雨夜的小屋。"})).json()
    segment_id = document["chapters"][0]["segments"][0]["id"]
    document["keyframes"] = [{"id": "frame-1", "segment_id": segment_id, "prompt": "A cabin in rain"}]
    assert (await book_client.put(base + "/document", json=document)).status_code == 200
    response = await book_client.post(base + "/keyframes/frame-1/generate")
    assert response.status_code == 200
    tasks = (await book_client.get(base)).json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["user_id"] == "book-reader"
    assert tasks[0]["task_type"] == "book_keyframe"
    assert tasks[0]["task_id"] in response.json()["task_ids"]
