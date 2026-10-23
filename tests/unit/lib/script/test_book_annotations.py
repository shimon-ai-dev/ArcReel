import pytest
from pydantic import ValidationError

from lib.script.script_document import build_materialized_script
from lib.script.script_models import NarrationScriptPlanSegment


def unit(**extra):
    return {
        "segment_id": "E1S01",
        "novel_text": "他说：你好。",
        "duration_seconds": 8,
        "characters_in_segment": [],
        "scenes": [],
        "props": [],
        **extra,
    }


def test_book_annotations_survive_original_materialization():
    data = NarrationScriptPlanSegment.model_validate(
        unit(
            book_speech=[
                {
                    "source_start": 3,
                    "source_end": 6,
                    "text": "你好。",
                    "speaker_id": "alice",
                    "performance": {"emotion": "warm"},
                    "pause_after_seconds": 0.2,
                }
            ],
            book_sound_cues=[{"cue_id": "rain", "description": "窗外雨声", "source_start": 0, "source_end": 6}],
        )
    )
    result = build_materialized_script(
        {"content_mode": "narration", "generation_mode": "storyboard", "output_mode": "audiobook"},
        1,
        plan_kind="narration",
        plan_entries=[data.model_dump()],
        title="One",
    )
    assert result["segments"][0]["book_speech"][0]["text"] == "你好。"
    assert not result["segments"][0].get("pending_authoring")


@pytest.mark.parametrize(("start", "end", "text"), [(0, 3, "你好。"), (3, 20, "你好。"), (4, 3, "你好。")])
def test_book_annotations_fail_wrong_local_spans(start, end, text):
    with pytest.raises(ValidationError):
        NarrationScriptPlanSegment.model_validate(
            unit(book_speech=[{"source_start": start, "source_end": end, "text": text}])
        )


def test_non_book_schema_roundtrip_does_not_add_empty_annotation_fields():
    result = NarrationScriptPlanSegment.model_validate(unit()).model_dump()
    assert "book_speech" not in result
    assert "book_sound_cues" not in result


def test_schema_safe_performance_still_rejects_zero_speed():
    with pytest.raises(ValidationError):
        NarrationScriptPlanSegment.model_validate(
            unit(
                book_speech=[
                    {
                        "source_start": 0,
                        "source_end": 3,
                        "text": "他说：",
                        "performance": {"speed": 0},
                    }
                ]
            )
        )
