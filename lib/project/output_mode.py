"""Output format is independent of the existing content and video generation modes."""

from collections.abc import Mapping
from typing import Literal, cast

OutputMode = Literal["video", "audiobook", "illustrated_audiobook"]
OUTPUT_MODES = frozenset({"video", "audiobook", "illustrated_audiobook"})


def project_output_mode(project: object) -> OutputMode:
    if not isinstance(project, Mapping):
        raise ValueError("Project metadata must be an object")
    value = project.get("output_mode", "video")
    if not isinstance(value, str) or value not in OUTPUT_MODES:
        raise ValueError(f"Invalid output_mode: {value!r}")
    return cast(OutputMode, value)


def is_book_project(project: Mapping[str, object]) -> bool:
    return project_output_mode(project) != "video"
