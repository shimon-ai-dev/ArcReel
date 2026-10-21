# Book modes implementation and verification (2026-10-21)

## Scope and architecture

Based on official ArcReel commit `231649fa8d1442ff0f6a49f4cd8689563865da46`, feature branch `feat/book-output-modes`. Upstream licenses, notices and attribution remain intact.

- `output_mode` is independent of `content_mode` and `generation_mode`. Missing values read as `video`; existing project files need no destructive rewrite. Persisted mode changes are rejected atomically.
- `lib/book` owns source-preserving chapters/segments, stable source offsets, pronunciation overrides, persistent voices, separate performance controls, asset versions, anchored events and export freshness. It does not derive timings from video frames or `video_version`.
- `lib/book_audio` implements explicit TTS capability validation, deterministic sample-count pauses, separate effects/ambience/music mixing and WAV/MP3 export. The opt-in local IndexTTS2 bridge is in `scripts/book/index_bridge.py`, outside the core-library HTTP layer.
- Existing provider resolution, backend assembly, durable generation queue/worker and retry mechanisms are reused. Audio and image histories are persisted independently. Stale queued requests are rejected; an in-flight old result can retain history but cannot take ownership of newer text or voice settings.
- `book_project` and REST endpoints share the same command service. Book workflow readiness requires complete current audio and, for illustrated output, images plus a current verified export receipt. Text coverage and listening quality remain distinct.
- The frontend routes book projects to an independent workspace. It supports character assignment, voices, performance, pause, pronunciation, explicit source correction, effects audition/replacement/deletion, fades/loop/ducking, keyframe density/reference paths, generation/retry and audio-clock playback/export. All new app labels are provided in Chinese, English and Vietnamese.

## Verification performed

The following use real internal project persistence, SQLite queue, provider resolution and worker code. HTTP model boundaries are intercepted in automated tests. Synthetic waveforms are not real model output.

Backend command:

```sh
.venv/bin/pytest tests/unit/lib/book tests/unit/lib/book_audio \
  tests/integration/lib/book_audio tests/integration/server/services/book \
  tests/integration/server/routers/test_books.py tests/unit/server/test_book_tools.py -q
```

Result: **65 passed**, with two upstream deprecation/reflection warnings.

Coverage includes:

- exact source preservation, missing/duplicate/reordered source rejection, stable IDs and local source corrections;
- chapters, shared voices, separate pronunciation mappings and synthesis cache identities;
- TTS HTTP/official Python parameter contracts, unsupported-control rejection and visible failure;
- real WAV/MP3 encoding, chapter and whole-book audio, silence length, ducking, loops, cross-chapter fades;
- actual DB/provider/resolver/ComfyUI adapter path with two generated HTTP-fixture images;
- illustrated manifest/HTML package, source-duration changes retiming sound and image events, stale export rejection;
- reopen/retry preserving successful versions, concurrent edits, late success/failure, stale queued provider changes and enqueue/worker races;
- authenticated REST caller, task listing, optimistic conflict, asset validation and path protection;
- old-data output default and immutable output mode.

Frontend book suite: **9 passed across 6 files**.

```sh
cd frontend
node_modules/.bin/vitest run src/components/book/*.test.ts src/components/book/*.test.tsx src/components/pages/CreateBookProjectModal.test.tsx
```

Frontend checks use `tsc --noEmit`, targeted ESLint, Vite production build, and focused book-only Vitest suites. DOM tests cover creation without image/video providers, audio seek/backseek, rate retention, chapter image changes, retiming, voice adapter switching and non-destructive keyframe density planning.

Static checks passed: Ruff, format, all nine import-layer contracts, dependency hygiene, repository convention/test audits, and focused basedpyright for all new core/service/router/Agent/bridge modules (zero errors/warnings). Website full check passed; a bounded-heap `docusaurus build --no-minify` successfully built both Chinese and English routes with no broken links/anchors. Seven documentation-tool tests passed. The final whole-repository basedpyright attempt exited 247 without diagnostics; the standard website production build exited 137 with Killed. These runs are not recorded as passes. Exact final results and logs accompany the delivered archive.

Per the user's later instruction, dedicated video-mode tests and real video generation were intentionally not run. Existing video code paths and validations were retained, but this delivery does not claim video regression acceptance.

## Actual-model and browser acceptance not passed

- No usable local TTS or ComfyUI model service/GPU was available in this environment. Local IndexTTS2 synthesis and local ComfyUI inference remain unverified.
- The official hosted IndexTTS2 public demo accepted a test request but returned `ZeroGPU quota exceeded`; no audio was produced. Hosted-demo availability is not local-deployment proof.
- Fish's hosted free endpoint needs account credentials. Credentials were not created or configured, and no paid fallback was used. Fish is not claimed as an implemented/tested book adapter.
- Native Chromium could not launch under the current sandbox; the alternate cloud-browser attempt did not complete. Actual unpacked-package browser playback is not claimed. DOM tests and a production build do not substitute for that acceptance step.
- No human/model listening evaluation has passed. Text coverage does not establish correct pronunciation, emotion, actor identity or voice quality.
- GitHub fork/push depends on the authorized user's sign-in. Local commits/source bundles do not establish that a fork was created or pushed.

## Example and limitations

`examples/book-modes/rainy-night.txt` contains original sample prose with narration, two characters, surprise, a gasp, pauses, footsteps and rain. Its README gives a reproducible actual-model acceptance procedure. `scripts/book/make_fixture.py` generates a clearly labelled synthetic audio/color-image engineering package, not a finished spoken audiobook.

Importer speaker attribution is deliberately conservative: narration/unconfirmed until corrected by the user or Agent. IndexTTS2 declares Chinese/English, reference audio, emotion vectors or emotion text. It does not claim native speed or nonverbal controls; supplied sound effects must carry provenance and voice-consistency caveats. Replacing an external reference audio file under the same name requires updating the voice reference digest/version so cached speech invalidates.

M4B, automatic sound-effect synthesis and slideshow-video conversion remain outside this first-version scope. The local bridge is loopback-only and does not configure remote authentication or network access. Mixing uses 24 kHz mono output and processes individual chapters in memory; unusually long chapters should be split. Image/voice quality, production-scale performance, and actual browser/model acceptance remain required before calling the full requested acceptance complete.
