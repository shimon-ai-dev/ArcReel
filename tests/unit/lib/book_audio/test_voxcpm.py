"""Official VoxCPM2 Python and bridge contracts, without downloading or running a model."""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lib.book_audio.tts import BookSynthesisRequest, IndexTTS2HTTPAdapter, UnsupportedSpeechControl
from lib.book_audio.voxcpm import VoxCPM2HTTPAdapter, VoxCPM2Settings, voxcpm2_generation_kwargs
from scripts.book.vox_bridge import create_bridge, encode_wav


def test_controllable_clone_preserves_text_and_uses_reference(tmp_path: Path):
    request = BookSynthesisRequest(
        "别怕，我在这里。", tmp_path / "out.wav", reference_audio="voice.wav", emotion_text="温柔，轻声安慰"
    )
    kwargs = voxcpm2_generation_kwargs(request, VoxCPM2Settings(seed=7), tmp_path / "voice.wav")
    assert kwargs == {
        "text": "(温柔，轻声安慰)别怕，我在这里。",
        "reference_wav_path": str(tmp_path / "voice.wav"),
        "cfg_value": 2.0,
        "inference_timesteps": 10,
        "seed": 7,
        "normalize": False,
        "denoise": False,
    }
    assert request.text == "别怕，我在这里。"


def test_continuation_clone_uses_exact_transcript_and_both_audio_inputs(tmp_path: Path):
    request = BookSynthesisRequest(
        "下一句。", tmp_path / "out.wav", reference_audio="voice.wav", reference_text="原始录音说了这一句。"
    )
    kwargs = voxcpm2_generation_kwargs(request, VoxCPM2Settings(clone_mode="continuation"), tmp_path / "voice.wav")
    assert kwargs["text"] == "下一句。"
    assert kwargs["prompt_text"] == "原始录音说了这一句。"
    assert kwargs["prompt_wav_path"] == kwargs["reference_wav_path"] == str(tmp_path / "voice.wav")


@pytest.mark.parametrize(
    "control",
    [
        {"speed": 1.2},
        {"emotion_vector": (0.0,) * 8},
        {"nonverbal": "laugh"},
        {"emotion_text": "sad", "emotion_intensity": 0.5},
        {"reference_text": "录音文本"},
        {"voice": "other-person"},
    ],
)
async def test_unsupported_control_fails_before_network(tmp_path: Path, respx_mock, control):
    with pytest.raises(UnsupportedSpeechControl):
        await VoxCPM2HTTPAdapter("http://127.0.0.1:7862").synthesize(
            BookSynthesisRequest("正文", tmp_path / "out.wav", reference_audio="voice.wav", **control)
        )
    assert not respx_mock.calls
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize("control", [{}, {"reference_text": "参考", "emotion_text": "快乐"}])
def test_continuation_requires_transcript_and_disallows_style(tmp_path: Path, control):
    with pytest.raises(ValueError, match=r"transcript|Emotion descriptions"):
        voxcpm2_generation_kwargs(
            BookSynthesisRequest("正文", tmp_path / "out.wav", reference_audio="voice.wav", **control),
            VoxCPM2Settings(clone_mode="continuation"),
            tmp_path / "voice.wav",
        )


async def test_adapter_transports_separate_control_and_settings(tmp_path: Path, respx_mock):
    audio = encode_wav([0.1] * 480, 48000)
    route = respx_mock.post("http://127.0.0.1:7862/synthesize").mock(
        return_value=httpx.Response(
            200,
            content=audio,
            headers={"X-ArcReel-TTS-Model": "VoxCPM2"},
        )
    )
    output = await VoxCPM2HTTPAdapter("http://127.0.0.1:7862", settings=VoxCPM2Settings(seed=9)).synthesize(
        BookSynthesisRequest("真的？", tmp_path / "speech.wav", reference_audio="role/front.wav", emotion_text="惊喜")
    )
    payload = json.loads(route.calls.last.request.content)
    assert payload["text"] == "真的？"
    assert payload["control"] == "惊喜"
    assert payload["settings"]["seed"] == 9
    assert output.read_bytes() == audio


