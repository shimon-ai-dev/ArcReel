---
id: book-modes
title: Audiobooks and illustrated audiobooks
sidebar_position: 5
update_docs: fact-check
---

# Audiobooks and illustrated audiobooks {#book-modes}

The goal is natural, complete chapter audio, optionally accompanied by the original storyboard images. Both modes extend the existing novel/chapter workspace rather than introducing a parallel chapter or keyframe workspace.

Select `audiobook`, `illustrated_audiobook`, or the existing `video` output at creation. The output mode is fixed afterward; older projects without this field remain video projects. Follow the [deployment guide](../ops/deployment.md), back up data, and update frontend and backend from the same branch. This does not automatically change a NAS or model service.

## Use the existing workspace {#audiobook}

1. Import a novel or chapter through the original interface. Keep its chapter navigation, breakdown review, character/scene assets, and right-side Agent. Original chapters and formal scripts remain authoritative.
2. The built-in breakdown preserves the full source within original storyboard units and annotates speakers, performance intentions, pauses, and separate sound cues. Annotations must match exact source spans; emotion and sound directions never become spoken text. Unconfirmed speakers require review.
3. Synchronize the reviewed chapter in its audio area and configure narrator/character voices. Existing character voice references can be reused. Changes to original chapters, voice references, or storyboards require synchronization; an older export cannot certify the changed content.
4. Generate missing or stale speech and listen before exporting. Evaluate stable cloned identity, natural ordinary speech, emotions, pauses, elongation, breathing, crying, and laughter. Recording an intention does not establish provider support or acceptable output.
5. Ambience, effects, and music use separate tracks. Breakdown cues are intentions, not generated files. Supply authorized media and configure mixing, ranges, and speech ducking.

Audiobooks skip image and video stages and need neither model type. Timing comes from actual audio lengths and explicit silence, not video duration tiers.

## VOX and capability boundaries {#local-tts}

The [VoxCPM2 guide](./voxcpm2.md) describes its actual interface, reference audio, and limitations. Do not pass another TTS model's controls to VOX or advertise IndexTTS2 emotion vectors/tags as VOX features. Generic TTS, the optional IndexTTS2 bridge, and VOX have separately verified capabilities. Unsupported controls must fail explicitly, not silently disappear or switch the voice.

The deployer supplies model installations, weights, service configuration, and authorization. ArcReel does not automatically download models, sign in, or create credentials. Endpoint availability and contract tests are not real-model or listening acceptance.

## Reuse original storyboard images {#illustrated}

Illustrated audiobook images are the existing storyboard images. Use the original image provider, character/scene/prop references, and storyboard generation, then synchronize audio playback anchors. Do not create a second keyframe generator. See the [ComfyUI guide](./comfyui.md). Video generation, video editing timelines, and MP4 stages are skipped; the original video mode remains unchanged.

The visual goal is realistic live-action character and scene continuity rather than a default anime appearance. Multi-angle portraits, full-body views, and base views must respect the actual provider's reference-image capability. Accepting multiple images is not proof of visual consistency.

## Reuse a local multi-view library {#local-library}

Import and update previews live in the original character/scene asset panels. On a computer that can read the library, run the read-only converter against the library root containing both published entries and archive content. It reads existing indexes, approval evidence and safe links to generate a portable bundle; users do not hand-author a new manifest. Select that generated folder in the original asset panel, inspect additions, changes, conflicts and pending voice applicability, then confirm. See [existing library bundles](./existing-library-bundles.md) for the command and supported dialect.

Archive versions, product versions, character baselines, looks and scene states remain separate. The converter never edits sources; missing sources do not delete existing project references. Frozen content cannot change within the same version. Explicitly selecting a different version requires preview and retains old content. Technical voice checks do not imply listening, model adaptation or clone-quality acceptance. Unconfirmed voice-to-baseline applicability never silently activates a voice.

Original storyboard generation uses explicitly confirmed views and requires a character identity anchor. It allocates references across characters/scenes and preceding-frame continuity before additional shot-appropriate headshot, full-body and appearance views. Prompts distinguish identity, clothing and pose roles. Actual provider capacity determines the limit; existing prompt previews and receipts identify sent and omitted views rather than promising all seven views are forwarded.

A browser folder selection does not mount an arbitrary computer path on the NAS. Published entries may link to archives outside the product folder, so choose the full library root; the converter rejects escapes. Synthetic fixtures verify this implementation, not actual-library conversion, NAS mounts or real-model image consistency.

## Export and verification {#verification}

Export chapter and whole-book WAV/MP3. Illustrated output also includes a ZIP with audio, original storyboard images, a manifest, and an HTML player. Extract and open index.html; if the browser restricts local media, serve the extracted directory with a local static server. The player supports pause, seeking, chapters, and playback rate, with images following actual audio time.

Missing, failed, stale, or incomplete speech prevents valid completion. Export validates actual media, digests, and receipts; replaced or damaged resources invalidate an older completion proof.

An existing synthetic package passed Chromium playback, pause, forward/backward image seeking, chapter switching, and playback-rate retention in GitHub Actions. Evidence is in repository `docs/verification/book-modes-2026-10-21.md`. Unit/integration tests cover contracts, source spans, original-workflow branches, mixing, and ffmpeg encoding/decoding. These are engineering fixtures, not real TTS or image-quality acceptance.

Real VOX listening, image consistency, and local asset-library compatibility still need actual services and authorized media. This stage excludes M4B, automatic ambience generation, full-video acceptance, and automatic voice-quality scoring.
