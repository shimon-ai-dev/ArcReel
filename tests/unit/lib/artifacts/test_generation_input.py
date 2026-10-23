"""生成输入 interface：分镜图与宫格的装配序、缺口定性与一次报全、依据与冻结。

观测走执行器的 adapter，配内存清单 adapter；参考图是临时目录里的真实小图。
"""

from __future__ import annotations

import copy
import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from lib.artifacts.artifact_manifest import (
    ArtifactBasis,
    ArtifactInputClaim,
    ArtifactKey,
    ArtifactManifestEntry,
    InMemoryArtifactManifestAdapter,
)
from lib.artifacts.generation_input import (
    GridReferences,
    InputGap,
    InputRefused,
    ManifestInputObservation,
    StoryboardImageInput,
    grid_references,
    storyboard_image_input,
)

TARGET = "E1S02"
_REGISTERED_BASIS = ArtifactBasis.build("test/registered", kind_version=1, inputs={}).digest

#: 缺省登记在清单里的资产图与上一分镜图：键 → 路径。
_SHEETS: dict[ArtifactKey, str] = {
    ArtifactKey.asset_sheet("character", "张三"): "characters/张三.png",
    ArtifactKey.asset_sheet("character", "张三/劲装"): "characters/derivatives/张三/劲装.png",
    ArtifactKey.asset_sheet("scene", "祠堂"): "scenes/祠堂.png",
    ArtifactKey.asset_sheet("prop", "玉佩"): "props/玉佩.png",
    ArtifactKey.asset_sheet("product", "保温杯"): "products/保温杯.png",
    ArtifactKey.episode_storyboard(1, "E1S01"): "storyboards/scene_E1S01.png",
}
_ORIGINALS = ("products/refs/保温杯_1.jpg", "products/refs/杯刷_1.jpg")


def _project() -> dict[str, Any]:
    return {
        "content_mode": "ad",
        "aspect_ratio": "9:16",
        "style": "Anime",
        "style_description": "cinematic",
        "characters": {
            "张三": {
                "description": "hero",
                "character_sheet": "characters/张三.png",
                "derivatives": {
                    "劲装": {"description": "劲装", "character_sheet": "characters/derivatives/张三/劲装.png"},
                },
            },
        },
        "scenes": {"祠堂": {"description": "temple", "scene_sheet": "scenes/祠堂.png"}},
        "props": {"玉佩": {"description": "jade", "prop_sheet": "props/玉佩.png"}},
        "products": {
            "保温杯": {"product_sheet": "products/保温杯.png", "reference_images": ["products/refs/保温杯_1.jpg"]},
            "杯刷": {"product_sheet": "", "reference_images": ["products/refs/杯刷_1.jpg"]},
            "杯垫": {"product_sheet": "", "reference_images": []},
        },
    }


def _shot(shot_id: str, **fields: Any) -> dict[str, Any]:
    shot: dict[str, Any] = {
        "shot_id": shot_id,
        "image_prompt": "@[保温杯]放在@[祠堂]的供桌上",
        "characters_in_shot": [],
        "scenes": [],
        "props": [],
        "products_in_shot": [],
    }
    shot.update(fields)
    return shot


def _script(**target_fields: Any) -> dict[str, Any]:
    target = {
        "characters_in_shot": ["张三/劲装"],
        "scenes": ["祠堂"],
        "props": ["玉佩"],
        "products_in_shot": ["保温杯"],
        **target_fields,
    }
    return {
        "episode": 1,
        "content_mode": "ad",
        "shots": [
            _shot("E1S01", generated_assets={"storyboard_image": "storyboards/scene_E1S01.png"}),
            _shot(TARGET, **target),
            _shot("E1S03", segment_break=True),
        ],
    }


