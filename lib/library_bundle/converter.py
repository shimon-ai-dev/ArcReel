"""Convert verified product indexes, not a newly authored user manifest.

Only the documented Chinese product-index tables and archive approval dialects
are interpreted. Unknown pointers remain preview blockers rather than guessed
versions. Markdown and JSON are data; neither is executed or copied wholesale.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from lib.library_bundle.safe_io import ContentFile, LibraryReader, LibraryReadError, new_output_directory
from lib.project.library_manifest import LibraryManifest

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
PERSON_SOURCE = re.compile(
    r"(person-\d+)\s*/\s*(baseline-\d+)\s*/\s*(look-\d+)\s*/\s*(action-\d+)"
    r"\s*/\s*(v\d+)\s*/\s*(character-assets/[^\s`<>]+)"
)
VOICE_SOURCE = re.compile(
    r"(person-\d+)\s*/\s*(voice-\d+)\s*/\s*(v\d+)\s*/\s*((?:voice-assets/)?(?:audio|transcripts)/[^\s`<>]+)"
)
SCENE_SOURCE = re.compile(r"(?:^|/)scenes/(scene-[A-Za-z0-9_-]+)/(state-\d+)-(v\d+)/scene-assets/")
HASH = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class Issue:
    code: str
    source: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class IndexRow:
    source: str
    line: int
    cells: dict[str, str]


@dataclass
class BundlePreview:
    library_id: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    content: dict[str, ContentFile] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.entries) and not self.blockers

    def manifest(self) -> dict[str, Any]:
        return {"schema_version": 1, "library_id": self.library_id, "entries": self.entries}

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "library_id": self.library_id,
            "ready": self.ready,
            "entry_count": len(self.entries),
            "file_count": len(self.content),
            "total_bytes": sum(item.size for item in self.content.values()),
            "entries": self.entries,
            "blockers": [asdict(issue) for issue in self.blockers],
            "warnings": [asdict(issue) for issue in self.warnings],
            "source_policy": "read-only; only selected index references; no source candidates or unrelated files",
        }


def markdown_rows(text: str, source: str) -> list[IndexRow]:
    """Read a bounded table dialect without treating Markdown as instructions."""
    rows: list[IndexRow] = []
    header: list[str] | None = None
    fenced = False
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
        if fenced or not line.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if header is None:
            header = cells
            continue
        if len(cells) != len(header):
            raise LibraryReadError(f"Unsupported Markdown table at line {line_number}")
        rows.append(IndexRow(source, line_number, dict(zip(header, cells, strict=True))))
    return rows


def _plain(value: str) -> str:
    return LINK.sub(lambda match: match.group(1), value).replace("`", "").replace("**", "").strip()


def _has_id(text: str, identifier: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(identifier) + r"(?![A-Za-z0-9])", text) is not None


def _local_link(reader: LibraryReader, source: str, link: str) -> str:
    value = unquote(link.strip().strip("<>"))
    if ":" in value or "\\" in value or "\x00" in value or value.startswith("/") or "#" in value or "?" in value:
        raise LibraryReadError("Index links must reference local files within the selected root")
    candidate = reader.root / PurePosixPath(source).parent / value
    # Existing Markdown indexes legitimately use ../ to reach their archive.
    lexical = Path(candidate.absolute())
    normalized = Path(os.path.normpath(lexical))
    try:
        relative = normalized.relative_to(reader.root).as_posix()
    except ValueError as exc:
        raise LibraryReadError("An index link leaves the selected library root") from exc
    reader.resolve(relative)
    return relative


def _json(reader: LibraryReader, path: str) -> dict[str, Any]:
    try:
        value = json.loads(reader.read_text(path))
    except json.JSONDecodeError as exc:
        raise LibraryReadError("An approval file is not valid JSON") from exc
    if not isinstance(value, dict):
        raise LibraryReadError("An approval record must be a JSON object")
    return value


def _status(value: Any) -> str:
    if isinstance(value, str) and value in {"approved", "rejected", "pending"}:
        return value
    return "pending"


def _hash(value: Any) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise LibraryReadError("The selected source has no valid explicit SHA-256")
    return value.lower()


def _records(approval: dict[str, Any]) -> list[dict[str, Any]]:
    records = approval.get("files")
    if not isinstance(records, list) or not records or not all(isinstance(item, dict) for item in records):
        raise LibraryReadError("Unsupported approval files dialect; an explicit files array is required")
    return records


def _confirmation(value: str) -> tuple[bool, bool]:
    plain = _plain(value)
    confirmed = any(term in plain for term in ("用户确认", "整体确认", "单文件确认"))
    if any(term in plain for term in ("未确认", "待确认", "未裁定")):
        confirmed = False
    frozen = any(term in plain for term in ("已冻结", "单文件冻结")) and "未冻结" not in plain
    return confirmed, frozen


def _view_labels(slot: str, archive: str, asset_type: str, action: str | None = None) -> dict[str, str]:
    role = "space" if asset_type == "scene" else "identity" if "/identity/" in archive else "look"
    if action is not None and action != "action-000":
        role = "action"
    view = next(
        (target for token, target in (("正面", "front"), ("背面", "back"), ("侧面", "side")) if token in slot),
        "unspecified",
    )
    framing = next(
        (
            target
            for token, target in (("大头", "headshot"), ("半身", "half_body"), ("全身", "full_body"))
            if token in slot
        ),
        "unspecified",
    )
    # Unmapped labels stay distinct rather than collapsing unrelated source views.
    if view == "unspecified" and slot:
        view = slot[:80]
    return {"role": role, "view": view, "framing": framing}


class ExistingLibraryConverter:
    def __init__(self, root: Path, *, library_id: str | None = None, entries: set[str] | None = None):
        self.reader = LibraryReader(root)
        self.preview = BundlePreview(library_id or self.reader.root.name)
        self.groups: dict[tuple[str, ...], dict[str, Any]] = {}
        self.version_keys: dict[tuple[str, ...], str] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.selected_entries = entries

    def approval(self, path: str) -> dict[str, Any]:
        if path not in self.approvals:
            self.approvals[path] = _json(self.reader, path)
        return self.approvals[path]

    def check_registry(self, person: str, parts: tuple[str, ...], base: str, status: str) -> None:
        path = f"characters/{person}/character.md"
        if status != "approved" or not (self.reader.root / path).exists():
            return
        rows = markdown_rows(self.reader.read_text(path), path)
        for row in rows:
            if "最后已批准版本" not in row.cells:
                continue
            label = row.cells.get("包", row.cells.get("声音设定", ""))
            if not all(_has_id(label, part) for part in parts):
                continue
            pointers = LINK.findall(row.cells["最后已批准版本"])
            if len(pointers) != 1:
                raise LibraryReadError("Matching registry row has no unambiguous last-approved pointer")
            # The version pointer is checked even if the descriptive pack.md is
            # absent; approval records and media are verified separately.
            link = unquote(pointers[0][1])
            if ":" in link or "\\" in link or link.startswith("/"):
                raise LibraryReadError("Registry approved pointers must be local relative links")
            expected = Path(os.path.normpath(self.reader.root / PurePosixPath(path).parent / link))
            selected = self.reader.root / base / "pack.md"
            if expected != selected:
                raise LibraryReadError("Product selection conflicts with the registry last-approved version")

    def content(self, source: str, digest: str, product: str) -> ContentFile:
        archive = self.reader.resolve(source)
        product_file = self.reader.resolve(product)
        actual = self.reader.inspect(source, expected_sha256=digest)
        if product_file != archive:
            # Copies are supported only if their bytes match the exact archive record.
            self.reader.inspect(product, expected_sha256=digest)
        existing = self.preview.content.get(actual.sha256)
        if existing is not None:
            return existing
        self.preview.content[actual.sha256] = actual
        return actual

    def image_dimensions(self, source: str, record: dict[str, Any] | None = None) -> tuple[int, int]:
        try:
            with self.reader.open(source) as stream, Image.open(stream) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 40_000_000:
                    raise LibraryReadError("Images must be PNG/JPEG/WebP and at most 40 million pixels")
                dimensions = image.size
                image.load()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
            raise LibraryReadError("Referenced image is unsupported or damaged") from exc
        if record is not None:
            for key, value in zip(("width", "height"), dimensions, strict=True):
                if key in record and (type(record[key]) is not int or record[key] != value):
                    raise LibraryReadError("Image dimensions disagree with the approval record")
        return dimensions

    def verify_audio(self, source: str) -> None:
        try:
            with self.reader.open(source) as stream, wave.open(stream, "rb") as audio:
                expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                if audio.getnchannels() not in (1, 2) or expected <= 0 or expected > 20 * 1024 * 1024:
                    raise LibraryReadError("Voice reference must contain nonempty mono/stereo PCM WAV")
                if len(audio.readframes(audio.getnframes())) != expected:
                    raise LibraryReadError("Voice reference audio is truncated")
        except (wave.Error, EOFError, OSError) as exc:
            raise LibraryReadError("Voice reference must contain valid PCM WAV") from exc

    def product(self, row: IndexRow) -> str:
        cell = next((row.cells[key] for key in ("文件", "成品文件") if key in row.cells), "")
        links = LINK.findall(cell)
        if len(links) == 1:
            return _local_link(self.reader, row.source, links[0][1])
        value = _plain(cell)
        if not value or len(links) > 1:
            raise LibraryReadError("The product row needs one explicit file pointer")
        if "/" not in value:
            category = "声音资产" if PurePosixPath(value).suffix.lower() in {".wav", ".txt"} else "基础视图"
            if "/场景/" in row.source:
                category = "空间视图"
            value = f"{category}/{value}"
        return _local_link(self.reader, row.source, value)

    def group(self, key: tuple[str, ...], entry: dict[str, Any], version: str) -> dict[str, Any]:
        if key in self.version_keys and self.version_keys[key] != version:
            raise LibraryReadError("Multiple published versions remain selected; resolve the current recommendation")
        self.version_keys[key] = version
        if key not in self.groups:
            self.groups[key] = entry
        return self.groups[key]

    def image(self, row: IndexRow, source_cell: str, product: str) -> None:
        match = PERSON_SOURCE.search(_plain(source_cell))
        if match is None:
            raise LibraryReadError(
                "Unsupported image source pointer; exact person/baseline/look/action/version/file is required"
            )
        person, baseline, look, action, version, filename = match.groups()
        base = f"characters/{person}/packs/{baseline}_{look}_{action}/{version}"
        source = f"{base}/{filename}"
        approval_path = f"{base}/approval.json"
        approval = self.approval(approval_path)
        for key, expected in {
            "asset_id": person,
            "baseline": baseline,
            "look": look,
            "action": action,
            "archive_version": version,
        }.items():
            if approval.get(key) != expected:
                raise LibraryReadError(f"Image approval {key} conflicts with the index source pointer")
        files = [item for item in _records(approval) if item.get("archive") == filename]
        if len(files) != 1:
            raise LibraryReadError("Image source must match exactly one approval file record")
        record = files[0]
        if record.get("product") != product:
            raise LibraryReadError("Image product pointer conflicts with its approval record")
        product_version = approval.get("product_version")
        self.check_registry(person, (baseline, look, action), base, _status(approval.get("status")))
        self.check_product_version(row, product_version)
        content = self.content(source, _hash(record.get("sha256")), product)
        width, height = self.image_dimensions(source, record)
        slot = str(record.get("slot", ""))
        coverage = approval.get("coverage", {})
        entry = {
            "asset_type": "character",
            "external_id": person,
            "name": f"{person} {baseline} {look} {action}",
            "baseline": baseline,
            "look": look,
            "action": action,
            "archive_version": version,
            "product_version": product_version,
            "status": _status(approval.get("status")),
            "frozen": approval.get("frozen") is True,
            "views": [],
            "index_path": row.source,
            "approval_path": approval_path,
            "coverage": [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in coverage.items()]
            if isinstance(coverage, dict)
            else [],
        }
        group = self.group(("character", person, baseline, look, action), entry, f"{version}/{product_version}")
        view = {
            "file": content.filename,
            "sha256": content.sha256,
            "archive_path": source,
            "product_path": product,
            "index_path": row.source,
            "approval_path": approval_path,
            "slot": slot,
            "frozen": record.get("frozen") is True,
            "confirmed": record.get("user_confirmed") is True,
            "width": width,
            "height": height,
            **_view_labels(slot, source, "character", action),
        }
        self.add_view(group, view)

    def check_product_version(self, row: IndexRow, value: Any) -> None:
        cell = next((row.cells[key] for key in ("成品V", "成品版本") if key in row.cells), None)
        if cell is not None and _plain(cell) != value:
            raise LibraryReadError("Product and archive version axes conflict; they are not interchangeable")

    def add_view(self, entry: dict[str, Any], view: dict[str, Any]) -> None:
        views = entry["views"]
        exact = [item for item in views if item["archive_path"] == view["archive_path"]]
        if exact:
            if exact[0]["sha256"] != view["sha256"]:
                raise LibraryReadError("Duplicate source references disagree about the content hash")
            self.preview.warnings.append(
                Issue(
                    "duplicate_reference",
                    view["index_path"],
                    "The same archive object is displayed in more than one product row; original source identity was retained",
                )
            )
            return
        views.append(view)

    def voice_baseline(self, person: str, voice: str) -> str | None:
        path = f"characters/{person}/character.md"
        if not (self.reader.root / path).exists():
            return None
        rows = markdown_rows(self.reader.read_text(path), path)
        values = {
            _plain(row.cells["适用 baseline"])
            for row in rows
            if "适用 baseline" in row.cells and _has_id(" ".join(row.cells.values()), voice)
        }
        if len(values) == 1:
            value = next(iter(values))
            if re.fullmatch(r"baseline-\d+", value):
                return value
        return None

    def transcript(self, base: str, approval: dict[str, Any], clip: str) -> str:
        records = [
            item
            for item in _records(approval)
            if item.get("role") == "transcript"
            and PurePosixPath(str(item.get("path", ""))).stem == PurePosixPath(clip).stem
        ]
        if len(records) > 1:
            raise LibraryReadError("Voice transcript selection is ambiguous")
        if not records:
            return ""
        record = records[0]
        source = f"{base}/{record['path']}"
        with self.reader.open(source) as stream:
            data = stream.read(400_001)
        if len(data) > 400_000 or hashlib.sha256(data).hexdigest() != _hash(record.get("sha256")):
            raise LibraryReadError("Voice transcript is too large or its SHA-256 mismatches")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LibraryReadError("Voice transcript must use UTF-8") from exc

    def voice(self, row: IndexRow, source_cell: str, product: str) -> None:
        match = VOICE_SOURCE.search(_plain(source_cell))
        if match is None:
            raise LibraryReadError("Unsupported voice source pointer; exact person/voice/version/file is required")
        person, voice_id, version, filename = match.groups()
        if not filename.startswith("voice-assets/"):
            filename = f"voice-assets/{filename}"
        base = f"characters/{person}/voices/{voice_id}/{version}"
        source = f"{base}/{filename}"
        approval_path = f"{base}/approval.json"
        approval = self.approval(approval_path)
        self.check_registry(person, (voice_id,), base, _status(approval.get("status")))
        for key, value in {"person": person, "voice": voice_id, "version": version}.items():
            if approval.get(key) != value:
                raise LibraryReadError(f"Voice approval {key} conflicts with the index pointer")
        files = [item for item in _records(approval) if item.get("path") == filename]
        if len(files) != 1:
            raise LibraryReadError("Voice pointer must match exactly one approval file record")
        record = files[0]
        if record.get("role") == "transcript":
            # Transcripts are embedded only alongside their selected audio clip.
            return
        if PurePosixPath(filename).suffix.lower() != ".wav":
            raise LibraryReadError("Portable voice import currently supports PCM WAV only")
        self.check_product_version(row, approval.get("product_version"))
        content = self.content(source, _hash(record.get("sha256")), product)
        self.verify_audio(source)
        baseline = self.voice_baseline(person, voice_id)
        voice = {
            "voice_id": voice_id,
            "version": version,
            "baseline": baseline,
            "baseline_status": "confirmed" if baseline else "pending",
            "status": _status(approval.get("status")),
            **{
                key: approval.get(key) is True
                for key in ("technical_pass", "agent_listened", "model_adapted", "clone_tested")
            },
            "clips": [],
        }
        entry = {
            "asset_type": "character",
            "external_id": person,
            "name": f"{person} {voice_id}",
            "baseline": baseline,
            "archive_version": version,
            "product_version": approval.get("product_version"),
            "status": _status(approval.get("status")),
            "frozen": approval.get("frozen") is True,
            "views": [],
            "voice": voice,
            "index_path": row.source,
            "approval_path": approval_path,
        }
        group = self.group(("voice", person, voice_id), entry, f"{version}/{approval.get('product_version')}")
        confirmed, frozen = _confirmation(row.cells.get("确认范围", ""))
        clip = {
            "file": content.filename,
            "sha256": content.sha256,
            "archive_path": source,
            "product_path": product,
            "index_path": row.source,
            "approval_path": approval_path,
            "slot": str(record.get("role", "")),
            "frozen": record.get("frozen") is True or frozen,
            "confirmed": record.get("user_confirmed") is True or confirmed,
            "transcript": self.transcript(base, approval, filename),
        }
        if not any(item["file"] == clip["file"] for item in group["voice"]["clips"]):
            group["voice"]["clips"].append(clip)
        if record.get("role") == "main_reference":
            selected = group["voice"].get("selected_clip")
            if selected is not None and selected != content.filename:
                raise LibraryReadError("Voice approval contains multiple main references")
            group["voice"]["selected_clip"] = content.filename

    def scene_map(self, path: str, source: str) -> tuple[str, bool, bool]:
        text = self.reader.read_text(path)
        matching: list[tuple[str, bool, bool]] = []
        for section in re.split(r"(?m)^##\s+", text)[1:]:
            source_links = [link for _, link in LINK.findall(section) if link.startswith(("views/", "./views/"))]
            for link in source_links:
                candidate = _local_link(self.reader, path, link)
                if self.reader.resolve(candidate) != self.reader.resolve(source):
                    continue
                hashes = set(re.findall(r"SHA-256[^a-fA-F0-9]*([a-fA-F0-9]{64})", section))
                if len(hashes) != 1:
                    raise LibraryReadError("Scene asset-map section needs one unambiguous SHA-256")
                confirmed, frozen = _confirmation(section)
                matching.append((_hash(next(iter(hashes))), confirmed, frozen))
        if len(matching) != 1:
            raise LibraryReadError("Current scene source does not match exactly one asset-map section")
        return matching[0]

    def scene(self, row: IndexRow, source_cell: str, product: str) -> None:
        sources = [_local_link(self.reader, row.source, link) for _, link in LINK.findall(source_cell)]
        images = [source for source in sources if PurePosixPath(source).suffix.lower() in IMAGE_SUFFIXES]
        maps = [source for source in sources if PurePosixPath(source).name == "asset-map.md"]
        if len(images) == 1:
            source = images[0]
        elif not images and len(maps) == 1:
            # The live product symlink, not an obsolete asset-map publication link,
            # identifies the archive object represented by this product row.
            source = self.reader.relative(self.reader.resolve(product))
        else:
            raise LibraryReadError("Scene source needs one exact image link or one map plus an in-root product symlink")
        match = SCENE_SOURCE.search(source)
        if match is None:
            raise LibraryReadError("Unsupported scene state/version source layout")
        scene_id, state, version = match.groups()
        pack_path = f"scenes/{scene_id}/{state}-{version}/pack.md"
        pack_text = self.reader.read_text(pack_path)
        pack_state = re.search(r"包状态\s*[：:]\s*`?([A-Za-z_-]+)", pack_text)
        canonical_map = f"scenes/{scene_id}/{state}-{version}/scene-assets/asset-map.md"
        if not maps and (self.reader.root / canonical_map).exists():
            maps = [canonical_map]
        confirmed, frozen = _confirmation(row.cells.get("确认范围", ""))
        digest_text = _plain(row.cells.get("SHA-256", ""))
        digest = _hash(digest_text) if digest_text else None
        if maps:
            if len(maps) != 1:
                raise LibraryReadError("Scene source has ambiguous asset-map pointers")
            map_hash, map_confirmed, map_frozen = self.scene_map(maps[0], source)
            if digest is not None and digest != map_hash:
                raise LibraryReadError("Scene index and asset-map hashes disagree")
            digest = map_hash
            confirmed = confirmed or map_confirmed
            frozen = frozen or map_frozen
        if digest is None:
            raise LibraryReadError("Scene source needs a SHA-256 from its index or exact asset-map section")
        content = self.content(source, digest, product)
        width, height = self.image_dimensions(source)
        product_version = next(iter(re.findall(r"(?:^|_)(V\d+)(?:\.|_)", product)), None)
        entry = {
            "asset_type": "scene",
            "external_id": scene_id,
            "name": f"{scene_id} {state}",
            "state": state,
            "archive_version": version,
            "product_version": product_version,
            "status": "pending",
            "frozen": False,
            "views": [],
            "index_path": row.source,
            "approval_path": pack_path,
            "coverage": [f"source_pack_status: {pack_state.group(1)}"] if pack_state else [],
        }
        group = self.group(("scene", scene_id, state), entry, f"{version}/{product_version}")
        slot = PurePosixPath(product).stem
        self.add_view(
            group,
            {
                "file": content.filename,
                "sha256": content.sha256,
                "archive_path": source,
                "product_path": product,
                "index_path": row.source,
                "approval_path": maps[0] if maps else pack_path,
                "slot": slot,
                "confirmed": confirmed,
                "frozen": frozen,
                "width": width,
                "height": height,
                **_view_labels(slot, source, "scene"),
            },
        )

    def process_index(self, source: str) -> None:
        text = self.reader.read_text(source)
        rows = markdown_rows(text, source)
        selected = [row for row in rows if any(key in row.cells for key in ("文件", "成品文件"))]
        if not selected:
            raise LibraryReadError("Unsupported product index dialect: no recognized product-file table")
        recommendations: dict[str, set[str]] = {}
        for line in text.splitlines():
            if "当前推荐" in line:
                for category, version in re.findall(r"(基础视图|[^*、：]+?)\s+(V\d+)", line):
                    recommendations.setdefault(category.strip(), set()).add(version)
        if any(len(versions) > 1 for versions in recommendations.values()):
            raise LibraryReadError(
                "Current product recommendation is ambiguous; no latest-version inference is allowed"
            )
        for row in selected:
            try:
                product = self.product(row)
                source_cell = next(
                    (row.cells[key] for key in ("精确来源版本", "精确来源包与文件", "来源与记录") if key in row.cells),
                    "",
                )
                if not source_cell:
                    raise LibraryReadError("Product index lacks an exact source pointer")
                category = _plain(row.cells.get("分类", ""))
                recommendation = recommendations.get(category)
                if recommendation is None and "/基础视图/" in product:
                    recommendation = recommendations.get("基础视图")
                if recommendation is None and "/声音资产/" in product:
                    matches = [
                        versions
                        for label, versions in recommendations.items()
                        if PurePosixPath(product).name.startswith(label)
                    ]
                    if len(matches) == 1:
                        recommendation = matches[0]
                if recommendation:
                    row_version = _plain(row.cells.get("成品V", row.cells.get("成品版本", "")))
                    if row_version not in recommendation:
                        self.preview.warnings.append(
                            Issue("not_current", source, "Historical product row was not selected", row.line)
                        )
                        continue
                if "/场景/" in source:
                    self.scene(row, source_cell, product)
                elif "voice-assets/" in source_cell or PurePosixPath(product).suffix.lower() in {".wav", ".txt"}:
                    self.voice(row, source_cell, product)
                elif PurePosixPath(product).suffix.lower() in IMAGE_SUFFIXES:
                    self.image(row, source_cell, product)
                else:
                    raise LibraryReadError("Unsupported media row; no unrelated files are imported")
            except LibraryReadError as exc:
                self.preview.blockers.append(Issue("unresolved_product", source, str(exc), row.line))

    def scan(self) -> BundlePreview:
        product_root = self.reader.root / "成品"
        if not product_root.is_dir():
            self.preview.blockers.append(
                Issue(
                    "library_root",
                    "成品",
                    "Select the complete library root containing 成品 plus characters/scenes archives",
                )
            )
            return self.preview
        found = False
        found_entries: set[str] = set()
        for category, prefix in (("人物", "person-"), ("场景", "scene-")):
            relative_category = f"成品/{category}"
            folder = product_root / category
            if not folder.exists():
                continue
            try:
                self.reader.resolve(relative_category)
                children = sorted(folder.iterdir(), key=lambda path: path.name)
                if len(children) > 2000:
                    raise LibraryReadError("Product catalog exceeds the supported entry limit")
                for child in children:
                    if not child.name.startswith(prefix):
                        continue
                    if self.selected_entries is not None and child.name not in self.selected_entries:
                        continue
                    source = f"{relative_category}/{child.name}/索引.md"
                    if not (self.reader.root / source).exists():
                        continue
                    found = True
                    found_entries.add(child.name)
                    try:
                        self.process_index(source)
                    except LibraryReadError as exc:
                        self.preview.blockers.append(Issue("unresolved_index", source, str(exc)))
            except (LibraryReadError, OSError) as exc:
                self.preview.blockers.append(Issue("unreadable_products", relative_category, str(exc)))
        self.preview.entries = list(self.groups.values())
        if self.selected_entries is not None:
            for name in sorted(self.selected_entries - found_entries):
                self.preview.blockers.append(
                    Issue("missing_entry", name, "Selected product entry has no supported index under this root")
                )
        if (
            len(self.preview.content) > 200
            or sum(item.size for item in self.preview.content.values()) > 128 * 1024 * 1024
        ):
            self.preview.blockers.append(
                Issue(
                    "bundle_size",
                    "bundle",
                    "Select a smaller library scope: at most 200 media files and 128 MiB per bundle",
                )
            )
        if not found or not self.preview.entries:
            self.preview.blockers.append(
                Issue(
                    "no_supported_entries",
                    "成品",
                    "No supported product entries were resolved; provide a redacted index example before extending the parser",
                )
            )
        if self.preview.entries:
            try:
                LibraryManifest.model_validate(self.preview.manifest())
            except ValidationError as exc:
                for error in exc.errors(include_url=False, include_input=False):
                    location = ".".join(str(part) for part in error["loc"])
                    self.preview.blockers.append(Issue("manifest_contract", location, error["msg"]))
        return self.preview


def prepare_library(
    root: Path, *, library_id: str | None = None, output: Path | None = None, entries: set[str] | None = None
) -> BundlePreview:
    """Preview or export selected media; never upload, apply, or change the source."""
    converter = ExistingLibraryConverter(root, library_id=library_id, entries=entries)
    preview = converter.scan()
    if output is None:
        return preview
    destination = new_output_directory(converter.reader.root, output)
    if preview.ready:
        try:
            for content in preview.content.values():
                converter.reader.copy(content, destination / content.filename)
        except LibraryReadError as exc:
            preview.blockers.append(Issue("source_changed", "bundle", str(exc)))
            # This directory was created exclusively by this call, never a user's existing output.
            for content in preview.content.values():
                (destination / content.filename).unlink(missing_ok=True)
        if preview.ready:
            (destination / "library-manifest.json").write_text(
                json.dumps(preview.manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    (destination / "preview.json").write_text(
        json.dumps(preview.report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return preview
