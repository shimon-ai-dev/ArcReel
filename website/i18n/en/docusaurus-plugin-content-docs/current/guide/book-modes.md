---
id: book-modes
title: Audiobooks and illustrated audiobooks
sidebar_position: 5
update_docs: fact-check
---

# Audiobooks and illustrated audiobooks {#book-modes}

Choose an output mode when creating a project: audiobook (`audiobook`), illustrated audiobook (`illustrated_audiobook`), or the existing video mode (`video`). Output mode is independent of content mode and video generation mode and cannot be changed after creation. Existing projects without this field are read as video projects without rewriting their files.

## Startup and upgrades {#startup}

Back up your data and upgrade the backend and frontend using the [deployment guide](../ops/deployment.md). Development installation still uses `uv sync` and `uv run alembic upgrade head` at the repository root, and `pnpm install` in `frontend/`. Both backend and frontend must come from the same feature branch.

Book data lives in the project's `book/` directory and preserves the original and normalized text, chapters, stable speech segments, character voices, performance instructions, and historical audio versions. Reopen a project to continue generation or retry failed segments; retrying another segment does not delete successful outputs.

## Producing an audiobook {#audiobook}

1. Create an audiobook project and import the full novel. No image or video model configuration is required.
2. Review chapters and speech segments. All original text is retained by default, including chapter headings, narration, and phrases such as “he said.” Automatic splitting does not establish correct speaker identification; a person or Agent must review unconfirmed segments.
3. Configure voices for the narrator and characters, then confirm each segment's speaker. Character IDs refer to persistent voice profiles shared across chapters.
4. Set emotion, expression descriptions, and pauses after segments. Emotion is stored separately from the text and is not appended to the spoken content. Pronunciation corrections use independent replacement mappings tied to source positions, preserving the original text.
5. Generate and preview speech. Failed segments retain their errors and a retry option. Changing a voice or performance settings invalidates only affected segments; changing pauses recalculates only the timeline.
6. Import sound effects, ambience, or music and anchor them to speech segments with offsets. Set volume, fades, looping, and duration. Ambience and music are reduced during speech. Verify your rights to use each asset; its source is recorded in the event.
7. Export chapter and whole-book WAV or MP3 files. Missing, failed, or stale required speech blocks export. Source-text coverage and actual voice quality are separate checks: passing coverage does not establish correct pronunciation, emotion, or voice identity.

The timeline uses actual audio sample lengths and explicitly inserted silence, not video duration presets. Images and effects are anchored to speech segments and automatically retimed after regeneration. Effects spanning chapters preserve their loop phase and complete fade envelope instead of restarting at chapter boundaries. Fix effects extending beyond the whole book before exporting; export does not silently truncate them.

Export rereads actual audio lengths and verifies recorded speech digests. Completion receipts retain SHA-256 digests of source assets and exported files; replacing or corrupting a file invalidates completion. Images must decode successfully; a valid-looking filename extension is insufficient.

## Local emotional TTS {#local-tts}

The local emotional adapter connects to an optional IndexTTS2 bridge supplied by ArcReel. It calls the [official IndexTTS Python API](https://github.com/index-tts/index-tts), not an official upstream HTTP API. The bridge runs separately from ArcReel and does not automatically install models, download weights, or create credentials.

Prepare the IndexTTS2 environment and model weights following the upstream instructions, then install FastAPI, Uvicorn, and HTTPX in that environment for the bridge. Add the ArcReel repository to PYTHONPATH and run:

```bash
PYTHONPATH=/path/to/ArcReel:$PYTHONPATH python /path/to/ArcReel/scripts/book/index_bridge.py \
  --model-dir /path/to/checkpoints_2 \
  --reference-root /path/to/voices \
  --port 7861
```

The service listens only on `127.0.0.1`. Do not expose it directly to the public internet. Authentication, reverse proxies, and network permissions for cross-machine deployment must be configured separately by the operator. Voice references must reside inside the specified reference directory; only relative filenames are accepted, not paths escaping the directory or symbolic links. You must own or have permission to use the reference audio.

Select `indextts2` for the character voice, enter `http://127.0.0.1:7861` as the service URL, and use a reference filename such as `narrator.wav`. The bridge specifically uses the official `indextts.infer_v2.IndexTTS2`, not `infer_v2_5`; do not mix their weights or interfaces.

The adapter explicitly supports:

- Chinese and English, with a maximum of 1000 characters per segment; default import uses shorter segments.
- Voice cloning from reference audio.
- Eight-dimensional emotion vectors ordered as happy, angry, sad, afraid, disgusted, melancholic, surprised, and calm.
- Natural-language emotion descriptions converted through the model's emotion analysis without being added to the text.
- Emotion intensity and deterministic programmatically inserted pauses.

The adapter does not advertise speed control or native nonverbal tags for gasping, crying, or laughing. Unsupported controls fail explicitly rather than being silently ignored. Sourced sound effects can supplement nonverbal utterances, but cannot guarantee consistency with the cloned character's voice. Existing generic ArcReel TTS providers remain reusable with conservative capability declarations; an ordinary TTS provider is not assumed to support emotional control.

Successful installation, a reachable endpoint, and contract tests are not real-model validation. Actual generation and listening are required to confirm usability with a particular machine, weights, and voice reference.

## Producing and playing an illustrated audiobook {#illustrated}

Illustrated audiobooks reuse all audiobook functionality and add keyframes. Each image is anchored to a speech segment and remains visible across subsequent segments until the next image begins. Images need not correspond one-to-one with TTS segments. An image must be available at the start of each chapter; the last image of the previous chapter may carry over.

Choose an existing image provider or prepare a local image service using the [ComfyUI integration guide](./comfyui.md), then generate keyframes. Illustrated audiobooks do not query required video capabilities, generate MP4 files, or require video model configuration.

The exported ZIP contains chapter audio, whole-book audio, images, `manifest.json`, and `index.html`. Extract it and open `index.html`; the player embeds its manifest and does not depend on fetch access to a local JSON file. If your browser restricts local audio resources, run this in the extracted directory:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`. The player uses the audio clock to synchronize images and current text, with pause, seeking, playback speed, and chapter selection. Chapter changes preserve playback speed. If playback fails, the page displays instructions for serving the package locally.

## Verification and explicit limitations {#verification}

Real-model end-to-end generation and listening remain unverified and require usable model services and weights. A synthetic package passed actual Chromium playback, pause, forward/backward image seeking, chapter switching, and playback-rate retention in GitHub Actions. This does not establish real speech or image model quality. See `docs/verification/book-modes-2026-10-21.md` in the repository for evidence.

Unit tests check separation of emotion from text, capability rejection, bridge parameters, complete coverage, pauses, and mixing. Integration tests use real ffmpeg WAV/MP3 encoding and decoding and verify packages and completion receipts. Synthetic waveforms in tests are engineering fixtures, not TTS output.

Generate a reproducible player test package:

```bash
uv run python scripts/book/make_fixture.py /tmp/new-book-fixture
node scripts/book/check_player.mjs /absolute/path/to/unzipped/index.html
```

Browser checks use the frontend Playwright dependency. Set `CHROMIUM_EXECUTABLE` to select a system Chromium installation. The script checks image changes after seeking, chapter changes, and preservation of playback speed. Environments that have not actually run the browser or models cannot claim acceptance on that basis.

The first release does not include M4B, automatically generated effects, illustrated-audiobook slideshow video, or automatic assessment of pronunciation and character voice quality. Export mixes each chapter and writes the whole-book WAV chapter by chapter; split exceptionally long chapters to limit memory use.
