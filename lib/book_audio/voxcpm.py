"""VoxCPM2 controls mapped to the official Python API through an opt-in bridge."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from lib.book_audio.tts import BookSynthesisRequest, SpeechCapabilities, UnsupportedSpeechControl, validate_controls
from lib.infra.async_thread import run_sync_transaction

VOXCPM2_LANGUAGES = (
    "ar",
    "my",
    "zh",
    "en",
    "fr",
    "de",
    "hi",
    "id",
    "it",
    "ja",
    "ko",
    "ms",
    "nl",
    "pt",
    "ru",
    "es",
    "th",
    "vi",
    "da",
    "fi",
    "el",
    "he",
    "km",
    "lo",
    "pl",
    "sw",
    "sv",
    "tl",
    "tr",
)


class VoxCPM2Settings(BaseModel):
    """Only upstream-supported generation options; no hidden voice substitutions."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    clone_mode: Literal["controllable", "continuation"] = "controllable"
    cfg_value: float = Field(default=2.0, ge=0.1, le=10)
    inference_timesteps: int = Field(default=10, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def voxcpm2_capabilities(*, continuation: bool = False) -> SpeechCapabilities:
    return SpeechCapabilities(
        emotion_description=not continuation,
        reference_audio=True,
        reference_transcript=continuation,
        languages=VOXCPM2_LANGUAGES,
    )


def validate_voxcpm2_request(request: BookSynthesisRequest, settings: VoxCPM2Settings) -> None:
    """Reject controls that cannot be faithfully mapped instead of silently dropping them."""
    validate_controls(request, voxcpm2_capabilities(continuation=settings.clone_mode == "continuation"))
    if request.voice:
        raise UnsupportedSpeechControl("VoxCPM2 cloning uses reference audio, not a provider voice ID")
    if not request.reference_audio:
        raise ValueError("VoxCPM2 character cloning requires a reference audio filename")
    if request.emotion_intensity != 1.0:
        raise UnsupportedSpeechControl("VoxCPM2 has no numeric emotion intensity; describe expression in words")
    if settings.clone_mode == "continuation" and not (request.reference_text or "").strip():
        raise ValueError("VoxCPM2 continuation cloning requires the exact reference transcript")
    if len(request.emotion_text) > 500 or any(c in request.emotion_text for c in "()（）\r\n"):
        raise ValueError("VoxCPM2 control description must be one line without parentheses, at most 500 characters")


def voxcpm2_generation_kwargs(
    request: BookSynthesisRequest, settings: VoxCPM2Settings, reference_path: Path
) -> dict[str, str | float | int | bool]:
    """Build the public VoxCPM.generate kwargs, never changing the stored source text."""
    validate_voxcpm2_request(request, settings)
    kwargs: dict[str, str | float | int | bool] = {
        "text": f"({request.emotion_text}){request.text}" if request.emotion_text else request.text,
        "reference_wav_path": str(reference_path),
        "cfg_value": settings.cfg_value,
        "inference_timesteps": settings.inference_timesteps,
        "seed": settings.seed,
        "normalize": False,
        "denoise": False,
    }
    if settings.clone_mode == "continuation":
        kwargs["prompt_wav_path"] = str(reference_path)
        kwargs["prompt_text"] = request.reference_text or ""
    return kwargs


@dataclass
class VoxCPM2HTTPAdapter:
    """Client for ArcReel's own bridge, not an assumed third-party or official HTTP API."""

    base_url: str
    settings: VoxCPM2Settings = field(default_factory=VoxCPM2Settings)
    timeout_seconds: float = 600

    @property
    def capabilities(self) -> SpeechCapabilities:
        return voxcpm2_capabilities(continuation=self.settings.clone_mode == "continuation")

    async def synthesize(self, request: BookSynthesisRequest) -> Path:
        validate_voxcpm2_request(request, self.settings)
        payload = {
            "text": request.text,
            "reference_audio": request.reference_audio,
            "reference_text": request.reference_text,
            "control": request.emotion_text,
            "language": request.language,
            "settings": self.settings.model_dump(),
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(f"{self.base_url.rstrip('/')}/synthesize", json=payload)
            response.raise_for_status()
            if response.headers.get("x-arcreel-tts-model") != "VoxCPM2":
                raise ValueError("The configured endpoint did not identify itself as the ArcReel VoxCPM2 bridge")
            content = response.content
        try:
            with wave.open(io.BytesIO(content), "rb") as audio:
                if audio.getframerate() != 48000 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                    raise ValueError("VoxCPM2 bridge must return native 48000 Hz mono PCM16 audio")
                frames = audio.getnframes()
                if frames == 0 or len(audio.readframes(frames)) != frames * 2:
                    raise ValueError("VoxCPM2 bridge returned empty or truncated audio")
        except (wave.Error, EOFError) as exc:
            raise ValueError("VoxCPM2 bridge did not return valid WAV audio") from exc
        await run_sync_transaction(request.output_path.write_bytes, content)
        return request.output_path
