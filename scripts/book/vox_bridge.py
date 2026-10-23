"""Opt-in loopback bridge for a separately installed official VoxCPM2 environment.

Only local model files are accepted. Importing this module does not load weights,
install dependencies, download models or start a server.
"""

from __future__ import annotations

import argparse
import array
import importlib
import io
import json
import math
import sys
import threading
import wave
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from lib.book_audio.tts import BookSynthesisRequest
from lib.book_audio.voxcpm import VoxCPM2Settings, voxcpm2_generation_kwargs


class VoxSynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=1000)
    reference_audio: str = Field(min_length=1)
    reference_text: str | None = Field(default=None, max_length=5000)
    control: str = Field(default="", max_length=500)
    language: str = "zh"
    settings: VoxCPM2Settings = Field(default_factory=VoxCPM2Settings)


def resolve_reference(root: Path, relative: str) -> Path:
    """Limit the model's file access to configured reference assets, never arbitrary paths."""
    if "\\" in relative or Path(relative).is_absolute() or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("Reference must be a relative filename below the reference root")
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink references are not supported")
    try:
        current = current.resolve(strict=True)
        current.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Reference audio was not found below the configured root") from exc
    if not current.is_file():
        raise ValueError("Reference audio is not a file")
    return current


def encode_wav(waveform: Iterable[float], sample_rate: int) -> bytes:
    """Encode the official mono float waveform as portable PCM16 WAV."""
    samples = array.array("h")
    for sample in waveform:
        value = float(sample)
        if not math.isfinite(value):
            raise ValueError("VoxCPM2 returned non-finite audio samples")
        samples.append(max(-32768, min(32767, round(value * 32768))))
    if not samples:
        raise ValueError("VoxCPM2 returned empty audio")
    if sys.byteorder != "little":
        samples.byteswap()
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(samples.tobytes())
    return stream.getvalue()


def create_bridge(generate: Callable[..., Any], reference_root: Path, sample_rate: int) -> FastAPI:
    """Serialize model access and use the model's real output sample rate."""
    root = reference_root.resolve(strict=True)
    if not root.is_dir() or sample_rate != 48000:
        raise ValueError("VoxCPM2 requires a reference directory and its native 48000 Hz output")
    lock = threading.Lock()
    app = FastAPI(title="ArcReel VoxCPM2 local bridge")

    @app.get("/health")
    def health() -> dict[str, str | int]:
        return {"adapter": "arcreel-voxcpm2", "model": "VoxCPM2", "sample_rate": sample_rate, "status": "ready"}

    @app.post("/synthesize")
    def synthesize(payload: VoxSynthesisPayload) -> Response:
        request = BookSynthesisRequest(
            text=payload.text,
            output_path=Path("unused.wav"),
            reference_audio=payload.reference_audio,
            reference_text=payload.reference_text,
            emotion_text=payload.control,
            language=payload.language,
        )
        try:
            reference = resolve_reference(root, payload.reference_audio)
            kwargs = voxcpm2_generation_kwargs(request, payload.settings, reference)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with lock:
            waveform = generate(**kwargs)
            audio = encode_wav(waveform, sample_rate)
        return Response(audio, media_type="audio/wav", headers={"X-ArcReel-TTS-Model": "VoxCPM2"})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=7862)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    model_dir = args.model_dir.resolve(strict=True)
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    if config.get("architecture", "").lower() != "voxcpm2":
        raise ValueError("The local model directory must contain VoxCPM2 weights, not VoxCPM 1.x")
    module = importlib.import_module("voxcpm")
    model = module.VoxCPM(
        voxcpm_model_path=str(model_dir),
        zipenhancer_model_path=None,
        enable_denoiser=False,
        optimize=False,
        device=args.device,
    )
    import uvicorn

    uvicorn.run(
        create_bridge(model.generate, args.reference_root, model.tts_model.sample_rate),
        host="127.0.0.1",
        port=args.port,
    )


if __name__ == "__main__":
    main()