class _Fixture:
    """项目目录里的真实小图 + 内存清单：每个用例在其上做一处改动。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = _project()
        self.script = _script()
        self.files: set[str] = set()
        self.registered: dict[ArtifactKey, str] = dict(_SHEETS)
        for index, path in enumerate([*_SHEETS.values(), *_ORIGINALS]):
            self.write_image(path, shade=index)

    def write_image(self, relative: str, *, shade: int = 0) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2, 2), (shade * 20 % 256, 64, 128)).save(target, format="PNG")
        self.files.add(relative)

    def remove_file(self, relative: str) -> None:
        (self.root / relative).unlink()
        self.files.discard(relative)

    def observation(self) -> ManifestInputObservation:
        adapter = InMemoryArtifactManifestAdapter(artifacts=set(self.files))
        for key, path in self.registered.items():
            adapter.put_entry(key, ArtifactManifestEntry(artifact_path=path, basis_digest=_REGISTERED_BASIS))
        return ManifestInputObservation(self.root, adapter)

    def assemble(self, resource_id: str = TARGET) -> StoryboardImageInput:
        return storyboard_image_input(
            self.project,
            self.script,
            episode=1,
            resource_id=resource_id,
            observation=self.observation(),
        )

    def target(self) -> dict[str, Any]:
        return self.script["shots"][1]


def _admitted(fixture: _Fixture, resource_id: str = TARGET) -> StoryboardImageInput:
    result = fixture.assemble(resource_id)
    assert not result.gaps, result
    return result


def _identities(generation_input: StoryboardImageInput) -> list[tuple[str, str | None, str | None, str | None]]:
    return [
        (ref.visual.role, ref.visual.logical_type, ref.visual.logical_id, ref.visual.kind)
        for ref in generation_input.references
    ]


def _identity_binder(
    claims: Sequence[ArtifactInputClaim], content_digests: Mapping[str, str]
) -> tuple[ArtifactInputClaim, ...]:
    return tuple(
        ArtifactInputClaim(
            key=claim.key, artifact_path=claim.artifact_path, content_digest=content_digests[claim.artifact_path]
        )
        for claim in claims
    )


def test_legacy_asset_name_with_surrounding_whitespace_resolves_in_storyboard(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    fixture.project["characters"][" 张三 "] = fixture.project["characters"].pop("张三")

    result = fixture.assemble()

    assert not result.gaps, result
    assert "characters/derivatives/张三/劲装.png" in [ref.artifact_path for ref in result.references]


class TestAssemblyOrder:
    @pytest.mark.parametrize("field", ["characters_in_shot", "scenes", "props", "products_in_shot"])
    def test_reference_whitespace_does_not_change_asset_identity_or_basis(self, tmp_path, field):
        fixture = _Fixture(tmp_path)
        basis = _admitted(fixture).expected_basis()
        grid = _grid(fixture, [TARGET])
        fixture.target()[field] = [f"  {name}  " for name in fixture.target()[field]]

        assert _admitted(fixture).expected_basis() == basis
        assert _grid(fixture, [TARGET]) == grid

    def test_products_then_sheets_by_field_then_previous_storyboard(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.target()["products_in_shot"] = ["保温杯", "杯刷", "杯垫"]

        generation_input = _admitted(fixture)

        assert _identities(generation_input) == [
            ("asset_sheet", "product", "保温杯", "sheet"),
            ("source", "product", "保温杯", "original"),
            ("source", "product", "杯刷", "original"),
            ("asset_sheet", "character", "张三/劲装", "sheet"),
            ("asset_sheet", "scene", "祠堂", "sheet"),
            ("asset_sheet", "prop", "玉佩", "sheet"),
            ("previous_storyboard", "storyboard", "E1S01", None),
        ]

    def test_a_derivative_reference_resolves_to_its_own_sheet_and_manifest_key(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.target().update(characters_in_shot=["张三/劲装", "张三"], products_in_shot=[], scenes=[], props=[])

        generation_input = _admitted(fixture)

        assert [(ref.artifact_path, ref.claim) for ref in generation_input.references[:2]] == [
            (
                "characters/derivatives/张三/劲装.png",
                ArtifactInputClaim(
                    key=ArtifactKey.asset_sheet("character", "张三/劲装"),
                    artifact_path="characters/derivatives/张三/劲装.png",
                ),
            ),
            (
                "characters/张三.png",
                ArtifactInputClaim(
                    key=ArtifactKey.asset_sheet("character", "张三"), artifact_path="characters/张三.png"
                ),
            ),
        ]

    def test_references_are_deduplicated_by_path_keeping_the_first_occurrence(self, tmp_path):
        fixture = _Fixture(tmp_path)
        nfd = unicodedata.normalize("NFD", "张三")
        fixture.project["products"]["杯刷"]["reference_images"] = ["products/refs/保温杯_1.jpg"]
        fixture.target().update(
            characters_in_shot=["张三", nfd],
            products_in_shot=["保温杯", unicodedata.normalize("NFD", "保温杯"), "杯刷"],
        )

        generation_input = _admitted(fixture)

        assert [(ref.visual.logical_id, ref.artifact_path) for ref in generation_input.references] == [
            ("保温杯", "products/保温杯.png"),
            ("保温杯", "products/refs/保温杯_1.jpg"),
            ("张三", "characters/张三.png"),
            ("祠堂", "scenes/祠堂.png"),
            ("玉佩", "props/玉佩.png"),
            ("E1S01", "storyboards/scene_E1S01.png"),
        ]

    @pytest.mark.parametrize(
        ("resource_id", "mutate"),
        [
            pytest.param("E1S01", lambda fixture: None, id="first-shot"),
            pytest.param("E1S03", lambda fixture: None, id="segment-break"),
            pytest.param(
                TARGET,
                lambda fixture: fixture.registered.pop(ArtifactKey.episode_storyboard(1, "E1S01")),
                id="previous-unregistered",
            ),
            pytest.param(
                TARGET, lambda fixture: fixture.remove_file("storyboards/scene_E1S01.png"), id="previous-file-missing"
            ),
            pytest.param(
                TARGET,
                lambda fixture: fixture.script["shots"][0].update(generated_assets={}),
                id="previous-never-generated",
            ),
        ],
    )
    def test_an_unavailable_previous_storyboard_is_omitted_without_a_gap(self, tmp_path, resource_id, mutate):
        fixture = _Fixture(tmp_path)
        mutate(fixture)

        generation_input = _admitted(fixture, resource_id)

        assert all(ref.visual.role != "previous_storyboard" for ref in generation_input.references)


def _unset_sheet(fixture: _Fixture, bucket: str, name: str, field: str) -> None:
    fixture.project[bucket][name][field] = ""


_GAP_CASES: list[tuple[str, Callable[[_Fixture], object], list[InputGap]]] = [
    (
        "unregistered-asset",
        lambda f: f.target().update(characters_in_shot=["李四"]),
        [InputGap("reference_asset_unregistered", "character", "李四")],
    ),
    (
        "unregistered-derivative",
        lambda f: f.target().update(characters_in_shot=["张三/便装"]),
        [InputGap("reference_asset_unregistered", "character", "张三/便装")],
    ),
    (
        "unregistered-product",
        lambda f: f.target().update(products_in_shot=["不存在的商品"]),
        [InputGap("reference_asset_unregistered", "product", "不存在的商品")],
    ),
    (
        "scene-without-sheet",
        lambda f: _unset_sheet(f, "scenes", "祠堂", "scene_sheet"),
        [InputGap("reference_asset_missing", "scene", "祠堂")],
    ),
    (
        "sheet-file-missing",
        lambda f: f.remove_file("props/玉佩.png"),
        [InputGap("reference_asset_missing", "prop", "玉佩")],
    ),
    (
        "sheet-not-in-manifest",
        lambda f: f.registered.pop(ArtifactKey.asset_sheet("character", "张三/劲装")),
        [InputGap("reference_asset_missing", "character", "张三/劲装")],
    ),
    (
        "sheet-registered-at-another-path",
        lambda f: f.registered.update({ArtifactKey.asset_sheet("scene", "祠堂"): "scenes/旧祠堂.png"}),
        [InputGap("reference_asset_missing", "scene", "祠堂")],
    ),
    (
        "sheet-path-escapes-project",
        lambda f: f.project["scenes"]["祠堂"].update(scene_sheet="../祠堂.png"),
        [InputGap("reference_asset_missing", "scene", "祠堂")],
    ),
    (
        "product-sheet-declared-but-unavailable",
        lambda f: f.remove_file("products/保温杯.png"),
        [InputGap("reference_asset_missing", "product", "保温杯")],
    ),
    (
        "product-original-unreadable",
        lambda f: f.remove_file("products/refs/保温杯_1.jpg"),
        [InputGap("asset_original_missing", "product", "保温杯")],
    ),
    (
        "prompt-pending",
        lambda f: f.target().update(image_prompt=None),
        [InputGap("script_prompt_pending", None, TARGET)],
    ),
]


class TestGaps:
    @pytest.mark.parametrize(("mutate", "expected"), [pytest.param(m, e, id=i) for i, m, e in _GAP_CASES])
    def test_each_gap_refuses_with_its_code(self, tmp_path, mutate, expected):
        fixture = _Fixture(tmp_path)
        mutate(fixture)

        assert fixture.assemble().refusal == InputRefused(reasons=tuple(expected))

    def test_all_gaps_are_reported_at_once_in_assembly_order(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.target().update(
            image_prompt=None,
            characters_in_shot=["李四", "张三/劲装"],
            products_in_shot=["保温杯", "杯刷"],
        )
        fixture.remove_file("products/refs/杯刷_1.jpg")
        fixture.remove_file("products/保温杯.png")
        fixture.registered.pop(ArtifactKey.asset_sheet("character", "张三/劲装"))
        _unset_sheet(fixture, "props", "玉佩", "prop_sheet")

        refused = fixture.assemble().refusal

        assert refused == InputRefused(
            reasons=(
                InputGap("script_prompt_pending", None, TARGET),
                InputGap("reference_asset_missing", "product", "保温杯"),
                InputGap("asset_original_missing", "product", "杯刷"),
                InputGap("reference_asset_unregistered", "character", "李四"),
                InputGap("reference_asset_missing", "character", "张三/劲装"),
                InputGap("reference_asset_missing", "prop", "玉佩"),
            )
        )

    @pytest.mark.parametrize(("mutate", "expected"), [pytest.param(m, e, id=i) for i, m, e in _GAP_CASES])
    def test_a_gapped_input_still_projects_a_basis_recording_the_gap(self, tmp_path, mutate, expected):
        fixture = _Fixture(tmp_path)
        complete = _admitted(fixture).expected_basis()
        mutate(fixture)

        basis = fixture.assemble().expected_basis()

        assert basis != complete
        assert json.loads(basis.normalized_bytes())["inputs"]["absent"] == [gap.evidence() for gap in expected]

    def test_a_complete_input_records_no_absent_inputs(self, tmp_path):
        basis = _admitted(_Fixture(tmp_path)).expected_basis()

        assert "absent" not in json.loads(basis.normalized_bytes())["inputs"]

    def test_a_gapped_input_cannot_be_rendered_or_frozen(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.target().update(image_prompt=None)
        generation_input = fixture.assemble()

        with pytest.raises(ValueError, match="gaps"):
            generation_input.render(max_reference_images=8, model="m")
        with pytest.raises(ValueError, match="gaps"):
            generation_input.freeze(max_reference_images=8, model="m", bind_claims=_identity_binder)

    def test_a_malformed_reference_field_is_structural_damage(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.target()["products_in_shot"] = "保温杯"

        with pytest.raises(ValueError, match="products_in_shot"):
            fixture.assemble()


class TestProducts:
    @pytest.mark.parametrize(
        ("product", "expected"),
        [
            pytest.param(
                "保温杯",
                [("asset_sheet", "products/保温杯.png"), ("source", "products/refs/保温杯_1.jpg")],
                id="sheet-and-original",
            ),
            pytest.param("杯刷", [("source", "products/refs/杯刷_1.jpg")], id="original-only"),
            pytest.param("杯垫", [], id="neither-is-text-only"),
        ],
    )
    def test_product_references(self, tmp_path, product, expected):
        fixture = _Fixture(tmp_path)
        fixture.target().update(products_in_shot=[product], characters_in_shot=[], scenes=[], props=[])
        fixture.registered.pop(ArtifactKey.episode_storyboard(1, "E1S01"))

        generation_input = _admitted(fixture)

        assert [(ref.visual.role, ref.artifact_path) for ref in generation_input.references] == expected

    def test_an_unavailable_declared_product_sheet_does_not_fall_back_to_originals(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.registered.pop(ArtifactKey.asset_sheet("product", "保温杯"))

        assert fixture.assemble().refusal == InputRefused(
            reasons=(InputGap("reference_asset_missing", "product", "保温杯"),)
        )


class TestCanvasRatio:
    @pytest.mark.parametrize(
        ("content_mode", "aspect_ratio", "expected"),
        [
            pytest.param("drama", "4:3", "4:3", id="string"),
            pytest.param("narration", {"storyboards": "1:1", "videos": "9:16"}, "1:1", id="per-resource"),
            pytest.param("narration", None, "9:16", id="narration-default"),
            pytest.param("ad", None, "9:16", id="ad-default"),
            pytest.param("drama", None, "16:9", id="drama-default"),
        ],
    )
    def test_storyboard_canvas_follows_the_project_ratio_rule(self, tmp_path, content_mode, aspect_ratio, expected):
        fixture = _Fixture(tmp_path)
        fixture.project["content_mode"] = content_mode
        if aspect_ratio is None:
            fixture.project.pop("aspect_ratio")
        else:
            fixture.project["aspect_ratio"] = aspect_ratio

        assert _admitted(fixture).canvas_ratio == expected


class TestFreeze:
    def test_registration_basis_equals_expected_basis_even_when_clamped(self, tmp_path):
        fixture = _Fixture(tmp_path)
        generation_input = _admitted(fixture)
        expected = generation_input.expected_basis()

        with generation_input.freeze(max_reference_images=2, model="m", bind_claims=_identity_binder) as frozen:
            snapshot_dir = Path(str(frozen.references.visual_references[0].path)).parent
            assert frozen.basis == expected
            assert len(frozen.references.visual_references) == 2
            assert frozen.warnings == (
                {"key": "ref_too_many_images", "params": {"count": 6, "model": "m", "max_count": 2}},
            )
            assert "图1、图2为商品参考图" in frozen.prompt
            assert "图3" not in frozen.prompt
            assert snapshot_dir.is_dir()

        assert not snapshot_dir.exists()

    def test_claims_are_bound_to_the_frozen_bytes(self, tmp_path):
        fixture = _Fixture(tmp_path)
        generation_input = _admitted(fixture)

        with generation_input.freeze(max_reference_images=0, model="m", bind_claims=_identity_binder) as frozen:
            frozen_digests = [visual.content_digest for visual in frozen.references.visual_references]
            claimed = {claim.artifact_path: claim.content_digest for claim in frozen.claims}

        # 原图不是登记产物，没有 claim；其余每张参考图的 claim 绑定到冻结时读到的字节。
        claimable = [ref for ref in generation_input.references if ref.claim is not None]
        assert [claim.key for claim in frozen.claims] == [ref.claim.key for ref in claimable if ref.claim]
        assert claimed == {
            ref.artifact_path: digest
            for ref, digest in zip(generation_input.references, frozen_digests, strict=True)
            if ref.claim is not None
        }

    def test_preview_render_numbers_the_same_clamped_references(self, tmp_path):
        fixture = _Fixture(tmp_path)
        generation_input = _admitted(fixture)

        rendered = generation_input.render(max_reference_images=3, model="m")
        with generation_input.freeze(max_reference_images=3, model="m", bind_claims=_identity_binder) as frozen:
            assert rendered.prompt == frozen.prompt
            assert rendered.warnings == frozen.warnings

    def test_changing_a_reference_changes_the_expected_basis(self, tmp_path):
        fixture = _Fixture(tmp_path)
        before = _admitted(fixture).expected_basis()
        fixture.write_image("scenes/祠堂.png", shade=9)

        assert _admitted(fixture).expected_basis() != before

    def test_project_payload_is_not_mutated(self, tmp_path):
        fixture = _Fixture(tmp_path)
        project, script = copy.deepcopy(fixture.project), copy.deepcopy(fixture.script)

        _admitted(fixture)

        assert (fixture.project, fixture.script) == (project, script)


def _grid(fixture: _Fixture, member_ids: Sequence[str]) -> GridReferences:
    return grid_references(fixture.project, fixture.script, member_ids=member_ids, observation=fixture.observation())


class TestGridReferences:
    def test_member_sheets_are_unioned_in_member_order_without_products_or_previous_storyboard(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.script["shots"][0].update(characters_in_shot=["张三"], props=["玉佩"], products_in_shot=["保温杯"])

        references = _grid(fixture, ["E1S01", TARGET])

        assert not references.gaps
        assert [
            (ref.visual.logical_type, ref.visual.logical_id, ref.artifact_path) for ref in references.references
        ] == [
            ("character", "张三", "characters/张三.png"),
            ("prop", "玉佩", "props/玉佩.png"),
            ("character", "张三/劲装", "characters/derivatives/张三/劲装.png"),
            ("scene", "祠堂", "scenes/祠堂.png"),
        ]
        assert references.references[2].claim == ArtifactInputClaim(
            key=ArtifactKey.asset_sheet("character", "张三/劲装"),
            artifact_path="characters/derivatives/张三/劲装.png",
        )

    def test_product_gaps_do_not_refuse_a_grid(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.remove_file("products/保温杯.png")
        fixture.remove_file("products/refs/保温杯_1.jpg")

        assert isinstance(_grid(fixture, [TARGET]), GridReferences)

    def test_every_member_gap_is_reported_once_in_assembly_order(self, tmp_path):
        fixture = _Fixture(tmp_path)
        fixture.script["shots"][0]["characters_in_shot"] = ["李四"]
        fixture.script["shots"][2]["characters_in_shot"] = ["李四", "张三/劲装"]
        fixture.project["characters"]["张三"]["derivatives"]["劲装"]["character_sheet"] = ""
        fixture.remove_file("props/玉佩.png")

        refused = _grid(fixture, ["E1S01", TARGET, "E1S03"]).refusal

        assert refused == InputRefused(
            reasons=(
                InputGap("reference_asset_unregistered", "character", "李四"),
                InputGap("reference_asset_missing", "character", "张三/劲装"),
                InputGap("reference_asset_missing", "prop", "玉佩"),
            )
        )

    def test_a_member_missing_from_the_script_is_structural_damage(self, tmp_path):
        fixture = _Fixture(tmp_path)

        with pytest.raises(ValueError, match="E1S09"):
            _grid(fixture, [TARGET, "E1S09"])


class TestImportedMultiview:
    def _add_views(self, fixture: _Fixture, name: str = "张三") -> None:
        views = []
        for framing, angles in (
            ("headshot", ("front", "left", "right")),
            ("full_body", ("front", "left", "right", "back")),
        ):
            for angle in angles:
                path = f"characters/refs/{name}-{framing}-{angle}.png"
                fixture.write_image(path, shade=len(views) + 10)
                views.append({"path": path, "role": "identity", "view": angle, "framing": framing, "confirmed": True})
        fixture.project["characters"][name] = {"description": "actor", "reference_views": views}

    def test_four_slots_preserve_two_identities_scene_and_previous_frame(self, tmp_path):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        self._add_views(fixture, "李四")
        fixture.target().update(characters_in_shot=["张三", "李四"], products_in_shot=[], props=[])
        result = _admitted(fixture)

        with result.freeze(max_reference_images=4, model="configured-workflow", bind_claims=_identity_binder) as frozen:
            assert [(ref.logical_type, ref.logical_id) for ref in frozen.references.visual_references] == [
                ("character", "张三"),
                ("character", "李四"),
                ("scene", "祠堂"),
                ("storyboard", "E1S01"),
            ]
            assert "张三 / 大头照 / 正面 / 身份基准" in frozen.prompt
            assert "李四 / 大头照 / 正面 / 身份基准" in frozen.prompt
            assert "图4为上一分镜图" in frozen.prompt
            assert "图5" not in frozen.prompt
            warning = frozen.warnings[0]
            assert warning["key"] == "ref_multiview_selected"
            assert "张三 / identity / headshot / front" in warning["params"]["selected"]
            assert "李四 / identity / full_body / back" in warning["params"]["omitted"]
            assert frozen.basis == result.expected_basis()

    @pytest.mark.parametrize(
        ("prompt", "expected"),
        [
            ("@[张三] left profile close-up", ("identity", "headshot", "left")),
            ("@[张三] full-body back view", ("look", "full_body", "back")),
            ("@[张三] stands beside the doorway", ("look", "full_body", "back")),
        ],
    )
    def test_spare_slot_is_selected_for_the_shot_and_preview_matches_execution(self, tmp_path, prompt, expected):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        look_path = "characters/refs/look-back.png"
        fixture.write_image(look_path)
        fixture.project["characters"]["张三"]["reference_views"].append(
            {
                "path": look_path,
                "role": "look",
                "framing": "full_body",
                "view": "back",
                "confirmed": True,
            }
        )
        fixture.target().update(characters_in_shot=["张三"], products_in_shot=[], props=[], image_prompt=prompt)
        result = _admitted(fixture)
        preview = result.render(max_reference_images=4, model="configured-workflow")

        with result.freeze(max_reference_images=4, model="configured-workflow", bind_claims=_identity_binder) as frozen:
            last = frozen.references.visual_references[-1]
            assert (last.role, last.framing, last.view) == expected
            assert (preview.prompt, preview.warnings) == (frozen.prompt, frozen.warnings)
            assert frozen.references.visual_references[0].role == "identity"
            assert "图1" in frozen.prompt

    @pytest.mark.parametrize("confirmed", [False, None])
    def test_pending_or_only_frozen_views_do_not_become_approved_through_legacy_fallback(self, tmp_path, confirmed):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        asset = fixture.project["characters"]["张三"]
        asset["reference_image"] = asset["reference_views"][0]["path"]
        for view in asset["reference_views"]:
            view.update(confirmed=confirmed, frozen=True)
        fixture.target().update(characters_in_shot=["张三"], products_in_shot=[], props=[], scenes=[])

        result = fixture.assemble()

        assert InputGap("reference_views_unconfirmed", "character", "张三") in result.gaps
        assert not any(ref.visual.logical_type == "character" for ref in result.references)

    def test_unconfirmed_missing_view_is_not_sent_but_missing_approved_view_blocks(self, tmp_path):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        views = fixture.project["characters"]["张三"]["reference_views"]
        views.append(
            {
                "path": "characters/refs/pending-look.png",
                "role": "look",
                "view": "front",
                "framing": "full_body",
                "confirmed": False,
            }
        )
        fixture.target().update(characters_in_shot=["张三"], products_in_shot=[], props=[], scenes=[])

        admitted = _admitted(fixture)
        assert all(ref.artifact_path != "characters/refs/pending-look.png" for ref in admitted.references)
        views[-1]["confirmed"] = True

        assert InputGap("asset_original_missing", "character", "张三") in fixture.assemble().gaps

    def test_a_look_without_an_identity_anchor_is_refused(self, tmp_path):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        for view in fixture.project["characters"]["张三"]["reference_views"]:
            view["role"] = "look"
        fixture.target().update(characters_in_shot=["张三"], products_in_shot=[], props=[], scenes=[])

        assert InputGap("reference_views_unconfirmed", "character", "张三") in fixture.assemble().gaps

    def test_mixed_import_and_legacy_sheet_keeps_both_subjects(self, tmp_path):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        fixture.target().update(characters_in_shot=["张三", "张三/劲装"], products_in_shot=[], props=[], scenes=[])
        # The legacy derivative remains a separate, explicitly referenced asset.
        fixture.project["characters"]["张三"]["derivatives"] = _project()["characters"]["张三"]["derivatives"]
        result = _admitted(fixture)

        assert [(ref.visual.logical_id, ref.visual.role) for ref in result.references[:3]] == [
            ("张三", "identity"),
            ("张三/劲装", "asset_sheet"),
            ("E1S01", "previous_storyboard"),
        ]

    def test_view_labels_are_part_of_provenance_but_paths_are_not(self, tmp_path):
        fixture = _Fixture(tmp_path)
        self._add_views(fixture)
        fixture.target().update(characters_in_shot=["张三"], products_in_shot=[], props=[], scenes=[])
        before = _admitted(fixture).expected_basis()
        fixture.project["characters"]["张三"]["reference_views"][0]["view"] = "three_quarter"

        assert _admitted(fixture).expected_basis() != before

    def test_imported_scene_views_do_not_require_a_generated_sheet(self, tmp_path):
        fixture = _Fixture(tmp_path)
        path = "scenes/refs/temple-front.png"
        fixture.write_image(path)
        fixture.project["scenes"]["祠堂"] = {
            "reference_views": [
                {
                    "path": path,
                    "role": "space",
                    "view": "front",
                    "framing": "wide",
                    "confirmed": True,
                }
            ]
        }
        fixture.target().update(characters_in_shot=[], products_in_shot=[], props=[])
        result = _admitted(fixture)

        assert result.references[0].artifact_path == path
        assert result.references[0].claim is None
        assert "空间参考" in result.render(max_reference_images=4, model="configured-workflow").prompt
