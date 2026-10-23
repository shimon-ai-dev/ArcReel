"""Book command boundaries shared by REST, Agent tools and durable workers."""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.backends.backend_assembly import assemble_backend
from lib.backends.image_backends.base import ImageGenerationRequest, ReferenceImage
from lib.book.domain import (
    all_segments,
    book_fingerprint,
    build_timeline,
    import_book,
    segment_fingerprint,
    selected_audio,
    spoken_text,
)
from lib.book.episode_bridge import build_episode_book, require_current_episodes, stale_episodes
from lib.book.models import AudioVersion, BookDocument, ImageVersion, Keyframe, SpeechSegment
from lib.book.paths import book_media_path
from lib.book.store import BookStore
from lib.book_audio.tts import BookSynthesisRequest, ExistingAudioAdapter, IndexTTS2HTTPAdapter
from lib.book_audio.voxcpm import VoxCPM2HTTPAdapter, VoxCPM2Settings
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.generation.generation_queue import GenerationQueue, get_generation_queue
from lib.infra.async_thread import run_noninterruptible_sync, run_sync_transaction
from lib.project.output_mode import is_book_project, project_output_mode
from lib.project.project_manager import ProjectManager, get_project_manager
from lib.speech.audio_utils import probe_existing_audio_duration_seconds

BOOK_TASK_TYPES = frozenset({"book_tts", "book_keyframe", "book_export"})


def book_store(project_name: str, *, projects: ProjectManager | None = None) -> BookStore:
    manager = projects or get_project_manager()
    if not is_book_project(manager.load_project(project_name)):
        raise ValueError("Book operations require an audiobook output mode")
    return BookStore(manager, project_name)


def media_path(project_dir: Path, relative: str) -> Path:
    """Resolve project media through the shared book path boundary."""
    return book_media_path(project_dir, relative)


def snapshot(project_name: str, *, projects: ProjectManager | None = None) -> dict[str, Any]:
    store = book_store(project_name, projects=projects)
    try:
        book = store.load()
    except FileNotFoundError:
        return {
            "book": None,
            "timeline": None,
            "status": {"complete": False, "coverage_valid": False, "missing_audio": [], "missing_images": []},
            "capabilities": capabilities(),
        }
    from lib.book.status import book_status

    mode = project_output_mode(store.projects.load_project(project_name))
    status = book_status(book, store.project_dir, illustrated=mode == "illustrated_audiobook")
    stale = stale_episodes(store.projects, project_name, book)
    status["stale_episodes"] = stale
    if stale:
        status["complete"] = False
        status["ready_to_export"] = False
        status["export_current"] = False
    return {
        "book": book.model_dump(mode="json"),
        "timeline": asdict(build_timeline(book)),
        "status": status,
        "capabilities": capabilities(),
        "exports": _export_receipt(store.project_dir) if status["complete"] else {},
    }


def _export_receipt(project_dir: Path) -> dict[str, Any]:
    from lib.infra.json_io import load_json

    try:
        return load_json(project_dir / "book" / "export.json")
    except FileNotFoundError:
        return {}


def capabilities() -> dict[str, Any]:
    from lib.book_audio.tts import SpeechCapabilities

    return {
        "voxcpm2": asdict(VoxCPM2HTTPAdapter("").capabilities),
        "voxcpm2_continuation": asdict(
            VoxCPM2HTTPAdapter("", settings=VoxCPM2Settings(clone_mode="continuation")).capabilities
        ),
        "indextts2": asdict(IndexTTS2HTTPAdapter("").capabilities),
        "provider": asdict(SpeechCapabilities()),
        "quality": "Text coverage is validated separately from listening quality; model output requires audition.",
    }


def sync_episode(project_name: str, episode: int, *, projects: ProjectManager | None = None) -> BookDocument:
    """Explicitly synchronize original chapter/storyboard data, preserving legacy work."""
    from lib.infra.json_io import atomic_write_json

    store = book_store(project_name, projects=projects)
    old = store.load() if store.path.exists() else None
    document = build_episode_book(store.projects, project_name, episode, old)
    if old is not None and old.origin == "legacy":
        archive = f"book/legacy/{uuid4().hex}.json"
        path = media_path(store.project_dir, archive)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, old.model_dump(mode="json"))
        document.legacy_archive = archive
    return store.save(document)


