"""Project-confined book paths that reject symlink and junction aliases."""

from pathlib import Path

from lib.book.models import validate_resource_path
from lib.infra.path_safety import safe_join


def book_media_path(project_dir: Path, relative: str, *, require_file: bool = False) -> Path:
    relative = validate_resource_path(relative)
    root = project_dir.resolve()
    current = project_dir
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Book paths cannot contain symbolic links or junctions")
    return safe_join(root, relative, require_file=require_file)