@pytest.mark.parametrize(("status", "headers"), [(503, {}), (200, {})])
async def test_adapter_does_not_fall_back_or_accept_wrong_service(tmp_path: Path, respx_mock, status, headers):
    respx_mock.post("http://127.0.0.1:7862/synthesize").mock(
        return_value=httpx.Response(status, content=encode_wav([0] * 480, 48000), headers=headers)
    )
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await VoxCPM2HTTPAdapter("http://127.0.0.1:7862").synthesize(
            BookSynthesisRequest("正文", tmp_path / "out.wav", reference_audio="voice.wav")
        )
    assert not (tmp_path / "out.wav").exists()


def test_bridge_calls_official_contract_and_returns_native_rate(tmp_path: Path):
    (tmp_path / "voice.wav").write_bytes(encode_wav([0] * 480, 48000))
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return [0.0, 0.5, -0.5] * 160

    client = TestClient(create_bridge(generate, tmp_path, 48000))
    response = client.post("/synthesize", json={"text": "您好。", "reference_audio": "voice.wav", "control": "平静"})
    assert response.status_code == 200
    assert response.headers["x-arcreel-tts-model"] == "VoxCPM2"
    with wave.open(io.BytesIO(response.content), "rb") as audio:
        assert audio.getframerate() == 48000
        assert audio.getnframes() == 480
        assert audio.getnchannels() == 1
    assert calls[0]["text"] == "(平静)您好。"
    assert calls[0]["reference_wav_path"] == str(tmp_path / "voice.wav")
    assert "prompt_wav_path" not in calls[0]


@pytest.mark.parametrize(
    "reference", ["../voice.wav", "/etc/passwd", "role/../voice.wav", "missing.wav", "role\\voice.wav"]
)
def test_bridge_rejects_outside_and_missing_references(tmp_path: Path, reference):
    client = TestClient(create_bridge(lambda **_: [0.0], tmp_path, 48000))
    response = client.post("/synthesize", json={"text": "正文", "reference_audio": reference})
    assert response.status_code == 422


def test_bridge_rejects_symlink_and_unknown_controls(tmp_path: Path):
    (tmp_path / "voice.wav").write_bytes(encode_wav([0.0], 48000))
    (tmp_path / "linked.wav").symlink_to(tmp_path / "voice.wav")
    client = TestClient(create_bridge(lambda **_: [0.0], tmp_path, 48000))
    assert client.post("/synthesize", json={"text": "正文", "reference_audio": "linked.wav"}).status_code == 422
    assert (
        client.post(
            "/synthesize", json={"text": "正文", "reference_audio": "voice.wav", "emotion_vector": [1] * 8}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/synthesize", json={"text": "正文", "reference_audio": "voice.wav", "settings": {"speed": 1.5}}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("samples", [[], [float("nan")], [float("inf")]])
def test_empty_or_nonfinite_model_audio_is_not_saved(samples):
    with pytest.raises(ValueError, match=r"empty|non-finite"):
        encode_wav(samples, 48000)


async def test_non_vox_adapter_does_not_ignore_reference_transcript(tmp_path: Path, respx_mock):
    with pytest.raises(UnsupportedSpeechControl, match="transcript"):
        await IndexTTS2HTTPAdapter("http://127.0.0.1:7861").synthesize(
            BookSynthesisRequest("正文", tmp_path / "out.wav", reference_audio="voice.wav", reference_text="原声")
        )
    assert not respx_mock.calls


@pytest.mark.parametrize(
    "audio", [b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40, encode_wav([0.0], 16000), encode_wav([0.0], 48000)[:-1]]
)
async def test_adapter_rejects_malformed_or_non_native_audio(tmp_path: Path, respx_mock, audio):
    respx_mock.post("http://127.0.0.1:7862/synthesize").mock(
        return_value=httpx.Response(200, content=audio, headers={"X-ArcReel-TTS-Model": "VoxCPM2"})
    )
    with pytest.raises(ValueError, match=r"WAV|48000|truncated"):
        await VoxCPM2HTTPAdapter("http://127.0.0.1:7862").synthesize(
            BookSynthesisRequest("正文", tmp_path / "out.wav", reference_audio="voice.wav")
        )
    assert not (tmp_path / "out.wav").exists()
