"""Opt-in loopback bridge for the official IndexTTS2 Python environment.

Start from the independently installed upstream environment with ArcReel on
PYTHONPATH. Nothing is downloaded, installed, or initialized on module import.
"""

from __future__ import annotations

import argparse
import importlib
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from lib.book_audio.tts import BookSynthesisRequest, SpeechCapabilities, validate_controls


class SynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    reference_audio: str
    emotion_vector: tuple[float, ...] = ()
    emotion_text: str = ""
    emotion_intensity: float = Field(default=1, ge=0, le=1)
    language: str = "zh"


def create_bridge(infer: Callable[..., Any], reference_root: Path) -> FastAPI:
    """Expose a serialized inference API with references confined to one directory."""
    root = reference_root.resolve(strict=True)
    lock = threading.Lock()
    app = FastAPI(title="ArcReel IndexTTS2 local bridge")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"adapter": "arcreel-indextts2", "model": "IndexTTS2", "status": "ready"}

    @app.post("/synthesize")
    def synthesize(payload: SynthesisPayload) -> Response:
        reference = root / payload.reference_audio
        if Path(payload.reference_audio).is_absolute() or any(
            part in ("..", ".") for part in Path(payload.reference_audio).parts
        ):
            raise HTTPException(422, "Reference must be a relative filename below the reference root")
        current = root
        for part in Path(payload.reference_audio).parts:
            current = current / part
            if current.is_symlink():
                raise HTTPException(422, "Symlink references are not supported")
        try:
            reference = reference.resolve(strict=True)
            reference.relative_to(root)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, "Reference audio was not found below the configured root") from exc
        if not reference.is_file():
            raise HTTPException(422, "Reference audio is not a file")
        request = BookSynthesisRequest(
            text=payload.text,
            output_path=Path("unused.wav"),
            reference_audio=payload.reference_audio,
            emotion_vector=payload.emotion_vector,
            emotion_text=payload.emotion_text,
            emotion_intensity=payload.emotion_intensity,
            language=payload.language,
        )
        try:
            validate_controls(
                request, SpeechCapabilities(emotion_vector=True, emotion_description=True, reference_audio=True)
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with lock, tempfile.TemporaryDirectory(prefix="arcreel-indextts2-") as directory:
            output = Path(directory) / "speech.wav"
            kwargs: dict[str, Any] = {
                "spk_audio_prompt": str(reference),
                "text": payload.text,
                "output_path": str(output),
                "use_random": False,
            }
            if payload.emotion_vector:
                kwargs["emo_vector"] = [v * payload.emotion_intensity for v in payload.emotion_vector]
            if payload.emotion_text:
                kwargs.update(use_emo_text=True, emo_text=payload.emotion_text, emo_alpha=payload.emotion_intensity)
            infer(**kwargs)
            return Response(output.read_bytes(), media_type="audio/wav")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=7861)
    args = parser.parse_args()
    # This optional integration runs inside the official model environment, not ArcReel's dependency set.
    module = importlib.import_module("indextts.infer_v2")
    model = module.IndexTTS2(
        cfg_path=str(args.model_dir / "config.yaml"),
        model_dir=str(args.model_dir),
        use_fp16=False,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )
    import uvicorn

    uvicorn.run(create_bridge(model.infer, args.reference_root), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
