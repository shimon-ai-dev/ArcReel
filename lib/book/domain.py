"""Source fidelity, stable segmentation, synthesis cache identity and audio timing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from lib.book.coverage import covers_source_verbatim, normalize_for_coverage
from lib.book.models import AudioVersion, BookChapter, BookDocument, SpeechSegment
from lib.episode.episode_ledger import normalize_source_text
from lib.infra.content_digest import prefixed_canonical_json_digest


class BookValidationError(ValueError):
    """Book invariants are not met; callers expose this as an editable validation failure."""


def all_segments(book: BookDocument) -> list[SpeechSegment]:
    return [segment for chapter in book.chapters for segment in chapter.segments]


def validate_coverage(book: BookDocument) -> None:
    """Require exact, ordered, once-only normalized source coverage, including whitespace."""
    if normalize_source_text(book.original_text) != book.normalized_text:
        raise BookValidationError("Normalized source differs from the stored original")
    if not book.normalized_text.strip():
        raise BookValidationError("Book source must contain spoken text")
    cursor = 0
    seen: set[str] = set()
    chapter_ids: set[str] = set()
    for chapter in book.chapters:
        if chapter.id in chapter_ids or not chapter.segments:
            raise BookValidationError("Chapter IDs must be unique and chapters nonempty")
        chapter_ids.add(chapter.id)
        for segment in chapter.segments:
            if segment.id in seen:
                raise BookValidationError(f"Duplicate speech segment: {segment.id}")
            seen.add(segment.id)
            if segment.source_start != cursor:
                raise BookValidationError(f"Source gap, overlap or reordered segment: {segment.id}")
            if segment.source_end > len(book.normalized_text):
                raise BookValidationError(f"Source range exceeds the book: {segment.id}")
            if book.normalized_text[cursor : segment.source_end] != segment.text:
                raise BookValidationError(f"Source text changed in segment: {segment.id}")
            cursor = segment.source_end
            previous_end = segment.source_start
            for override in sorted(segment.pronunciation, key=lambda item: item.source_start):
                if override.source_start < previous_end or override.source_end > segment.source_end:
                    raise BookValidationError(f"Overlapping or out-of-range pronunciation: {segment.id}")
                if override.source_end <= override.source_start:
                    raise BookValidationError(f"Empty pronunciation range: {segment.id}")
                if book.normalized_text[override.source_start : override.source_end] != override.original:
                    raise BookValidationError(f"Pronunciation source mismatch: {segment.id}")
                previous_end = override.source_end
            version_ids = [version.id for version in segment.audio_versions]
            if len(version_ids) != len(set(version_ids)):
                raise BookValidationError(f"Duplicate audio version: {segment.id}")
            if segment.selected_audio_version is not None and segment.selected_audio_version not in version_ids:
                raise BookValidationError(f"Selected audio version is absent: {segment.id}")
    if cursor != len(book.normalized_text):
        raise BookValidationError("Speech segments do not completely cover the source")
    parts = [part for segment in all_segments(book) if (part := normalize_for_coverage(segment.text))]
    if not covers_source_verbatim(parts, normalize_for_coverage(book.normalized_text)):
        raise BookValidationError("Novel verbatim coverage check failed")
    for kind, events in (("sound", book.effects), ("image", book.keyframes)):
        event_ids: set[str] = set()
        for event in events:
            if event.id in event_ids or event.segment_id not in seen:
                raise BookValidationError(f"Duplicate or unanchored {kind} event: {event.id}")
            event_ids.add(event.id)
    cue_ids: set[str] = set()
    for cue in book.sound_cues:
        if cue.id in cue_ids or cue.segment_id not in seen or cue.end_segment_id not in seen:
            raise BookValidationError(f"Duplicate or unanchored sound intention: {cue.id}")
        cue_ids.add(cue.id)
    for effect in book.effects:
        if effect.end_segment_id is not None and effect.end_segment_id not in seen:
            raise BookValidationError(f"Missing sound end anchor: {effect.id}")
    for speaker_id, voice in book.voices.items():
        if voice.id != speaker_id:
            raise BookValidationError("Voice profile key must match speaker ID")


def spoken_text(segment: SpeechSegment) -> str:
    """Apply explicitly aligned pronunciation overrides without changing source or stage directions."""
    text = segment.text
    for override in sorted(segment.pronunciation, key=lambda item: item.source_start, reverse=True):
        start = override.source_start - segment.source_start
        end = override.source_end - segment.source_start
        if not 0 <= start < end <= len(text) or segment.text[start:end] != override.original:
            raise BookValidationError(f"Pronunciation source mismatch: {segment.id}")
        text = text[:start] + override.spoken + text[end:]
    return text


def segment_fingerprint(book: BookDocument, segment: SpeechSegment) -> str:
    """Only synthesis inputs count: pauses and unrelated voices do not invalidate speech."""
    voice = book.voices.get(segment.speaker_id)
    voice_data = voice.model_dump(mode="json") if voice else None
    if voice_data is not None:
        voice_data.pop("source_character", None)
    if voice_data is not None and voice_data.get("reference_text") is None:
        voice_data.pop("reference_text", None)
    return prefixed_canonical_json_digest(
        {
            "version": 1,
            "text": spoken_text(segment),
            "source_text": segment.text,
            "speaker_id": segment.speaker_id,
            "voice": voice_data,
            "performance": segment.performance.model_dump(mode="json"),
        }
    )


def selected_audio(book: BookDocument, segment: SpeechSegment) -> AudioVersion | None:
    fingerprint = segment_fingerprint(book, segment)
    return next(
        (
            version
            for version in segment.audio_versions
            if version.id == segment.selected_audio_version and version.fingerprint == fingerprint
        ),
        None,
    )


def invalidate_changed_audio(book: BookDocument) -> list[str]:
    """Mark changed synthesis inputs pending, retaining every historical version for retry/review."""
    invalidated = []
    for segment in all_segments(book):
        if segment.selected_audio_version is not None and selected_audio(book, segment) is None:
            segment.selected_audio_version = None
            segment.status = "pending"
            segment.task_id = None
            segment.error = None
            invalidated.append(segment.id)
    return invalidated


def _stable_id(kind: str, source: str, start: int, end: int) -> str:
    digest = hashlib.sha256(f"{start}:{end}:{source[start:end]}".encode()).hexdigest()[:16]
    return f"{kind}_{digest}"


def import_book(text: str, title: str = "", *, max_segment_chars: int = 300) -> BookDocument:
    """Conservative deterministic import; unidentified speakers remain narrator for manual/Agent review.

    Chapter headings and attribution words are narrated. Quotes and paragraph boundaries are preferred
    split points, but not a character is removed. No video duration or model capability is consulted.
    """
    if max_segment_chars < 1:
        raise BookValidationError("Segment character limit must be positive")
    source = normalize_source_text(text)
    if not source.strip():
        raise BookValidationError("Book source must contain spoken text")
    headings = list(re.finditer(r"(?m)^(?:第[^\n]{1,20}[章节回卷部]|Chapter\s+\w+)[^\n]*", source, re.IGNORECASE))
    starts = sorted({0, *(match.start() for match in headings)})
    names = {match.start(): match.group().strip() for match in headings}
    chapters = []
    for chapter_index, start in enumerate(starts):
        end = starts[chapter_index + 1] if chapter_index + 1 < len(starts) else len(source)
        segments = []
        cursor = start
        while cursor < end:
            limit = min(cursor + max_segment_chars, end)
            boundaries = [
                match.end()
                for match in re.finditer(r"[。！？!?][”」]?|\n|[”」]|(?=[“「])|(?<=[.!?])\s", source[cursor:limit])
                if match.end() > 0 and source[cursor : cursor + match.end()].strip()
            ]
            stop = cursor + boundaries[0] if boundaries else limit
            # Avoid a standalone whitespace-only segment at the end of a chapter.
            if not source[stop:end].strip() and end - cursor <= max_segment_chars:
                stop = end
            segment = SpeechSegment(
                id=_stable_id("seg", source, cursor, stop),
                source_start=cursor,
                source_end=stop,
                text=source[cursor:stop],
            )
            segments.append(segment)
            cursor = stop
        chapters.append(
            BookChapter(
                id=_stable_id("chapter", source, start, end),
                title=names.get(start, title or f"Chapter {chapter_index + 1}"),
                segments=segments,
            )
        )
    book = BookDocument(title=title, original_text=text, normalized_text=source, chapters=chapters)
    validate_coverage(book)
    return book


@dataclass(frozen=True)
class TimedSegment:
    id: str
    chapter_id: str
    start_seconds: float
    duration_seconds: float
    pause_after_seconds: float
    audio_path: str | None

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds + self.pause_after_seconds


@dataclass(frozen=True)
class TimedEvent:
    id: str
    chapter_id: str
    start_seconds: float
    duration_seconds: float | None
    path: str | None


@dataclass
class BookTimeline:
    segments: list[TimedSegment] = field(default_factory=list)
    effects: list[TimedEvent] = field(default_factory=list)
    keyframes: list[TimedEvent] = field(default_factory=list)
    duration_seconds: float = 0
    missing_segment_ids: list[str] = field(default_factory=list)


def build_timeline(book: BookDocument, *, require_audio: bool = False) -> BookTimeline:
    """Resolve stable anchors against actual speech durations plus deterministic silence.

    Preview missing audio has zero duration and an explicit missing list; export must require audio.
    Times are book-global. Chapter-local consumers subtract the chapter's first segment time.
    """
    validate_coverage(book)
    timeline = BookTimeline()
    by_id: dict[str, TimedSegment] = {}
    for chapter in book.chapters:
        for segment in chapter.segments:
            audio = selected_audio(book, segment)
            if audio is None:
                timeline.missing_segment_ids.append(segment.id)
            timed = TimedSegment(
                segment.id,
                chapter.id,
                timeline.duration_seconds,
                audio.duration_seconds if audio else 0,
                segment.pause_after_seconds,
                audio.path if audio else None,
            )
            timeline.segments.append(timed)
            by_id[segment.id] = timed
            timeline.duration_seconds = timed.end_seconds
    if require_audio and timeline.missing_segment_ids:
        raise BookValidationError("Required speech is missing or stale: " + ", ".join(timeline.missing_segment_ids))
    for effect in book.effects:
        anchor = by_id[effect.segment_id]
        start = anchor.start_seconds + effect.offset_seconds
        duration = effect.duration_seconds
        if effect.end_segment_id:
            duration = by_id[effect.end_segment_id].end_seconds - start
        if start < 0 or duration <= 0:
            raise BookValidationError(f"Sound event is outside its anchored range: {effect.id}")
        timeline.effects.append(TimedEvent(effect.id, anchor.chapter_id, start, duration, effect.path))
    for keyframe in book.keyframes:
        anchor = by_id[keyframe.segment_id]
        start = anchor.start_seconds + keyframe.offset_seconds
        if require_audio and start >= timeline.duration_seconds:
            raise BookValidationError(f"Keyframe is outside the book: {keyframe.id}")
        timeline.keyframes.append(TimedEvent(keyframe.id, anchor.chapter_id, start, None, keyframe.path))
    timeline.effects.sort(key=lambda item: item.start_seconds)
    timeline.keyframes.sort(key=lambda item: item.start_seconds)
    return timeline


def book_fingerprint(book: BookDocument) -> str:
    """Identity of all inputs to an export; queue/error/revision/history are not export inputs."""
    return prefixed_canonical_json_digest(
        {
            "version": 1,
            "title": book.title,
            "source": book.normalized_text,
            "chapters": [
                {
                    "id": chapter.id,
                    "title": chapter.title,
                    "segments": [
                        {
                            "id": segment.id,
                            "fingerprint": segment_fingerprint(book, segment),
                            "audio": audio.model_dump(mode="json")
                            if (audio := selected_audio(book, segment))
                            else None,
                            "pause": segment.pause_after_seconds,
                        }
                        for segment in chapter.segments
                    ],
                }
                for chapter in book.chapters
            ],
            "effects": [effect.model_dump(mode="json") for effect in book.effects],
            "keyframes": [
                {
                    "id": image.id,
                    "segment_id": image.segment_id,
                    "offset_seconds": image.offset_seconds,
                    "path": image.path,
                    "prompt": image.prompt,
                    "provider": image.provider,
                    "model": image.model,
                    "reference_paths": image.reference_paths,
                }
                for image in book.keyframes
            ],
        }
    )


def replace_segment_text(book: BookDocument, segment_id: str, text: str) -> BookDocument:
    """Return a revised source preserving stable segment/event IDs and unrelated audio caches.

    The source edit explicitly changes the book text, not the performance. BookStore archives the
    previous original before saving a source revision. Offsets after the edit shift, but IDs do not.
    Pronunciation replacements on the edited segment are cleared because they require review.
    """
    validate_coverage(book)
    replacement = normalize_source_text(text)
    if not replacement.strip():
        raise BookValidationError("A speech segment must contain text")
    result = book.model_copy(deep=True)
    segment = next((item for item in all_segments(result) if item.id == segment_id), None)
    if segment is None:
        raise BookValidationError(f"Unknown speech segment: {segment_id}")
    if replacement == segment.text:
        return result
    old_end = segment.source_end
    delta = len(replacement) - len(segment.text)
    result.normalized_text = (
        result.normalized_text[: segment.source_start] + replacement + result.normalized_text[old_end:]
    )
    result.original_text = result.normalized_text
    segment.text = replacement
    segment.source_end += delta
    segment.pronunciation = []
    segment.selected_audio_version = None
    segment.status = "pending"
    segment.task_id = None
    segment.error = None
    for following in all_segments(result):
        if following.id != segment_id and following.source_start >= old_end:
            if delta > 0:
                following.source_end += delta
                following.source_start += delta
            else:
                following.source_start += delta
                following.source_end += delta
            for override in following.pronunciation:
                override.source_start += delta
                override.source_end += delta
    invalidate_changed_audio(result)
    validate_coverage(result)
    return result
