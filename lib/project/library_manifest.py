"""Portable, content-backed external library manifest and persisted reference metadata."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lib.project.asset_types import validate_asset_name

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ViewRole = Literal["identity", "look", "action", "space"]


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def relative_metadata_path(value: str) -> str:
    """Source paths are descriptive only and never resolved by the server."""
    if not value or "\\" in value or "\x00" in value or ":" in value:
        raise ValueError("a relative POSIX path is required")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("absolute paths and dot segments are not allowed")
    return value


class SourceFile(ManifestModel):
    sha256: Digest
    archive_path: str | None = Field(default=None, max_length=1000)
    product_path: str | None = Field(default=None, max_length=1000)
    index_path: str | None = Field(default=None, max_length=1000)
    approval_path: str | None = Field(default=None, max_length=1000)
    slot: str | None = Field(default=None, max_length=200)
    frozen: bool = False
    confirmed: bool = False

    @field_validator("archive_path", "product_path", "index_path", "approval_path")
    @classmethod
    def safe_metadata_path(cls, value: str | None) -> str | None:
        return relative_metadata_path(value) if value is not None else None


class UploadedFile(SourceFile):
    file: str = Field(min_length=1, max_length=255)

    @field_validator("file")
    @classmethod
    def upload_name(cls, value: str) -> str:
        relative_metadata_path(value)
        if "/" in value:
            raise ValueError("upload file must be a unique basename")
        return value


class ViewLabels(ManifestModel):
    role: ViewRole
    view: str = Field(default="unspecified", min_length=1, max_length=80)
    framing: str = Field(default="unspecified", min_length=1, max_length=80)


class ManifestView(UploadedFile, ViewLabels):
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class ReferenceView(SourceFile, ViewLabels):
    path: str
    archive_version: Identifier
    product_version: Identifier | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @field_validator("path")
    @classmethod
    def project_path(cls, value: str) -> str:
        return relative_metadata_path(value)


class ManifestVoiceClip(UploadedFile):
    transcript: str = Field(default="", max_length=100_000)


class VoiceApproval(ManifestModel):
    voice_id: Identifier
    version: Identifier
    baseline: Identifier | None = None
    baseline_status: Literal["pending", "confirmed"] = "pending"
    status: ApprovalStatus = "pending"
    technical_pass: bool = False
    agent_listened: bool = False
    model_adapted: bool = False
    clone_tested: bool = False
    selected_clip: str | None = None


class ManifestVoice(VoiceApproval):
    clips: list[ManifestVoiceClip] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def selected_clip_exists(self) -> Self:
        names = [clip.file for clip in self.clips]
        if len(set(names)) != len(names):
            raise ValueError("voice clip filenames must be unique")
        if self.selected_clip is not None and self.selected_clip not in names:
            raise ValueError("selected_clip must name an uploaded clip")
        return self


class ReferenceVoiceClip(SourceFile):
    path: str
    file: str
    transcript: str = Field(default="", max_length=100_000)

    @field_validator("path")
    @classmethod
    def project_path(cls, value: str) -> str:
        return relative_metadata_path(value)


class ExternalVoice(VoiceApproval):
    library_id: Identifier
    external_id: Identifier
    clips: list[ReferenceVoiceClip]


class EntryEvidence(ManifestModel):
    index_path: str | None = Field(default=None, max_length=1000)
    approval_path: str | None = Field(default=None, max_length=1000)
    coverage: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("index_path", "approval_path")
    @classmethod
    def safe_metadata_path(cls, value: str | None) -> str | None:
        return relative_metadata_path(value) if value is not None else None


class ExternalLibraryIdentity(EntryEvidence):
    voice_id: Identifier | None = None
    library_id: Identifier
    external_id: Identifier
    baseline: Identifier | None = None
    look: Identifier | None = None
    action: Identifier | None = None
    state: Identifier | None = None
    archive_version: Identifier
    product_version: Identifier | None = None
    status: ApprovalStatus = "pending"
    frozen: bool = False


class ManifestEntry(EntryEvidence):
    asset_type: Literal["character", "scene"]
    external_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=100_000)
    baseline: Identifier | None = None
    look: Identifier | None = None
    action: Identifier | None = None
    state: Identifier | None = None
    archive_version: Identifier
    product_version: Identifier | None = None
    status: ApprovalStatus = "pending"
    frozen: bool = False
    views: list[ManifestView] = Field(default_factory=list, max_length=100)
    voice: ManifestVoice | None = None

    @field_validator("name")
    @classmethod
    def asset_name(cls, value: str) -> str:
        return validate_asset_name(value)

    @model_validator(mode="after")
    def valid_media(self) -> Self:
        if not self.views and self.voice is None:
            raise ValueError("an entry needs at least one view or voice pack")
        if self.asset_type == "scene" and self.voice is not None:
            raise ValueError("voice packs belong to character entries")
        if any((view.role == "space") != (self.asset_type == "scene") for view in self.views):
            raise ValueError("scene views use space role; character views use identity, look or action")
        slots = [(v.role, v.view, v.framing) for v in self.views]
        if len(slots) != len(set(slots)):
            raise ValueError("view slots must be unique inside each entry")
        return self


class LibraryManifest(ManifestModel):
    schema_version: Literal[1]
    library_id: Identifier
    entries: list[ManifestEntry] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_targets(self) -> Self:
        names = [entry.name.casefold() for entry in self.entries]
        identities = [
            (
                e.asset_type,
                e.external_id,
                e.baseline,
                e.look,
                e.action,
                e.state,
                e.voice.voice_id if not e.views and e.voice else None,
            )
            for e in self.entries
        ]
        if len(names) != len(set(names)):
            raise ValueError("manifest target names must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("manifest external variant identities must be unique")
        return self
