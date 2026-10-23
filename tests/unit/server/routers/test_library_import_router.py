"""The multipart import boundary is preview-first and keeps filesystem work off-loop."""

import hashlib
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from lib.project.project_manager import ProjectManager
from server.error_handlers import register_error_handlers
from server.routers import library_import
from tests.auth_deps import AUTH_DEPENDENCIES, override_auth


def _client(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    (directory / "project.json").write_text(json.dumps({"characters": {}, "scenes": {}, "metadata": {}}))
    monkeypatch.setattr(library_import, "get_project_manager", lambda: manager)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(library_import.router, dependencies=AUTH_DEPENDENCIES)
    override_auth(app)
    return TestClient(app), manager, directory


def _bundle():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), "blue").save(buffer, format="PNG")
    content = buffer.getvalue()
    manifest = {
        "schema_version": 1,
        "library_id": "synthetic",
        "entries": [
            {
                "asset_type": "character",
                "name": "Example",
                "external_id": "person-demo",
                "archive_version": "v001",
                "views": [
                    {
                        "file": "image.png",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "role": "identity",
                        "confirmed": True,
                    }
                ],
            }
        ],
    }
    return json.dumps(manifest), [("files", ("image.png", content, "image/png"))]


class TestLibraryImportRouter:
    def test_preview_then_apply_and_reload_original_asset(self, tmp_path, monkeypatch):
        client, manager, directory = _client(tmp_path, monkeypatch)
        manifest, files = _bundle()
        preview = client.post("/projects/demo/assets/library-import/preview", data={"manifest": manifest}, files=files)
        assert preview.status_code == 200
        assert preview.json()["summary"]["added"] == 1
        assert list(directory.iterdir()) == [directory / "project.json"]
        applied = client.post(
            "/projects/demo/assets/library-import/apply",
            data={"manifest": manifest, "preview_token": preview.json()["preview_token"]},
            files=files,
        )
        assert applied.status_code == 200
        assert applied.json()["applied"] is True
        assert manager.load_project("demo")["characters"]["Example"]["reference_views"][0]["confirmed"] is True

    def test_apply_without_preview_token_is_rejected(self, tmp_path, monkeypatch):
        client, manager, _ = _client(tmp_path, monkeypatch)
        manifest, files = _bundle()
        response = client.post("/projects/demo/assets/library-import/apply", data={"manifest": manifest}, files=files)
        assert response.status_code == 422
        assert manager.load_project("demo")["characters"] == {}

    def test_undeclared_server_path_and_duplicate_uploads_rejected(self, tmp_path, monkeypatch):
        client, manager, _ = _client(tmp_path, monkeypatch)
        manifest, files = _bundle()
        bad = json.loads(manifest)
        bad["server_path"] = "/etc"
        response = client.post(
            "/projects/demo/assets/library-import/preview", data={"manifest": json.dumps(bad)}, files=files
        )
        assert response.status_code == 422
        duplicate = client.post(
            "/projects/demo/assets/library-import/preview", data={"manifest": manifest}, files=files + files
        )
        assert duplicate.status_code == 422
        assert manager.load_project("demo")["characters"] == {}

    def test_missing_project_has_localized_not_found(self, tmp_path, monkeypatch):
        client, _, _ = _client(tmp_path, monkeypatch)
        manifest, files = _bundle()
        response = client.post(
            "/projects/missing/assets/library-import/preview", data={"manifest": manifest}, files=files
        )
        assert response.status_code == 404
        assert "detail" in response.json()
