"""Explicit book-performance contracts; unsupported controls never disappear."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lib.backends.audio_backends.base import AudioBackend, AudioCapability, AudioSynthesisRequest
from lib.infra.async_thread import run_sync_transaction


@dataclass(frozen=True)
class SpeechCapabilities:
    emotion_vector: bool = False
    emotion_description: bool = False
    reference_audio: bool = False
    speed: bool = False
    nonverbal: tuple[str, ...] = ()
    languages: tuple[str, ...] = ("zh", "en")
    max_text_chars: int = 1000


@dataclass(frozen=True)
class BookSynthesisRequest:
    text: str
    output_path: Path
    voice: str = ""
    reference_audio: str | None = None
    emotion_vector: tuple[float, ...] = ()
    emotion_text: str = ""
    emotion_intensity: float = 1.0
    speed: float = 1.0
    nonverbal: str = ""
    language: str = "zh"


class UnsupportedSpeechControl(ValueError):
    """Requested performance cannot be expressed by the selected adapter."""


def validate_controls(request: BookSynthesisRequest, capabilities: SpeechCapabilities) -> None:
    if not request.text.strip() or len(request.text) > capabilities.max_text_chars:
        raise ValueError("Speech text is empty or exceeds the adapter text limit")
    if request.language not in capabilities.languages:
        raise UnsupportedSpeechControl(f"Unsupported language: {request.language}")
    if request.emotion_vector and not capabilities.emotion_vector:
        raise UnsupportedSpeechControl("Emotion vectors are not supported")
    if request.emotion_text and not capabilities.emotion_description:
        raise UnsupportedSpeechControl("Emotion descriptions are not supported")
    if request.reference_audio and not capabilities.reference_audio:
        raise UnsupportedSpeechControl("Reference audio is not supported")
    if request.speed != 1.0 and not capabilities.speed:
        raise UnsupportedSpeechControl("Speaking speed control is not supported")
    if request.nonverbal and request.nonverbal not in capabilities.nonverbal:
        raise UnsupportedSpeechControl(f"Native nonverbal control is not supported: {request.nonverbal}")
    if not 0 <= request.emotion_intensity <= 1 or not 0.25 <= request.speed <= 4:
        raise ValueError("Invalid emotion intensity or speaking speed")
    if request.emotion_vector and (
        len(request.emotion_vector) != 8 or any(not 0 <= v <= 1 for v in request.emotion_vector)
    ):
        raise ValueError("IndexTTS emotion vector must contain eight values in [0, 1]")
    if request.emotion_intensity != 1.0 and not (request.emotion_vector or request.emotion_text):
        raise UnsupportedSpeechControl("Emotion intensity requires an emotion vector or description")
    if request.emotion_vector and request.emotion_text:
        raise ValueError("Choose either an emotion vector or an emotion description")


@dataclass
class IndexTTS2HTTPAdapter:
    """Client for ArcReel's opt-in IndexTTS2 bridge, not an upstream HTTP API.

    reference_audio is a relative filename under the bridge's reference root.
    The bridge runs in the independently installed official IndexTTS2 environment.
    """

    base_url: str
    timeout_seconds: float = 600
    capabilities: SpeechCapabilities = field(
        default_factory=lambda: SpeechCapabilities(
            emotion_vector=True,
            emotion_description=True,
            reference_audio=True,
        )
    )

    async def synthesize(self, request: BookSynthesisRequest) -> Path:
        validate_controls(request, self.capabilities)
        if not request.reference_audio:
            raise ValueError("IndexTTS2 requires a voice reference audio filename")
        payload = {
            "text": request.text,
            "reference_audio": request.reference_audio,
            "emotion_vector": list(request.emotion_vector),
            "emotion_text": request.emotion_text,
            "emotion_intensity": request.emotion_intensity,
            "language": request.language,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(f"{self.base_url.rstrip('/')}/synthesize", json=payload)
            response.raise_for_status()
            content = response.content
        if len(content) < 44 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise ValueError("IndexTTS2 bridge did not return WAV audio")
        await run_sync_transaction(request.output_path.write_bytes, content)
        return request.output_path


@dataclass
class ExistingAudioAdapter:
    """Reuse an ArcReel provider without pretending it supports emotional controls."""

    backend: AudioBackend

    @property
    def capabilities(self) -> SpeechCapabilities:
        return SpeechCapabilities(speed=AudioCapability.SPEECH_SPEED in self.backend.capabilities)

    async def synthesize(self, request: BookSynthesisRequest) -> Path:
        validate_controls(request, self.capabilities)
        await self.backend.synthesize(
            AudioSynthesisRequest(
                text=request.text,
                output_path=request.output_path,
                voice=request.voice,
                language_type={"zh": "Chinese", "en": "English"}[request.language],
                speed=request.speed if self.capabilities.speed else None,
            )
        )
        return request.output_path
