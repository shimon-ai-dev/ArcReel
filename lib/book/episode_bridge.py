"""Project existing chapter/source/storyboard truth onto the book audio timeline.

This is not another chapter splitter or image planner. The original episode ledger,
source and formal storyboard script remain authoritative. Book data holds only the
speech-performance, sound mixing and timing needed for the selected output mode.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from lib.book.domain import all_segments
from lib.book.models import BookChapter, BookDocument, Keyframe, Performance, SoundCue, SpeechSegment, VoiceProfile
from lib.book.paths import book_media_path
from lib.episode.episode_ledger import normalize_source_text, parse_positive_episode_num
from lib.episode.episode_paths import episode_source_relpath
from lib.episode.episode_sources import SourceOrigin, episode_entry, episode_source_origin
from lib.infra.content_digest import prefixed_canonical_json_digest
from lib.project.project_manager import ProjectManager
from lib.script.script_models import get_generated_assets
from lib.script.script_skeleton import resolve_kind_items


@dataclass(frozen=True)
class EpisodeInput:
    episode: int
    title: str
    source: str
    items: list[dict[str, Any]]
    id_field: str
    digest: str


def character_reference(manager: ProjectManager, name: str, character_name: str) -> tuple[str | None, str | None]:
    """Read the original project's confined audio asset; never trust a filename as a content identity."""
    character = manager.load_project(name).get("characters", {}).get(character_name)
    if not isinstance(character, dict):
        raise ValueError(f"Register speaker in the existing character assets: {character_name}")
    relative = character.get("reference_audio") or None
    if relative is None:
        return None, None
    if not isinstance(relative, str):
        raise ValueError(f"Character reference audio must be a relative path: {character_name}")
    path = book_media_path(manager.get_project_path(name), relative, require_file=True)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return relative, digest


def character_reference_text(manager: ProjectManager, name: str, character_name: str) -> str | None:
    """Return an explicitly imported transcript, preserving legacy manually entered text."""
    character = manager.load_project(name).get("characters", {}).get(character_name)
    if not isinstance(character, dict) or "reference_audio_transcript" not in character:
        return None
    value = character["reference_audio_transcript"]
    if not isinstance(value, str):
        raise ValueError(f"Character reference transcript must be text: {character_name}")
    return value


def read_episode_input(manager: ProjectManager, name: str, episode: int) -> EpisodeInput:
    project = manager.load_project(name)
    entry = episode_entry(project, episode)
    if entry is None:
        raise ValueError(f"Episode {episode} is not registered in this project")
    if episode_source_origin(entry) is SourceOrigin.NONE:
        raise ValueError(f"Episode {episode} needs its original chapter source before book synthesis")
    directory = manager.get_project_path(name)
    source = normalize_source_text(
        book_media_path(directory, episode_source_relpath(episode), require_file=True).read_text(encoding="utf-8")
    )
    filename = entry.get("script_file")
    if not isinstance(filename, str) or not filename:
        raise ValueError(f"Episode {episode} needs its existing storyboard breakdown first")
    filename = manager.normalize_script_filename(filename)
    if "/" in filename or "\\" in filename:
        raise ValueError("Episode script binding must be a filename")
    script = manager.load_script_readonly(name, filename)
    items, id_field, kind = resolve_kind_items(script)
    if kind not in {"segments", "scenes"} or not items:
        raise ValueError("Books reuse a narration or drama chapter storyboard script")
    speakers: set[str] = set()
    for item in items:
        for annotation in item.get("book_speech") or []:
            if not isinstance(annotation, dict):
                continue
            speaker = annotation.get("speaker_id")
            if isinstance(speaker, str) and speaker not in {"", "narrator"}:
                speakers.add(speaker)
    references = {
        speaker: (*character_reference(manager, name, speaker), character_reference_text(manager, name, speaker))
        for speaker in sorted(speakers)
    }
    images: dict[str, str | None] = {}
    for item in items:
        relative = get_generated_assets(item).get("storyboard_image")
        if not isinstance(relative, str) or not relative:
            continue
        path = book_media_path(directory, relative)
        images[relative] = None
        if path.is_file():
            with path.open("rb") as image:
                images[relative] = hashlib.file_digest(image, "sha256").hexdigest()
    digest = prefixed_canonical_json_digest(
        {"source": source, "items": items, "character_references": references, "storyboard_images": images}
    )
    return EpisodeInput(
        episode, str(entry.get("title") or script.get("title") or episode), source, items, id_field, digest
    )


