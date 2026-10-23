"""Book source, performance and anchored media, independent of video frames."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BookModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Performance(BookModel):
    emotion: str | None = None
    intensity: float = Field(default=1.0, ge=0, le=1)
    emotion_vector: list[float] | None = None
    style: str | None = None
    speed: float | None = Field(default=None, gt=0, le=4)
    nonverbal: str | None = None

    @field_validator("emotion_vector")
    @classmethod
    def valid_vector(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (len(value) != 8 or any(not 0 <= item <= 1 for item in value)):
            raise ValueError("Emotion vector must contain eight values between zero and one")
        return value


class VoiceProfile(BookModel):
    id: str = Field(min_length=1)
    name: str = ""
    adapter: str = "provider"
    model: str = ""
    base_url: str = ""
    voice: str = ""
    reference_audio: str | None = None
    reference_audio_digest: str | None = None
    reference_text: str | None = None
    source_character: str | None = None
    language: str = "zh"
    settings: dict[str, str | float | int | bool] = Field(default_factory=dict)


class PronunciationOverride(BookModel):
    """Explicit span replacement in normalized source coordinates, never an edit to source."""

    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    original: str = Field(min_length=1)
    spoken: str = Field(min_length=1)


class AudioVersion(BookModel):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    fingerprint: str = Field(min_length=1)
    created_at: str = ""
    content_digest: str | None = None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return validate_resource_path(value)


class SpeechSegment(BookModel):
    unit_id: str | None = None
    id: str = Field(min_length=1)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    text: str = Field(min_length=1)
    speaker_id: str = "narrator"
    speaker_confirmed: bool = False
    performance: Performance = Field(default_factory=Performance)
    pause_after_seconds: float = Field(default=0, ge=0, le=60)
    pronunciation: list[PronunciationOverride] = Field(default_factory=list)
    audio_versions: list[AudioVersion] = Field(default_factory=list)
    selected_audio_version: str | None = None
    status: Literal["pending", "queued", "running", "succeeded", "failed"] = "pending"
    task_id: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def valid_range(self) -> SpeechSegment:
        if self.source_end <= self.source_start:
            raise ValueError("Segment source range must be nonempty")
        return self


class BookChapter(BookModel):
    episode: int | None = Field(default=None, gt=0)
    workflow_digest: str | None = None
    id: str = Field(min_length=1)
    title: str
    segments: list[SpeechSegment] = Field(default_factory=list)


class SoundEffect(BookModel):
    id: str = Field(min_length=1)
    track: Literal["effects", "ambience", "music"] = "effects"
    segment_id: str = Field(min_length=1)
    offset_seconds: float = 0
    path: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    end_segment_id: str | None = None
    volume: float = Field(default=1, ge=0, le=4)
    fade_in_seconds: float = Field(default=0, ge=0)
    fade_out_seconds: float = Field(default=0, ge=0)
    loop: bool = False
    ducking: float = Field(default=0.25, ge=0, le=1)
    source: str = "user-provided"
    voice_consistency_note: str | None = None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return validate_resource_path(value)


class ImageVersion(BookModel):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    prompt: str = ""
    provider: str | None = None
    model: str | None = None
    reference_paths: list[str] = Field(default_factory=list)
    created_at: str = ""
    content_digest: str | None = None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return validate_resource_path(value)


class Keyframe(BookModel):
    storyboard_id: str | None = None
    versions: list[ImageVersion] = Field(default_factory=list)
    id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    offset_seconds: float = Field(default=0, ge=0)
    prompt: str = ""
    path: str | None = None
    provider: str | None = None
    model: str | None = None
    reference_paths: list[str] = Field(default_factory=list)
    status: Literal["pending", "queued", "running", "succeeded", "failed"] = "pending"
    task_id: str | None = None
    error: str | None = None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str | None) -> str | None:
        return None if value is None else validate_resource_path(value)

    @field_validator("reference_paths")
    @classmethod
    def relative_references(cls, value: list[str]) -> list[str]:
        return [validate_resource_path(path) for path in value]


class SoundCue(BookModel):
    """Source-linked sound intention, deliberately not a generated media artifact."""

    id: str
    episode: int = Field(gt=0)
    unit_id: str
    segment_id: str
    end_segment_id: str
    description: str
    track: Literal["ambience", "sfx", "music"] = "ambience"


class BookDocument(BookModel):
    origin: Literal["legacy", "episodes"] = "legacy"
    legacy_archive: str | None = None
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    title: str = ""
    original_text: str
    normalized_text: str
    chapters: list[BookChapter] = Field(default_factory=list)
    voices: dict[str, VoiceProfile] = Field(default_factory=dict)
    sound_cues: list[SoundCue] = Field(default_factory=list)
    effects: list[SoundEffect] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)


def validate_resource_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("Book media must use a project-relative POSIX path without dot segments")
    return value
