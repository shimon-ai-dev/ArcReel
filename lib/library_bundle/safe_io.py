"""Confined source reads and content-addressed copies for local library export."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class LibraryReadError(ValueError):
    """The selected source cannot be read safely or is inconsistent."""


@dataclass(frozen=True)
class ContentFile:
    source: str
    sha256: str
    size: int
    filename: str


def relative_path(value: str) -> PurePosixPath:
    """Accept root-relative portable paths, not URLs or platform-specific paths."""
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or path.is_absolute()
        or any(part in {".", "..", ""} for part in value.split("/"))
    ):
        raise LibraryReadError("Expected a relative path inside the selected library root")
    return path


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


class LibraryReader:
    """Follow product symlinks only when their resolved targets stay in this root.

    No reads are performed until the opened file and its resolved ancestors have
    been checked. The source is never modified, including on failed conversion.
    """

    def __init__(self, root: Path):
        try:
            self.root = root.expanduser().resolve(strict=True)
            root_stat = self.root.stat()
        except (OSError, RuntimeError) as exc:
            raise LibraryReadError("The selected library root does not exist or is unreadable") from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            raise LibraryReadError("The selected library root must be a directory")
        self.root_identity = _identity(root_stat)

    def resolve(self, value: str) -> Path:
        candidate = self.root.joinpath(*relative_path(value).parts)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise LibraryReadError(
                "A reference leaves the selected root; select the complete library containing products and archives"
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise LibraryReadError("A referenced source is missing, unreadable, or contains a symlink loop") from exc
        return resolved

    def relative(self, value: Path) -> str:
        return value.relative_to(self.root).as_posix()

    def _ancestors(self, resolved: Path) -> list[tuple[Path, tuple[int, int]]]:
        paths = [self.root]
        current = self.root
        for part in resolved.relative_to(self.root).parts[:-1]:
            current = current / part
            paths.append(current)
        result = []
        for path in paths:
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_ino == 0:
                raise LibraryReadError("Source directory identity cannot be verified safely")
            result.append((path, _identity(info)))
        if result[0][1] != self.root_identity:
            raise LibraryReadError("The selected library root changed during conversion")
        return result

    @contextmanager
    def open(self, value: str) -> Generator[BinaryIO]:
        resolved = self.resolve(value)
        try:
            ancestors = self._ancestors(resolved)
            if not stat.S_ISREG(resolved.lstat().st_mode):
                raise LibraryReadError("A referenced source is not a regular file")
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            )
            descriptor = os.open(resolved, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                current = resolved.lstat()
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or opened.st_ino == 0
                    or _identity(opened) != _identity(current)
                    or ancestors != self._ancestors(resolved)
                ):
                    raise LibraryReadError("A source changed while opening it or is not a regular file")
                yield stream
                after = os.fstat(stream.fileno())
                if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise LibraryReadError("A source file changed during conversion; retry with a stable library")
        except OSError as exc:
            raise LibraryReadError("A source file could not be read safely") from exc

    def read_text(self, value: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
        with self.open(value) as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise LibraryReadError("Source metadata exceeds the supported size limit")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LibraryReadError("Source metadata must use UTF-8") from exc

    def inspect(
        self, value: str, *, expected_sha256: str | None = None, max_bytes: int = 20 * 1024 * 1024
    ) -> ContentFile:
        suffix = relative_path(value).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
            raise LibraryReadError("Only explicitly referenced supported images and audio can enter a bundle")
        digest = hashlib.sha256()
        size = 0
        with self.open(value) as stream:
            while data := stream.read(1024 * 1024):
                size += len(data)
                if size > max_bytes:
                    raise LibraryReadError("Referenced media exceeds the 20 MiB per-file upload limit")
                digest.update(data)
        if not size:
            raise LibraryReadError("Referenced media is empty")
        sha256 = digest.hexdigest()
        if expected_sha256 is not None and sha256 != expected_sha256.lower():
            raise LibraryReadError("Referenced media SHA-256 does not match its approval record")
        return ContentFile(value, sha256, size, f"{sha256}{suffix}")

    def copy(self, content: ContentFile, destination: Path) -> None:
        """Copy verified bytes, rejecting changes between preview and export."""
        digest = hashlib.sha256()
        size = 0
        with self.open(content.source) as source, destination.open("xb") as target:
            while data := source.read(1024 * 1024):
                size += len(data)
                if size > content.size:
                    raise LibraryReadError("Referenced media changed after preview; rebuild the bundle")
                target.write(data)
                digest.update(data)
        if digest.hexdigest() != content.sha256:
            raise LibraryReadError("Referenced media changed after preview; rebuild the bundle")


def new_output_directory(root: Path, output: Path) -> Path:
    """Never put generated files in the source or overwrite an existing directory."""
    output = output.expanduser().absolute()
    resolved = output.resolve()
    if resolved == root or root in resolved.parents:
        raise LibraryReadError("The output directory must be outside the source library")
    if output.exists() or output.is_symlink():
        raise LibraryReadError("The output directory already exists; choose a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    return output
