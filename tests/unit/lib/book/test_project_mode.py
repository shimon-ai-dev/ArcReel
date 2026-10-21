"""Output mode is fixed independently of the existing content/generation axes."""

import pytest

from lib.infra.json_io import atomic_write_json
from lib.project.output_mode import project_output_mode
from lib.project.project_manager import ProjectManager
from lib.project.project_schema import CURRENT_PROJECT_SCHEMA_VERSION


@pytest.fixture
def manager(tmp_path):
    projects = ProjectManager(tmp_path / "projects")
    directory = projects.projects_dir / "novel"
    directory.mkdir(parents=True)
    atomic_write_json(
        directory / "project.json",
        {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "output_mode": "audiobook",
            "content_mode": "narration",
            "generation_mode": "storyboard",
            "episodes": [],
            "characters": {},
            "scenes": {},
            "props": {},
        },
    )
    return projects


@pytest.mark.parametrize("mode", ["illustrated_audiobook", "video"])
def test_save_rejects_output_mode_change_without_writing(manager, mode):
    project = manager.load_project("novel")
    project["output_mode"] = mode
    with pytest.raises(ValueError, match="fixed"):
        manager.save_project("novel", project)
    assert manager.load_project("novel")["output_mode"] == "audiobook"


def test_update_rejects_output_mode_change_atomically(manager):
    def mutate(project):
        project["output_mode"] = "illustrated_audiobook"
        project["title"] = "Must not persist"

    with pytest.raises(ValueError, match="fixed"):
        manager.update_project("novel", mutate)
    project = manager.load_project("novel")
    assert project["output_mode"] == "audiobook"
    assert project.get("title") != "Must not persist"


def test_same_mode_save_and_update_preserve_independent_axes(manager):
    project = manager.load_project("novel")
    project["title"] = "New title"
    manager.save_project("novel", project)
    changed = manager.update_project("novel", lambda current: current.update(title="Edited"))
    assert changed["output_mode"] == "audiobook"
    assert changed["content_mode"] == "narration"
    assert changed["generation_mode"] == "storyboard"
    assert changed["title"] == "Edited"


def test_missing_output_mode_defaults_without_mutating_legacy_mapping():
    legacy = {"content_mode": "drama", "generation_mode": "storyboard"}
    assert project_output_mode(legacy) == "video"
    assert "output_mode" not in legacy
