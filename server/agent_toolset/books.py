"""Book commands share the same source, validation and durable queue as the workspace."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lib.book.models import BookDocument
from lib.book.store import BookConflictError
from lib.infra.async_thread import run_sync_transaction
from server.agent_toolset.declaration import BLOCKED, ToolDeclaration
from server.services.book.service import (
    edit_segment,
    enqueue_export,
    enqueue_keyframe,
    enqueue_speech,
    import_source,
    save_document,
    snapshot,
)
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolProblem, ToolRequest


class BookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["status", "import_source", "save_document", "edit_segment", "generate", "keyframe", "export"] = (
        Field(description="书籍操作：读取状态、导入完整原文、保存编辑、生成语音、生成关键帧或导出")
    )
    text: str | None = Field(default=None, max_length=5_000_000, description="import_source 的完整原始文本，不得摘要")
    title: str = Field(default="", description="导入书籍的标题")
    document: BookDocument | None = Field(default=None, description="status 返回的完整书籍文档；保留 revision 乐观锁")
    segment_id: str | None = Field(default=None, description="修改正文的稳定语音段 ID；其余段缓存与事件 ID 保持")
    segment_ids: list[str] | None = Field(default=None, description="要生成的稳定语音段 ID；省略表示所有缺失或过期段")
    force: bool = Field(default=False, description="即使已有有效音频也重新生成点名段；不自动更换模型或声音")
    keyframe_id: str | None = Field(default=None, description="图声书关键帧 ID")
    format: Literal["wav", "mp3"] = Field(default="wav", description="章节和整本导出的音频格式")

    @model_validator(mode="after")
    def validate_action(self) -> BookRequest:
        if self.action == "import_source" and (self.text is None or not self.text.strip()):
            raise ValueError("import_source requires complete source text")
        if self.action == "save_document" and self.document is None:
            raise ValueError("save_document requires the complete book document")
        if self.action == "keyframe" and not self.keyframe_id:
            raise ValueError("keyframe requires keyframe_id")
        if self.action == "edit_segment" and (not self.segment_id or not self.text):
            raise ValueError("edit_segment requires segment_id and text")
        return self


async def book_project(
    request: ToolRequest[BookRequest], scope: ProjectScope, caller: CallerContext, services: Services
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    try:
        if value.action == "status":
            result = await asyncio.to_thread(snapshot, scope.project_name, projects=services.projects)
        elif value.action == "import_source":
            document = await run_sync_transaction(
                import_source, scope.project_name, value.text or "", value.title, projects=services.projects
            )
            result = {"book": document.model_dump(mode="json")}
        elif value.action == "save_document":
            assert value.document is not None
            document = await run_sync_transaction(
                save_document, scope.project_name, value.document, projects=services.projects
            )
            result = {"book": document.model_dump(mode="json")}
        elif value.action == "edit_segment":
            document = await run_sync_transaction(
                edit_segment, scope.project_name, value.segment_id or "", value.text or "", projects=services.projects
            )
            result = {"book": document.model_dump(mode="json")}
        elif value.action == "generate":
            result = await enqueue_speech(
                scope.project_name,
                value.segment_ids,
                force=value.force,
                projects=services.projects,
                queue=services.queue,
                user_id=caller.user_id,
                source=caller.source,
            )
        elif value.action == "keyframe":
            result = await enqueue_keyframe(
                scope.project_name,
                value.keyframe_id or "",
                projects=services.projects,
                queue=services.queue,
                user_id=caller.user_id,
                source=caller.source,
            )
        else:
            result = await enqueue_export(
                scope.project_name,
                value.format,
                projects=services.projects,
                queue=services.queue,
                user_id=caller.user_id,
                source=caller.source,
            )
        return ToolOutcome(value=result)
    except BookConflictError as exc:
        return ToolOutcome(problem=ToolProblem("book_revision_conflict", str(exc), action="reload_book"))
    except FileNotFoundError as exc:
        return ToolOutcome(problem=ToolProblem("book_not_found", str(exc), action="import_source"))
    except ValueError as exc:
        return ToolOutcome(problem=ToolProblem("invalid_book_request", str(exc), action="fix_input"))


BOOK_PROJECT = ToolDeclaration(
    name="book_project",
    description=(
        "有声书/图声书的统一制作工具。先 action=status 读取完整文档、真实能力、覆盖检查、时间线与完成状态。"
        "import_source 保存全文并保真分章分段，不得摘要、删掉‘他说’或改变原文顺序。save_document 修改说话人、"
        "持久声音配置、独立情绪/风格/停顿/发音映射、音效轨及关键帧锚点，须原样保留当前 revision；不能伪造音频产物。"
        "原文修改用 import_source。配置模型前核对 capabilities；不支持的控制明确报告，不静默丢弃。"
        "generate 按稳定段 ID 入持久队列，缺省只生成缺失或过期段，失败可重试，返回 task_ids 不是生成成功。"
        "keyframe 仅图声书可用，复用已配置图像 Provider（含 ComfyUI），不调用视频模型。"
        "export 生成章节/整本 WAV 或 MP3、manifest 与 HTML 包，正文覆盖和必需媒体缺失会阻止完成。"
        "时间线按实际语音时长与明确静音重算，图片和音效始终绑定语音段。"
        "书籍模式不使用视频任务、视频时长档或视频完成条件；文本覆盖通过不代表听感质量已验收。"
    ),
    request_model=BookRequest,
    migration=BLOCKED,
    domain_key="book",
    handler=book_project,
)

BOOK_TOOLS = (BOOK_PROJECT,)
