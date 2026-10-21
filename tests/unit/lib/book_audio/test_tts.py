"""HTTP adapter and official Python bridge contract tests, not live model validation."""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lib.book_audio.tts import BookSynthesisRequest, IndexTTS2HTTPAdapter
from scripts.book.index_bridge import create_bridge


def wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\0\0" * 240)
    return stream.getvalue()


async def test_http_adapter_keeps_emotion_out_of_spoken_text(tmp_path: Path, respx_mock):
    route = respx_mock.post("http://127.0.0.1:7861/synthesize").mock(
        return_value=httpx.Response(200, content=wav_bytes(), headers={"content-type": "audio/wav"})
    )
    output = await IndexTTS2HTTPAdapter("http://127.0.0.1:7861").synthesize(
        BookSynthesisRequest(
            "他说：别怕。", tmp_path / "speech.wav", reference_audio="narrator.wav", emotion_text="calm"
        )
    )
    payload = json.loads(route.calls.last.request.content)
    assert payload["text"] == "他说：别怕。"
    assert payload["emotion_text"] == "calm"
    assert output.read_bytes() == wav_bytes()


async def test_http_adapter_propagates_failure_without_voice_fallback(tmp_path: Path, respx_mock):
    respx_mock.post("http://127.0.0.1:7861/synthesize").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await IndexTTS2HTTPAdapter("http://127.0.0.1:7861").synthesize(
            BookSynthesisRequest("正文", tmp_path / "speech.wav", reference_audio="voice.wav")
        )
    assert not (tmp_path / "speech.wav").exists()


def test_bridge_constrains_references_and_maps_official_parameters(tmp_path: Path):
    (tmp_path / "voice.wav").write_bytes(wav_bytes())
    calls = []

    def infer(**kwargs):
        calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(wav_bytes())

    client = TestClient(create_bridge(infer, tmp_path))
    denied = client.post("/synthesize", json={"text": "正文", "reference_audio": "../outside.wav"})
    assert denied.status_code == 422
    response = client.post(
        "/synthesize",
        json={
            "text": "正文",
            "reference_audio": "voice.wav",
            "emotion_vector": [0, 0, 0, 0, 0, 0, 1, 0],
            "emotion_intensity": 0.5,
        },
    )
    assert response.content == wav_bytes()
    assert calls[0]["text"] == "正文"
    assert calls[0]["emo_vector"] == [0, 0, 0, 0, 0, 0, 0.5, 0]
    assert calls[0]["use_random"] is False


async def test_intensity_without_emotion_is_not_silently_ignored(tmp_path: Path, respx_mock):
    with pytest.raises(ValueError, match="intensity requires"):
        await IndexTTS2HTTPAdapter("http://127.0.0.1:7861").synthesize(
            BookSynthesisRequest("正文", tmp_path / "speech.wav", reference_audio="voice.wav", emotion_intensity=0.5)
        )
    assert not respx_mock.calls