def import_source(
    project_name: str, text: str, title: str = "", *, projects: ProjectManager | None = None
) -> BookDocument:
    store = book_store(project_name, projects=projects)
    book = import_book(text, title)
    try:
        old = store.load()
    except FileNotFoundError:
        return store.save(book)
    if old.origin == "episodes":
        raise ValueError("Edit source through the original chapter workflow, then sync the episode")
    if book.normalized_text == old.normalized_text:
        old.title = title
        old.original_text = text
        return store.save(old)
    book.revision = old.revision
    book.voices = old.voices
    # Reuse unchanged source passages in order; changed segments do not inherit old audio.
    old_by_text: dict[str, list[Any]] = {}
    for segment in all_segments(old):
        old_by_text.setdefault(segment.text, []).append(segment)
    new_counts = Counter(segment.text for segment in all_segments(book))
    retained: set[str] = set()
    for segment in all_segments(book):
        candidates = old_by_text.get(segment.text, [])
        if not candidates or len(candidates) != 1 or new_counts[segment.text] != 1:
            continue
        previous = candidates.pop(0)
        segment.id = previous.id
        segment.speaker_id = previous.speaker_id
        segment.speaker_confirmed = previous.speaker_confirmed
        segment.pronunciation = [item.model_copy(deep=True) for item in previous.pronunciation]
        delta = segment.source_start - previous.source_start
        for override in segment.pronunciation:
            override.source_start += delta
            override.source_end += delta
        segment.performance = previous.performance
        segment.pause_after_seconds = previous.pause_after_seconds
        segment.audio_versions = previous.audio_versions
        segment.selected_audio_version = previous.selected_audio_version
        segment.status = previous.status
        segment.task_id = previous.task_id
        segment.error = previous.error
        retained.add(segment.id)
    book.effects = [
        effect
        for effect in old.effects
        if effect.segment_id in retained and (not effect.end_segment_id or effect.end_segment_id in retained)
    ]
    book.keyframes = [frame for frame in old.keyframes if frame.segment_id in retained]
    return store.save(book)


