"""Agent book commands use scoped storage and never enter video planning."""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.book.domain import all_segments
from lib.book.models import BookDocument
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.infra.json_io import atomic_write_json
from lib.project.project_manager import ProjectManager
from lib.project.project_schema import CURRENT_PROJECT_SCHEMA_VERSION
from lib.workflow.workflow_plan import build_workflow_plan
from lib.workflow.workflow_state import WorkflowStateService
from server.agent_toolset.books import BookRequest, book_project
from server.agent_toolset.orientation import get_video_capabilities
from server.services.project.workflow_planner import WorkflowPlanner
from server.tool_runtime import CallerContext, NoArguments, ProjectScope, Services, ToolRequest


@pytest.fixture
def book_services(tmp_path: Path) -> Services:
    manager = ProjectManager(tmp_path / "projects")
    directory = manager.projects_dir / "book-demo"
    directory.mkdir(parents=True)
    atomic_write_json(
        directory / "project.json",
        {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "output_mode": "audiobook",
            "content_mode": "narration",
            "generation_mode": "storyboard",
            "title": "Novel",
            "episodes": [],
            "characters": {},
            "scenes": {},
            "props": {},
        },
    )
    return Services(
        projects=manager, workflow_planner=WorkflowPlanner(manager), capabilities=ConfigResolver(async_session_factory)
    )


async def test_agent_import_edit_and_coverage_use_scoped_project(book_services: Services) -> None:
    scope = ProjectScope("book-demo", book_services.projects.data_root)
    caller = CallerContext("default", "mcp")
    created = await book_project(
        ToolRequest(BookRequest(action="import_source", text="小明说：“你好！”")), scope, caller, book_services
    )
    assert created.problem is None
    assert created.value is not None
    book = BookDocument.model_validate(created.value["book"])
    segment_id = all_segments(book)[0].id
    edited = await book_project(
        ToolRequest(BookRequest(action="edit_segment", segment_id=segment_id, text="小明轻声说：")),
        scope,
        caller,
        book_services,
    )
    assert edited.value is not None
    assert edited.value["book"]["normalized_text"] == "小明轻声说：“你好！”"
    state = await book_project(ToolRequest(BookRequest(action="status")), scope, caller, book_services)
    assert state.value is not None
    assert state.value["status"]["coverage_valid"] is True
    assert state.value["status"]["complete"] is False


async def test_agent_rejects_stale_document_and_source_rewrite(book_services: Services) -> None:
    scope = ProjectScope("book-demo", book_services.projects.data_root)
    caller = CallerContext("default", "mcp")
    created = await book_project(
        ToolRequest(BookRequest(action="import_source", text="原文。")), scope, caller, book_services
    )
    assert created.value is not None
    document = BookDocument.model_validate(created.value["book"])
    saved = await book_project(
        ToolRequest(BookRequest(action="save_document", document=document)), scope, caller, book_services
    )
    assert saved.problem is None
    stale = await book_project(
        ToolRequest(BookRequest(action="save_document", document=document)), scope, caller, book_services
    )
    assert stale.problem is not None
    assert stale.problem.code == "book_revision_conflict"
    document.original_text = "改写。"
    rejected = await book_project(
        ToolRequest(BookRequest(action="save_document", document=document)), scope, caller, book_services
    )
    assert rejected.problem is not None
    assert rejected.problem.code == "invalid_book_request"


async def test_book_orientation_does_not_require_video_provider(book_services: Services) -> None:
    scope = ProjectScope("book-demo", book_services.projects.data_root)
    denied = await get_video_capabilities(
        ToolRequest(NoArguments()), scope, CallerContext("default", "mcp"), book_services
    )
    assert denied.problem is not None
    assert denied.problem.code == "book_has_no_video_workflow"
    state = await asyncio.to_thread(WorkflowStateService(book_services.projects).get_status, "book-demo")
    plan = build_workflow_plan(state)
    assert [step.id for step in plan.steps] == ["book"]
    assert plan.next_action.args == {"tool": "book_project", "action": "import_source"}
    assert not any("video" in step.id for step in plan.steps)


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "import_source"},
        {"action": "save_document"},
        {"action": "keyframe"},
        {"action": "edit_segment", "segment_id": "missing"},
    ],
)
def test_book_request_requires_action_inputs(payload: dict) -> None:
    with pytest.raises(ValidationError):
        BookRequest.model_validate(payload)