def stale_episodes(manager: ProjectManager, name: str, book: BookDocument) -> list[int]:
    """Read-only freshness check, including storyboard artifact replacement/removal."""
    if book.origin != "episodes":
        return []
    stale = []
    changed_voices = set()
    for speaker, voice in book.voices.items():
        if voice.source_character is None:
            continue
        try:
            matches = character_reference(manager, name, voice.source_character) == (
                voice.reference_audio,
                voice.reference_audio_digest,
            )
            transcript = character_reference_text(manager, name, voice.source_character)
            if transcript is not None:
                matches = matches and voice.reference_text == transcript
        except (ValueError, OSError):
            matches = False
        if not matches:
            changed_voices.add(speaker)
    for chapter in book.chapters:
        if chapter.episode is None:
            continue
        try:
            current = read_episode_input(manager, name, chapter.episode)
            matches = current.digest == chapter.workflow_digest and not any(
                segment.speaker_id in changed_voices for segment in chapter.segments
            )
        except (ValueError, OSError):
            matches = False
        if not matches:
            stale.append(chapter.episode)
    return stale


def require_current_episodes(manager: ProjectManager, name: str, book: BookDocument) -> None:
    if stale := stale_episodes(manager, name, book):
        raise ValueError(f"Original chapters or storyboards changed; sync these episodes first: {stale}")


def _segment_id(episode: int, unit_id: str, start: int, end: int, text: str) -> str:
    digest = hashlib.sha256(f"{unit_id}:{start}:{end}:{text}".encode()).hexdigest()[:16]
    return f"speech-e{episode}-{digest}"


def _unit_parts(item: dict[str, Any], text: str) -> list[dict[str, Any]]:
    """Annotations only partition exact source; unsupported/ambiguous labels are not guessed."""
    annotations = item.get("book_speech") or []
    if not isinstance(annotations, list):
        raise ValueError("book_speech must be an ordered list")
    parts = []
    cursor = 0
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise ValueError("Speech annotations must be objects")
        start, end = annotation.get("source_start"), annotation.get("source_end")
        if not isinstance(start, int) or not isinstance(end, int) or not cursor <= start < end <= len(text):
            raise ValueError("Speech annotation source offsets must be ordered, non-overlapping and within the unit")
        if text[start:end] != annotation.get("text"):
            raise ValueError("Speech annotation text must exactly match the original storyboard source")
        if start > cursor:
            parts.append({"start": cursor, "end": start})
        parts.append({**annotation, "start": start, "end": end})
        cursor = end
    if cursor < len(text):
        parts.append({"start": cursor, "end": len(text)})
    return parts


