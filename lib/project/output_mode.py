"""Output format is independent of the existing content and video generation modes."""

from collections.abc import Mapping
from typing import Literal, cast

OutputMode = Literal["video", "audiobook", "illustrated_audiobook"]
OUTPUT_MODES = frozenset({"video", "audiobook", "illustrated_audiobook"})


def project_output_mode(project: Mapping[str, object]) -> OutputMode:
    value = project.get("output_mode", "video")
    if value not in OUTPUT_MODES:
        raise ValueError(f"Invalid output_mode: {value!r}")
    return cast(OutputMode, value)


def is_book_project(project: Mapping[str, object]) -> bool:
    return project_output_mode(project) != "video"
