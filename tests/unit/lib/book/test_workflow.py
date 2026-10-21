"""Book-mode status does not require video artifacts or video capabilities."""

from pathlib import Path

from lib.book.domain import all_segments, book_fingerprint, import_book, segment_fingerprint
from lib.book.models import AudioVersion
from lib.book.store import BookStore
from lib.infra.content_digest import sha256_file
from lib.infra.json_io import atomic_write_json
from lib.project.project_manager import ProjectManager
from lib.project.project_schema import CURRENT_PROJECT_SCHEMA_VERSION
from lib.workflow.workflow_state import WorkflowActionType, WorkflowStateService, workflow_finished


def test_book_status_and_summary_are_audio_first_and_export_gated(tmp_path: Path) -> None:
    projects = ProjectManager(tmp_path)
    project_dir = projects.projects_dir / "book"
    project_dir.mkdir(parents=True)
    atomic_write_json(
        project_dir / "project.json",
        {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "output_mode": "audiobook",
            "content_mode": "narration",
            "generation_mode": "storyboard",
            "grid_storyboard": False,
            "episodes": [],
            "characters": {},
            "scenes": {},
            "props": {},
        },
    )
    service = WorkflowStateService(projects)
    absent = service.get_status("book")
    assert absent.next_action.args == {"tool": "book_project", "action": "import_source"}
    book = import_book("你好。")
    segment = all_segments(book)[0]
    segment.audio_versions = [
        AudioVersion(id="v1", path="speech.wav", duration_seconds=1, fingerprint=segment_fingerprint(book, segment))
    ]
    segment.selected_audio_version = "v1"
    segment.status = "succeeded"
    (project_dir / "speech.wav").write_bytes(b"speech")
    store = BookStore(projects, "book")
    book = store.save(book)
    status = service.get_status("book")
    assert status.project.output_mode == "audiobook"
    assert status.next_action.args["action"] == "export"
    assert not workflow_finished(status)
    summary = service.get_project_summary("book")
    assert summary.episodes[0].videos.total == 0
    assert summary.episodes_summary.completed == 0
    assert service.get_episode_next_steps("book")[0].next_action.args["tool"] == "book_project"
    atomic_write_json(
        project_dir / "book/export.json",
        {
            "fingerprint": book_fingerprint(book),
            "files": ["speech.wav"],
            "illustrated": False,
            "resource_digests": {"speech.wav": sha256_file(project_dir / "speech.wav")},
        },
    )
    complete = service.get_status("book")
    assert complete.next_action.type == WorkflowActionType.NONE
    assert workflow_finished(complete)
    assert service.get_project_summary("book").episodes_summary.completed == 1