def project_episode(inputs: EpisodeInput, offset: int = 0) -> tuple[BookChapter, list[Keyframe]]:
    """Preserve every source character, binding pictures to the original storyboard IDs."""
    segments: list[SpeechSegment] = []
    frames: list[Keyframe] = []
    cursor = 0

    def append_piece(unit_id: str, start: int, end: int, annotation: dict[str, Any] | None = None) -> str:
        data = annotation or {}
        text = inputs.source[start:end]
        if not text:
            raise ValueError("Empty storyboard source interval")
        segment = SpeechSegment(
            id=_segment_id(inputs.episode, unit_id, start, end, text + prefixed_canonical_json_digest(data)),
            unit_id=unit_id or None,
            source_start=offset + start,
            source_end=offset + end,
            text=text,
            speaker_id=data.get("speaker_id") or "narrator",
            speaker_confirmed=bool(data.get("speaker_id")),
            performance=Performance.model_validate(data.get("performance") or {}),
            pause_after_seconds=data.get("pause_after_seconds", 0),
        )
        segments.append(segment)
        return segment.id

    for item in inputs.items:
        unit_id = item.get(inputs.id_field)
        if not isinstance(unit_id, str) or not unit_id:
            raise ValueError("Storyboard is missing its stable unit ID")
        excerpt = normalize_source_text(str(item.get("novel_text") or item.get("source_text") or ""))
        if not excerpt.strip():
            raise ValueError(f"Storyboard {unit_id} requires its verbatim source passage before audio sync")
        start = inputs.source.find(excerpt, cursor)
        if start < 0:
            raise ValueError(f"Storyboard {unit_id} source is changed, reordered or absent from the original chapter")
        if start > cursor:
            append_piece("", cursor, start)
        first_segment = ""
        for part in _unit_parts(item, excerpt):
            current = append_piece(unit_id, start + part["start"], start + part["end"], part)
            if not first_segment:
                first_segment = current
        cursor = start + len(excerpt)
        image_path = get_generated_assets(item).get("storyboard_image")
        frame = Keyframe(
            id=f"storyboard-e{inputs.episode}-{unit_id}",
            storyboard_id=unit_id,
            segment_id=first_segment,
            path=image_path if isinstance(image_path, str) and image_path else None,
            status="succeeded" if image_path else "pending",
        )
        frames.append(frame)
    if cursor < len(inputs.source):
        append_piece("", cursor, len(inputs.source))
    # Whitespace is source fidelity, not an independent model utterance. Attach it
    # to a neighboring spoken segment without deleting any original characters.
    for segment in list(segments):
        if segment.text.strip() or len(segments) == 1:
            continue
        index = segments.index(segment)
        neighbor = segments[index - 1] if index else segments[1]
        if index:
            neighbor.text += segment.text
            neighbor.source_end = segment.source_end
        else:
            neighbor.text = segment.text + neighbor.text
            neighbor.source_start = segment.source_start
        for frame in frames:
            if frame.segment_id == segment.id:
                frame.segment_id = neighbor.id
        segments.remove(segment)
    # A leading heading/narration uses the first existing storyboard rather than a new image plan.
    if frames and segments:
        frames[0].segment_id = segments[0].id
    return BookChapter(
        id=f"episode-{inputs.episode}",
        episode=inputs.episode,
        title=inputs.title,
        workflow_digest=inputs.digest,
        segments=segments,
    ), frames


