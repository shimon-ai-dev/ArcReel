"""Self-contained audio and illustrated-book packages, with no video dependency."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from lib.book.domain import all_segments, book_fingerprint, build_timeline, selected_audio, validate_coverage
from lib.book.models import BookDocument
from lib.book.paths import book_media_path
from lib.book_audio.mixer import MixEffect, SpeechClip, concatenate_chapters, encode_mp3, mix_chapter, read_audio
from lib.infra.content_digest import sha256_file
from lib.infra.json_io import atomic_write_json
from lib.infra.path_safety import safe_join


def build_book_package(
    book: BookDocument,
    project_dir: Path,
    output_dir: Path,
    format: str = "wav",
    illustrated: bool = False,
) -> dict[str, Any]:
    """Export into a fresh directory. Caller owns transaction cleanup on failure.

    Validation is fail-closed for source coverage, missing/stale speech and missing
    required images. Speech-quality review is explicitly not inferred from text coverage.
    """
    if format not in ("wav", "mp3"):
        raise ValueError("Only WAV and MP3 export are supported")
    validate_coverage(book)
    book = book.model_copy(deep=True)
    for segment in all_segments(book):
        audio = selected_audio(book, segment)
        if audio is None or segment.status != "succeeded":
            raise ValueError(f"Required speech is not ready: {segment.id}")
        path = book_media_path(project_dir, audio.path, require_file=True)
        if audio.content_digest:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if audio.content_digest.removeprefix("sha256:") != digest:
                raise ValueError(f"Speech content changed: {segment.id}")
        audio.duration_seconds = len(read_audio(path)) / 24000
    timeline = build_timeline(book, require_audio=True)
    if illustrated and not book.keyframes:
        raise ValueError("Illustrated books require at least one keyframe")
    for frame in book.keyframes if illustrated else []:
        if frame.status != "succeeded" or not frame.path:
            raise ValueError(f"Required keyframe is not ready: {frame.id}")
        book_media_path(project_dir, frame.path, require_file=True)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "audio").mkdir()
    (output_dir / "images").mkdir()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "title": book.title,
        "output_mode": "illustrated_audiobook" if illustrated else "audiobook",
        "clock": "audio-seconds",
        "chapters": [],
        "validation": {"source_coverage": "passed", "speech_quality": "not_reviewed"},
    }
    image_paths: dict[str, str] = {}
    if illustrated:
        for index, frame in enumerate(book.keyframes):
            assert frame.path is not None
            source = book_media_path(project_dir, frame.path, require_file=True)
            if source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                raise ValueError("Keyframes must be PNG, JPEG or WebP images")
            with Image.open(source) as image:
                image.verify()
            relative = f"images/frame-{index + 1}{source.suffix.lower()}"
            shutil.copyfile(source, output_dir / relative)
            image_paths[frame.id] = relative
    source_effects = {effect.id: effect for effect in book.effects}
    chapter_wavs = []
    for index, chapter in enumerate(book.chapters):
        timed = [item for item in timeline.segments if item.chapter_id == chapter.id]
        start, end = timed[0].start_seconds, timed[-1].end_seconds
        speech = [
            SpeechClip(book_media_path(project_dir, item.audio_path or "", require_file=True), item.pause_after_seconds)
            for item in timed
        ]
        effects = []
        for event in timeline.effects:
            effect = source_effects[event.id]
            event_end = event.start_seconds + (event.duration_seconds or 0)
            if event_end > timeline.duration_seconds:
                raise ValueError(f"Sound event extends beyond book: {event.id}")
            if effect.volume == 0:
                continue
            left, right = max(start, event.start_seconds), min(end, event_end)
            if right <= left:
                continue
            effects.append(
                MixEffect(
                    path=book_media_path(project_dir, effect.path, require_file=True),
                    start_seconds=left - start,
                    duration_seconds=right - left,
                    gain_db=20 * math.log10(max(effect.volume, 0.001)),
                    fade_in_seconds=effect.fade_in_seconds,
                    fade_out_seconds=effect.fade_out_seconds,
                    loop=effect.loop,
                    track="sfx" if effect.track == "effects" else effect.track,
                    duck_db=20 * math.log10(max(effect.ducking, 0.000001)),
                    source_offset_seconds=left - event.start_seconds,
                    envelope_duration_seconds=event.duration_seconds,
                )
            )
        wav = output_dir / f"audio/chapter-{index + 1}.wav"
        result = mix_chapter(speech, effects, wav)
        chapter_wavs.append(wav)
        relative_audio = f"audio/chapter-{index + 1}.{format}"
        if format == "mp3":
            encode_mp3(wav, output_dir / relative_audio)
        frames = []
        if illustrated:
            previous = [event for event in timeline.keyframes if event.start_seconds <= start]
            if previous:
                frames.append({"time": 0, "path": image_paths[previous[-1].id]})
            frames.extend(
                {"time": event.start_seconds - start, "path": image_paths[event.id]}
                for event in timeline.keyframes
                if start < event.start_seconds < end
            )
            if not frames or frames[0]["time"] != 0:
                raise ValueError(f"Chapter has no keyframe at its start: {chapter.id}")
        manifest["chapters"].append(
            {
                "id": chapter.id,
                "title": chapter.title,
                "audio": relative_audio,
                "duration_seconds": result.duration_seconds,
                "keyframes": frames,
                "segments": [
                    {
                        "id": segment.id,
                        "text": segment.text,
                        "time": result.speech_starts[position],
                        "duration_seconds": result.speech_durations[position],
                    }
                    for position, segment in enumerate(chapter.segments)
                ],
                "mix": {"peak_normalized_samples": result.clipped_samples},
            }
        )
    concatenate_chapters(chapter_wavs, output_dir / "audio/book.wav")
    if format == "mp3":
        encode_mp3(output_dir / "audio/book.wav", output_dir / "audio/book.mp3")
    manifest["whole_book_audio"] = f"audio/book.{format}"
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = json.dumps(manifest, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (output_dir / "index.html").write_text(PLAYER.replace("__MANIFEST__", payload), encoding="utf-8")
    return manifest


def export_book(
    book: BookDocument,
    project_dir: Path,
    output_dir: Path,
    *,
    format: str = "wav",
    illustrated: bool = False,
) -> Path:
    """Publish a unique package and zip, then atomically replace the completion receipt."""
    output_dir = safe_join(project_dir, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    package = output_dir / f"edition-{uuid.uuid4().hex}"
    manifest = build_book_package(book, project_dir, package, format=format, illustrated=illustrated)
    archive = package.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                target.write(path, path.relative_to(package).as_posix())
    prefix = package.relative_to(project_dir.resolve()).as_posix()
    files = [path.relative_to(project_dir.resolve()).as_posix() for path in package.rglob("*") if path.is_file()]
    files.append(archive.relative_to(project_dir.resolve()).as_posix())
    resource_paths = set(files)
    resource_paths.update(audio.path for segment in all_segments(book) if (audio := selected_audio(book, segment)))
    resource_paths.update(effect.path for effect in book.effects)
    if illustrated:
        resource_paths.update(frame.path for frame in book.keyframes if frame.path)
    resource_digests = {
        path: sha256_file(book_media_path(project_dir, path, require_file=True)) for path in resource_paths
    }
    receipt = {
        "resource_digests": resource_digests,
        "fingerprint": book_fingerprint(book),
        "illustrated": illustrated,
        "files": files,
        "archive_path": archive.relative_to(project_dir.resolve()).as_posix(),
        "chapters": [
            {
                "id": chapter["id"],
                "path": f"{prefix}/{chapter['audio']}",
                "duration_seconds": chapter["duration_seconds"],
            }
            for chapter in manifest["chapters"]
        ],
        "whole_book_path": f"{prefix}/{manifest['whole_book_audio']}",
        "manifest_path": f"{prefix}/manifest.json",
        "player_path": f"{prefix}/index.html",
    }
    (project_dir / "book").mkdir(exist_ok=True)
    atomic_write_json(project_dir / "book" / "export.json", receipt)
    return archive


PLAYER = """<!doctype html>
<html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ArcReel audio book</title>
<style>body{font:18px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;background:#161820;color:#eee}img{max-width:100%;max-height:60vh;display:block;margin:1rem auto}audio{width:100%}select,button{font:inherit;margin:.5rem;padding:.4rem}#text{white-space:pre-wrap;line-height:1.8}a{color:#a9cbff}</style>
<h1 id="title"></h1><label>章节 / Chapter <select id="chapters"></select></label>
<label>倍速 / Speed <select id="rate"><option value="0.75">0.75×</option><option selected value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label>
<img id="frame" alt="故事关键帧 / Story illustration" hidden><audio id="audio" controls preload="metadata"></audio><p id="text"></p><p id="error" role="alert"></p>
<script id="manifest" type="application/json">__MANIFEST__</script>
<script>
const book=JSON.parse(document.getElementById('manifest').textContent);
const audio=document.getElementById('audio'),frame=document.getElementById('frame'),chapters=document.getElementById('chapters'),rate=document.getElementById('rate'),text=document.getElementById('text');
let chapter;
document.getElementById('title').textContent=book.title;
book.chapters.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=c.title;chapters.append(o)});
function sync(){const t=audio.currentTime||0;const f=chapter.keyframes.filter(f=>f.time<=t).at(-1);frame.hidden=!f;if(f&&frame.getAttribute('src')!==f.path)frame.src=f.path;const s=chapter.segments.filter(s=>s.time<=t).at(-1);text.textContent=s?s.text:'';}
function load(i){chapter=book.chapters[i];chapters.value=i;audio.src=chapter.audio;audio.playbackRate=Number(rate.value);sync();}
chapters.onchange=()=>load(Number(chapters.value));rate.onchange=()=>audio.playbackRate=Number(rate.value);
['timeupdate','seeking','seeked','loadedmetadata','ratechange'].forEach(e=>audio.addEventListener(e,sync));
audio.addEventListener('ended',()=>{const i=Number(chapters.value)+1;if(i<book.chapters.length){load(i);audio.play().catch(()=>{})}});
audio.addEventListener('error',()=>{document.getElementById('error').textContent='音频无法打开。请在解压目录运行 python -m http.server 8000，然后打开 http://localhost:8000 / Serve the extracted directory locally.';});
load(0);
</script></html>"""
