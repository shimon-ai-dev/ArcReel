"""Book output reuses original source and chapter truth, not a parallel workspace."""

from pathlib import Path

from lib.book.domain import import_book
from lib.book.store import BookStore
from lib.project.project_manager import ProjectManager
from lib.workflow.workflow_state import WorkflowActionType, WorkflowStateService


def test_book_document_does_not_replace_original_chapter_ledger(tmp_path: Path) -> None:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("book")
    pm.create_project_metadata(
        "book",
        "Book",
        "",
        "narration",
        extras={
            "generation_mode": "storyboard",
            "grid_storyboard": False,
            "output_mode": "audiobook",
        },
    )
    BookStore(pm, "book").save(import_book("你好。"))
    service = WorkflowStateService(pm)
    status = service.get_status("book")
    assert status.project.output_mode == "audiobook"
    assert status.next_action.type == WorkflowActionType.COLLECT_PROJECT_INPUT
    assert status.next_action.args.get("action") != "import_source"
    assert service.get_project_summary("book").episodes == []
    assert service.get_episode_next_steps("book") == []


def test_workflow_refuses_old_export_when_original_episode_changes(tmp_path, monkeypatch):
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("book")
    pm.create_project_metadata(
        "book",
        "Book",
        "",
        "narration",
        extras={
            "generation_mode": "storyboard",
            "grid_storyboard": False,
            "output_mode": "audiobook",
        },
    )
    book = import_book("你好。")
    book.origin = "episodes"
    book.chapters[0].episode = 4
    BookStore(pm, "book").save(book)
    monkeypatch.setattr("lib.workflow.workflow_state.stale_episodes", lambda *_args: [4])

    # A stale original must be caught before any old export-complete proof is read.
    def unexpected_status(*args, **kwargs):
        raise AssertionError("stale projection must not consult old book export")

    monkeypatch.setattr("lib.workflow.workflow_state.book_status", unexpected_status)
    status = WorkflowStateService(pm)._book_status("book", pm.load_project("book"), 4)
    assert not status.artifacts["book"]["complete"]
    assert status.next_action.args == {"tool": "book_project", "action": "sync_episode", "episode": 4}
    assert status.gates["book"]["stale_episodes"] == [4]
