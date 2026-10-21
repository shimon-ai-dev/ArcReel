"""Atomic revisioned book storage using the project's existing file-lock primitive."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from lib.book.domain import invalidate_changed_audio, validate_coverage
from lib.book.models import BookDocument
from lib.book.paths import book_media_path
from lib.infra.json_io import atomic_write_bytes, atomic_write_json, load_json
from lib.project.project_activity import record_project_activity
from lib.project.project_manager import ProjectManager


class BookConflictError(ValueError):
    """A newer book revision must be loaded before this edit can be saved."""


class BookStore:
    def __init__(self, projects: ProjectManager, project_name: str) -> None:
        self.projects = projects
        self.project_name = project_name
        self.project_dir = projects.get_project_path(project_name)
        self.path = book_media_path(self.project_dir, "book/book.json")

    def load(self) -> BookDocument:
        """Read and validate the book. Absent books raise FileNotFoundError."""
        book_media_path(self.project_dir, "book/book.json")
        book = BookDocument.model_validate(load_json(self.path))
        validate_coverage(book)
        return book

    def save(self, book: BookDocument, *, expected_revision: int | None = None) -> BookDocument:
        """Write a detached validated copy; optimistic revision defaults to document revision."""
        book_media_path(self.project_dir, "book/book.json")
        with self.projects.file_lock(self.path):
            current = self.load() if self.path.exists() else None
            expected = book.revision if expected_revision is None else expected_revision
            actual = current.revision if current is not None else 0
            if expected != actual:
                raise BookConflictError(f"Book revision changed: expected {expected}, current {actual}")
            return self._write(book, actual + 1)

    def update(self, mutator: Callable[[BookDocument], BookDocument | None]) -> BookDocument:
        """Serialize task completion against edits; mutate the latest document under one lock."""
        book_media_path(self.project_dir, "book/book.json")
        with self.projects.file_lock(self.path):
            current = self.load()
            revision = current.revision
            result = mutator(current)
            return self._write(current if result is None else result, revision + 1)

    def _write(self, book: BookDocument, revision: int) -> BookDocument:
        document = BookDocument.model_validate(book.model_dump(mode="json"))
        validate_coverage(document)
        invalidate_changed_audio(document)
        document.revision = revision
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            previous = self.load()
            if previous.original_text != document.original_text:
                content = previous.original_text.encode("utf-8")
                history = book_media_path(self.project_dir, "book/source_history")
                history.mkdir(exist_ok=True)
                atomic_write_bytes(history / f"{hashlib.sha256(content).hexdigest()}.txt", content)
        atomic_write_json(self.path, document.model_dump(mode="json"))
        record_project_activity(self.project_dir)
        return document