def build_episode_book(manager: ProjectManager, name: str, episode: int, old: BookDocument | None) -> BookDocument:
    project = manager.load_project(name)
    selected = {chapter.episode for chapter in old.chapters if chapter.episode is not None} if old else set()
    selected.add(episode)
    order = [
        parse_positive_episode_num(entry.get("episode"))
        for entry in project.get("episodes", [])
        if isinstance(entry, dict)
    ]
    if not selected.issubset(set(order)):
        raise ValueError("A synchronized chapter was removed from the project; resolve it before resyncing")
    inputs = [
        read_episode_input(manager, name, number) for number in order if number in selected and number is not None
    ]
    document = BookDocument(
        origin="episodes",
        title=project.get("title", ""),
        original_text="".join(i.source for i in inputs),
        normalized_text="".join(i.source for i in inputs),
        revision=old.revision if old else 0,
        voices=old.voices if old else {},
    )
    previous = {segment.id: segment for segment in all_segments(old)} if old else {}
    offset = 0
    for item in inputs:
        chapter, frames = project_episode(item, offset)
        for segment in chapter.segments:
            prior = previous.get(segment.id)
            if prior is not None and prior.text == segment.text:
                # Manual performance/voice edits and historical audio survive unchanged source.
                delta = segment.source_start - prior.source_start
                preserved = prior.model_copy(deep=True)
                preserved.source_start += delta
                preserved.source_end += delta
                for override in preserved.pronunciation:
                    override.source_start += delta
                    override.source_end += delta
                chapter.segments[chapter.segments.index(segment)] = preserved
        unit_cursor = 0
        for unit in item.items:
            unit_id = unit[item.id_field]
            unit_segments = [s for s in chapter.segments if s.unit_id == unit_id]
            if not unit_segments:
                continue
            excerpt = normalize_source_text(str(unit.get("novel_text") or unit.get("source_text") or ""))
            unit_position = item.source.find(excerpt, unit_cursor)
            unit_cursor = unit_position + len(excerpt)
            unit_start = offset + unit_position
            cue_ids: set[str] = set()
            for cue in unit.get("book_sound_cues") or []:
                if not isinstance(cue, dict):
                    raise ValueError("Scene sound cue must be an object")
                a, b, cue_id = cue.get("source_start"), cue.get("source_end"), cue.get("cue_id")
                length = len(excerpt)
                if type(a) is not int or type(b) is not int or not 0 <= a < b <= length:
                    raise ValueError("Scene sound cue offsets must be within the original unit source")
                if not isinstance(cue_id, str) or not cue_id or cue_id in cue_ids:
                    raise ValueError("Scene sound cue IDs must be nonempty and unique within the unit")
                cue_ids.add(cue_id)
                if not isinstance(cue.get("description"), str) or not cue["description"].strip():
                    raise ValueError("Scene sound cue needs a description")
                start = unit_start + cue["source_start"]
                end = unit_start + cue["source_end"]
                linked = [s for s in unit_segments if s.source_start < end and s.source_end > start]
                if not linked:
                    raise ValueError("Scene sound cue must anchor to its original source")
                document.sound_cues.append(
                    SoundCue(
                        id=f"cue-e{item.episode}-{unit_id}-{cue['cue_id']}",
                        episode=item.episode,
                        unit_id=unit_id,
                        segment_id=linked[0].id,
                        end_segment_id=linked[-1].id,
                        description=cue["description"],
                        track=cue.get("track", "ambience"),
                    )
                )
        document.chapters.append(chapter)
        document.keyframes.extend(frames)
        offset += len(item.source)
    segment_ids = {segment.id for segment in all_segments(document)}
    if old:
        old_cues = {cue.id: cue for cue in old.sound_cues}
        new_cues = {cue.id: cue for cue in document.sound_cues}
        document.effects = [
            effect
            for effect in old.effects
            if effect.segment_id in segment_ids
            and (not effect.end_segment_id or effect.end_segment_id in segment_ids)
            and (effect.id not in old_cues or old_cues[effect.id] == new_cues.get(effect.id))
        ]
        document.legacy_archive = old.legacy_archive
    for speaker in {segment.speaker_id for segment in all_segments(document)}:
        prior_voice = document.voices.get(speaker)
        if prior_voice is not None:
            # Explicit manual profiles are not silently rebound to a project asset.
            if prior_voice.source_character is None:
                continue
            relative, digest = character_reference(manager, name, prior_voice.source_character)
            transcript = character_reference_text(manager, name, prior_voice.source_character)
            updates: dict[str, Any] = {"reference_audio": relative, "reference_audio_digest": digest}
            if transcript is not None:
                updates["reference_text"] = transcript
            document.voices[speaker] = prior_voice.model_copy(update=updates, deep=True)
            continue
        if speaker == "narrator":
            continue
        relative, digest = character_reference(manager, name, speaker)
        document.voices[speaker] = VoiceProfile(
            id=speaker,
            name=speaker,
            adapter="voxcpm2",
            model="VoxCPM2",
            reference_audio=relative,
            reference_audio_digest=digest,
            source_character=speaker,
            reference_text=character_reference_text(manager, name, speaker),
        )
    return document