def save_document(project_name: str, document: BookDocument, *, projects: ProjectManager | None = None) -> BookDocument:
    store = book_store(project_name, projects=projects)
    current = store.load()
    require_current_episodes(store.projects, project_name, current)
    if current.origin == "episodes":
        if [
            (
                c.id,
                c.episode,
                c.workflow_digest,
                [(s.id, s.text, s.source_start, s.source_end, s.unit_id) for s in c.segments],
            )
            for c in document.chapters
        ] != [
            (
                c.id,
                c.episode,
                c.workflow_digest,
                [(s.id, s.text, s.source_start, s.source_end, s.unit_id) for s in c.segments],
            )
            for c in current.chapters
        ]:
            raise ValueError("Chapter structure and source belong to the original storyboard workflow")
        if document.keyframes != current.keyframes:
            raise ValueError("Edit storyboard images in the existing storyboard workflow, then sync")
    document.sound_cues = current.sound_cues
    document.origin = current.origin
    document.legacy_archive = current.legacy_archive
    if (document.original_text, document.normalized_text) != (current.original_text, current.normalized_text):
        raise ValueError("Use source import to change source text")
    old_segments = {item.id: item for item in all_segments(current)}
    for segment in all_segments(document):
        previous = old_segments.get(segment.id)
        # Artifact facts and task outcomes are written only by the generation worker.
        segment.audio_versions = previous.audio_versions if previous else []
        segment.selected_audio_version = previous.selected_audio_version if previous else None
        segment.status = previous.status if previous else "pending"
        segment.task_id = previous.task_id if previous else None
        segment.error = previous.error if previous else None
        if previous is not None and segment_fingerprint(document, segment) != segment_fingerprint(current, previous):
            segment.status = "pending"
            segment.task_id = None
            segment.error = None
    for effect in document.effects:
        if not media_path(store.project_dir, effect.path).is_file():
            raise ValueError(f"Sound asset does not exist: {effect.id}")
    previous_frames = {item.id: item for item in current.keyframes}
    for frame in document.keyframes:
        previous = previous_frames.get(frame.id)
        frame.versions = list(previous.versions) if previous else []
        basis = (frame.prompt, frame.provider, frame.model, frame.reference_paths)
        old_basis = (previous.prompt, previous.provider, previous.model, previous.reference_paths) if previous else None
        supplied_path = frame.path
        if supplied_path and (previous is None or supplied_path != previous.path):
            path = media_path(store.project_dir, supplied_path)
            if not supplied_path.startswith("book/assets/"):
                raise ValueError("Manually selected images must be uploaded book assets")
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
            frame.versions.append(
                ImageVersion(
                    id=uuid4().hex,
                    path=supplied_path,
                    prompt=frame.prompt,
                    provider="uploaded",
                    created_at=datetime.now(UTC).isoformat(),
                    content_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
            frame.status = "succeeded"
            frame.error = None
            frame.task_id = None
        elif previous is not None and basis != old_basis:
            frame.path = None
            frame.status = "pending"
            frame.error = None
            frame.task_id = None
        elif previous is not None and supplied_path == previous.path:
            frame.status = previous.status
            frame.error = previous.error
            frame.task_id = previous.task_id
        else:
            frame.status = "pending"
            frame.error = None
            frame.task_id = None
    return store.save(document)


def edit_segment(
    project_name: str, segment_id: str, text: str, *, projects: ProjectManager | None = None
) -> BookDocument:
    from lib.book.domain import replace_segment_text

    store = book_store(project_name, projects=projects)

    def change(book: BookDocument) -> BookDocument:
        if book.origin == "episodes":
            raise ValueError("Edit source through the original chapter workflow, then sync the episode")
        return replace_segment_text(book, segment_id, text)

    return store.update(change)


async def enqueue_speech(
    project_name: str,
    segment_ids: list[str] | None = None,
    *,
    force: bool = False,
    projects: ProjectManager | None = None,
    queue: GenerationQueue | None = None,
    user_id: str = "default",
    source: str = "webui",
) -> dict[str, Any]:
    store = await asyncio.to_thread(book_store, project_name, projects=projects)
    book = await asyncio.to_thread(store.load)
    await asyncio.to_thread(require_current_episodes, store.projects, project_name, book)
    segments = all_segments(book)
    requested = set(segment_ids) if segment_ids is not None else {item.id for item in segments}
    unknown = requested - {item.id for item in segments}
    if unknown:
        raise ValueError(f"Unknown speech segments: {sorted(unknown)}")
    missing_voices = {
        item.speaker_id for item in segments if item.id in requested and item.speaker_id not in book.voices
    }
    if missing_voices:
        raise ValueError(f"Configure voices for speakers: {sorted(missing_voices)}")
    tasks = []
    for segment in segments:
        if segment.id not in requested:
            continue
        cached = selected_audio(book, segment)
        if cached is not None and segment.status == "succeeded" and not force:

            def cache_valid(cached: AudioVersion = cached) -> bool:
                path = media_path(store.project_dir, cached.path)
                return path.is_file() and (
                    not cached.content_digest
                    or hashlib.sha256(path.read_bytes()).hexdigest() == cached.content_digest.removeprefix("sha256:")
                )

            exists = await asyncio.to_thread(cache_valid)
            if exists:
                continue
        voice = book.voices.get(segment.speaker_id)
        if voice is None:
            raise ValueError(f"Configure a voice for speaker: {segment.speaker_id}")
        task = await (queue or get_generation_queue()).enqueue_task(
            user_id=user_id,
            source=source,
            project_name=project_name,
            task_type="book_tts",
            media_type="audio",
            resource_type="book_tts",
            resource_id=segment.id,
            provider_id=voice.model.split("/", 1)[0] if voice.adapter == "provider" else "book-" + voice.adapter,
            payload={"fingerprint": segment_fingerprint(book, segment)},
        )

        def mark_queued(current: BookDocument, segment=segment, task=task) -> None:
            for item in all_segments(current):
                if item.id == segment.id and segment_fingerprint(current, item) == segment_fingerprint(book, segment):
                    if item.task_id == str(task["task_id"]) and item.status in {"running", "succeeded", "failed"}:
                        continue
                    item.status = "queued"
                    item.task_id = str(task["task_id"])
                    item.error = None

        if task.get("status") in {"queued", "running"}:
            await run_sync_transaction(store.update, mark_queued)
        tasks.append(task)
    return {"task_ids": [item["task_id"] for item in tasks], "tasks": tasks}


async def enqueue_keyframe(
    project_name: str,
    frame_id: str,
    *,
    projects: ProjectManager | None = None,
    queue: GenerationQueue | None = None,
    user_id: str = "default",
    source: str = "webui",
) -> dict[str, Any]:
    store = await asyncio.to_thread(book_store, project_name, projects=projects)
    project = await asyncio.to_thread(store.projects.load_project, project_name)
    if project_output_mode(project) != "illustrated_audiobook":
        raise ValueError("Keyframes require illustrated_audiobook output")
    book = await asyncio.to_thread(store.load)
    if book.origin == "episodes":
        raise ValueError("Generate the existing storyboard image, then sync the episode; no separate keyframe pipeline")
    await asyncio.to_thread(require_current_episodes, store.projects, project_name, book)
    frame = next((item for item in book.keyframes if item.id == frame_id), None)
    if frame is None:
        raise ValueError("Unknown keyframe")
    if bool(frame.provider) != bool(frame.model):
        raise ValueError("Keyframe provider and model must be selected together")
    task = await (queue or get_generation_queue()).enqueue_task(
        user_id=user_id,
        source=source,
        project_name=project_name,
        task_type="book_keyframe",
        media_type="image",
        resource_type="book_keyframe",
        resource_id=frame_id,
        payload={
            "prompt": frame.prompt,
            "image_provider": frame.provider,
            "image_model": frame.model,
            "reference_paths": frame.reference_paths,
        },
    )

    def mark_queued(current: BookDocument) -> None:
        for item in current.keyframes:
            if item.id == frame_id and (item.prompt, item.provider, item.model, item.reference_paths) == (
                frame.prompt,
                frame.provider,
                frame.model,
                frame.reference_paths,
            ):
                if item.task_id == str(task["task_id"]) and item.status in {"running", "succeeded", "failed"}:
                    continue
                item.status = "queued"
                item.task_id = str(task["task_id"])
                item.error = None

    if task.get("status") in {"queued", "running"}:
        await run_sync_transaction(store.update, mark_queued)
    return {"task_ids": [task["task_id"]], "tasks": [task]}


async def enqueue_export(
    project_name: str,
    format: str = "wav",
    *,
    projects: ProjectManager | None = None,
    queue: GenerationQueue | None = None,
    user_id: str = "default",
    source: str = "webui",
) -> dict[str, Any]:
    if format not in {"wav", "mp3"}:
        raise ValueError("Export format must be wav or mp3")
    store = await asyncio.to_thread(book_store, project_name, projects=projects)
    book = await asyncio.to_thread(store.load)
    await asyncio.to_thread(require_current_episodes, store.projects, project_name, book)
    task = await (queue or get_generation_queue()).enqueue_task(
        user_id=user_id,
        source=source,
        project_name=project_name,
        task_type="book_export",
        media_type="render",
        provider_id="render",
        resource_type="book_export",
        resource_id="book",
        payload={"format": format, "fingerprint": book_fingerprint(book)},
    )
    return {"task_ids": [task["task_id"]], "tasks": [task]}


async def execute_book_task(
    task: dict[str, Any], *, projects: ProjectManager | None = None, resolver: ConfigResolver | None = None
) -> dict[str, Any]:
    project_name = str(task["project_name"])
    store = await asyncio.to_thread(book_store, project_name, projects=projects)
    resource_id = str(task["resource_id"])
    kind = task["task_type"]
    queued_payload = task.get("payload") or {}
    queued_book = await asyncio.to_thread(store.load)
    await asyncio.to_thread(require_current_episodes, store.projects, store.project_name, queued_book)
    if kind == "book_tts" and queued_payload.get("fingerprint"):
        queued_segment = next((item for item in all_segments(queued_book) if item.id == resource_id), None)
        if queued_segment is None or segment_fingerprint(queued_book, queued_segment) != queued_payload["fingerprint"]:
            raise ValueError("Queued speech inputs changed; generate the current segment again")
    if kind == "book_keyframe" and queued_book.origin == "episodes":
        raise ValueError("Use original storyboard generation for synchronized chapters")
    if kind == "book_keyframe" and "prompt" in queued_payload:
        queued_frame = next((item for item in queued_book.keyframes if item.id == resource_id), None)
        if queued_frame is None or (
            queued_frame.prompt,
            queued_frame.provider,
            queued_frame.model,
            queued_frame.reference_paths,
        ) != (
            queued_payload["prompt"],
            queued_payload.get("image_provider"),
            queued_payload.get("image_model"),
            queued_payload.get("reference_paths", []),
        ):
            raise ValueError("Queued image inputs changed; generate the current keyframe again")
    if (
        kind == "book_export"
        and queued_payload.get("fingerprint")
        and book_fingerprint(queued_book) != queued_payload["fingerprint"]
    ):
        raise ValueError("Queued export inputs changed; export the current book again")
    if kind == "book_export":
        from lib.book_audio.export import export_book

        book = queued_book
        project = await asyncio.to_thread(store.projects.load_project, project_name)
        output = store.project_dir / "book" / "export"
        result = await run_sync_transaction(
            export_book,
            book,
            store.project_dir,
            output,
            format=(task.get("payload") or {}).get("format", "wav"),
            illustrated=project_output_mode(project) == "illustrated_audiobook",
        )
        await asyncio.to_thread(require_current_episodes, store.projects, project_name, book)
        return {"path": str(result)}

    def mark_running(book: BookDocument) -> None:
        items = all_segments(book) if kind == "book_tts" else book.keyframes
        for item in items:
            if item.id == resource_id:
                if (
                    isinstance(item, SpeechSegment)
                    and queued_payload.get("fingerprint")
                    and segment_fingerprint(book, item) != queued_payload["fingerprint"]
                ):
                    raise ValueError("Queued speech inputs changed; generate the current segment again")
                if (
                    isinstance(item, Keyframe)
                    and "prompt" in queued_payload
                    and (item.prompt, item.provider, item.model, item.reference_paths)
                    != (
                        queued_payload["prompt"],
                        queued_payload.get("image_provider"),
                        queued_payload.get("image_model"),
                        queued_payload.get("reference_paths", []),
                    )
                ):
                    raise ValueError("Queued image inputs changed; generate the current keyframe again")
                item.status = "running"
                item.task_id = str(task.get("task_id", ""))
                item.error = None

    frozen_book = await run_sync_transaction(store.update, mark_running)
    try:
        return await _execute_media(store, task, resource_id, kind, frozen_book, resolver=resolver)
    except Exception as exc:
        error_message = str(exc)

        def fail(book: BookDocument) -> None:
            items = all_segments(book) if kind == "book_tts" else book.keyframes
            for item in items:
                if item.id == resource_id and item.task_id == str(task.get("task_id", "")):
                    item.status = "failed"
                    item.error = error_message

        await run_noninterruptible_sync(store.update, fail)
        raise


async def _execute_media(
    store: BookStore,
    task: dict[str, Any],
    resource_id: str,
    kind: str,
    book: BookDocument,
    *,
    resolver: ConfigResolver | None = None,
) -> dict[str, Any]:
    project = await asyncio.to_thread(store.projects.load_project, store.project_name)
    version_id = uuid4().hex
    output = store.project_dir / "book" / "media" / f"{version_id}.{'wav' if kind == 'book_tts' else 'png'}"
    await run_sync_transaction(output.parent.mkdir, parents=True, exist_ok=True)
    resolver = resolver or ConfigResolver(async_session_factory)
    if kind == "book_tts":
        segment = next((item for item in all_segments(book) if item.id == resource_id), None)
        if segment is None:
            raise ValueError("Speech segment no longer exists")
        voice = book.voices.get(segment.speaker_id)
        if voice is None:
            raise ValueError("Speaker voice is not configured")
        fingerprint = segment_fingerprint(book, segment)
        if (task.get("payload") or {}).get("fingerprint", fingerprint) != fingerprint:
            raise ValueError("Queued speech inputs changed; generate the current segment again")
        if voice.settings and voice.adapter != "voxcpm2":
            raise ValueError("Adapter-specific voice settings are not supported by this adapter")
        if voice.adapter == "voxcpm2":
            if voice.model not in {"", "VoxCPM2", "voxcpm2", "openbmb/VoxCPM2"}:
                raise ValueError("VoxCPM2 bridge only supports its configured VoxCPM2 model")
            adapter = VoxCPM2HTTPAdapter(voice.base_url, settings=VoxCPM2Settings.model_validate(voice.settings))
        elif voice.adapter == "indextts2":
            if voice.voice:
                raise ValueError("IndexTTS2 uses reference audio, not a voice ID")
            if voice.model not in {"", "IndexTTS2", "indextts2"}:
                raise ValueError("IndexTTS2 bridge only supports its configured IndexTTS2 model")
            adapter = IndexTTS2HTTPAdapter(voice.base_url)
        elif voice.adapter == "provider":
            if not voice.model or "/" not in voice.model:
                raise ValueError("Choose an explicit provider/model for this speaker")
            if voice.base_url:
                raise ValueError("Configure the service URL on the selected provider, not the voice")
            provider_id, model_id = voice.model.split("/", 1)
            if not provider_id or not model_id:
                raise ValueError("Provider voice model must be explicit provider/model")
            resolved = await resolver.resolve_audio_backend(
                project, {"audio_provider": provider_id, "audio_model": model_id}
            )
            backend = await assemble_backend(
                provider_id=resolved.provider_id, media_type="audio", model_id=resolved.model_id, resolver=resolver
            )
            adapter = ExistingAudioAdapter(backend)
        else:
            raise ValueError(f"Unsupported book speech adapter: {voice.adapter}")
        performance = segment.performance
        reference_audio = voice.reference_audio
        if voice.adapter == "voxcpm2" and voice.source_character and reference_audio:
            reference_audio = f"{store.project_name}/{reference_audio}"
        await adapter.synthesize(
            BookSynthesisRequest(
                text=spoken_text(segment),
                output_path=output,
                voice=voice.voice,
                reference_audio=reference_audio,
                reference_text=voice.reference_text,
                emotion_vector=tuple(performance.emotion_vector or []),
                emotion_text="; ".join(value for value in (performance.emotion, performance.style) if value),
                emotion_intensity=performance.intensity,
                speed=performance.speed or 1,
                nonverbal=performance.nonverbal or "",
                language=voice.language,
            )
        )
        duration = await probe_existing_audio_duration_seconds(output)
        if duration is None or duration <= 0:
            raise ValueError("Generated speech is not decodable audio")
        digest = await asyncio.to_thread(lambda: hashlib.sha256(output.read_bytes()).hexdigest())
        version = AudioVersion(
            id=version_id,
            path=output.relative_to(store.project_dir).as_posix(),
            duration_seconds=duration,
            fingerprint=fingerprint,
            created_at=datetime.now(UTC).isoformat(),
            content_digest=digest,
        )

        def commit(current: BookDocument) -> None:
            require_current_episodes(store.projects, store.project_name, current)
            for item in all_segments(current):
                if item.id == resource_id:
                    item.audio_versions.append(version)
                    if segment_fingerprint(current, item) == fingerprint and item.task_id == str(
                        task.get("task_id", "")
                    ):
                        item.selected_audio_version = version.id
                        item.status = "succeeded"
                        item.error = None

        await run_noninterruptible_sync(store.update, commit)
        return {"path": version.path, "version": version.id, "duration_seconds": duration}
    if project_output_mode(project) != "illustrated_audiobook":
        raise ValueError("Keyframe generation requires illustrated_audiobook output")
    frame = next((item for item in book.keyframes if item.id == resource_id), None)
    if frame is None or not frame.prompt.strip():
        raise ValueError("Keyframe prompt is required")
    if bool(frame.provider) != bool(frame.model):
        raise ValueError("Keyframe provider and model must be selected together")
    generation_type = "i2i" if frame.reference_paths else "t2i"
    payload = {"image_provider": frame.provider, "image_model": frame.model} if frame.provider and frame.model else {}
    resolved = await resolver.resolve_image_backend(project, payload, generation_type=generation_type)
    backend = await assemble_backend(
        provider_id=resolved.provider_id,
        media_type="image",
        model_id=resolved.model_id,
        resolver=resolver,
        generation_type=generation_type,
    )
    references = await asyncio.to_thread(
        lambda: [ReferenceImage(str(media_path(store.project_dir, path))) for path in frame.reference_paths]
    )
    await backend.generate(
        ImageGenerationRequest(
            prompt=frame.prompt,
            output_path=output,
            reference_images=references,
            aspect_ratio=str(project.get("aspect_ratio", "16:9")),
            project_name=store.project_name,
        )
    )

    digest = await asyncio.to_thread(lambda: hashlib.sha256(output.read_bytes()).hexdigest())
    image_version = ImageVersion(
        id=version_id,
        path=output.relative_to(store.project_dir).as_posix(),
        prompt=frame.prompt,
        provider=resolved.provider_id,
        model=resolved.model_id,
        reference_paths=frame.reference_paths,
        created_at=datetime.now(UTC).isoformat(),
        content_digest=digest,
    )

    def commit_frame(current: BookDocument) -> None:
        for item in current.keyframes:
            if item.id == resource_id:
                item.versions.append(image_version)
            if (
                item.id == resource_id
                and item.task_id == str(task.get("task_id", ""))
                and (item.prompt, item.provider, item.model, item.reference_paths)
                == (
                    frame.prompt,
                    frame.provider,
                    frame.model,
                    frame.reference_paths,
                )
            ):
                item.path = output.relative_to(store.project_dir).as_posix()
                item.status = "succeeded"
                item.error = None
                item.task_id = str(task.get("task_id", ""))

    await run_noninterruptible_sync(store.update, commit_frame)
    return {"path": output.relative_to(store.project_dir).as_posix()}
