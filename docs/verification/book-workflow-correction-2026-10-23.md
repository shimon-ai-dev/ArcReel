# Original-workflow book-mode correction

## Product goals

- Keep the existing novel/chapter import, planning, review, storyboard, character/scene/prop assets, Studio layout and Agent.
- Illustrated audiobook pictures are the existing storyboard images. Skip video generation and editing; do not create another keyframe pipeline. Pure audiobook additionally skips visual requirements.
- Preserve every source character. Original chapter breakdown records speakers, natural-language performance intentions, pauses and separately anchored scene-sound intentions.
- Prioritize stable cloned voices and natural speech/emotion. Elongation, breathing and crying/laughter are listening goals, not promises of native provider controls.
- Prioritize live-action/drama appearance and character/scene continuity rather than default anime styling.
- Reuse the researched product/archive library structure through a read-only converter and explicit project-asset import preview. Preserve separate baseline, look, archive/product version and voice-applicability evidence; never invent approval.

## Implemented correction

The shared Studio routes remain authoritative. Chapter audio/listen tabs synchronize the registered original episode source and formal script into the existing audio/mixing/export engine. The standalone BookWorkspace route is removed. Legacy book documents are preserved in a full JSON archive when first synchronized; generated files are not deleted.

Original storyboard generation retains the existing style, character/scene/prop reference and preceding-frame machinery. Synchronized book tasks cannot invoke the divergent legacy keyframe renderer. Audio timelines reference original storyboard IDs and files.

The original LLM planning schemas persist exact source-bound speech and sound annotations through original materialization. Unannotated source is preserved, not summarized. Whitespace remains in neighboring spoken spans instead of becoming an invalid independent utterance.

VoxCPM2 has an explicit optional local bridge using the official Python API contract. Controllable cloning and transcript continuation are separate modes. Unsupported numeric emotion/speed and native nonverbal controls fail clearly. Scene-sound intentions require real assets before export; they are not fabricated sound files.

Original character voice references are project-bound and content-hashed. Changed source, annotations, storyboard images or character audio require resynchronization; stale exports cannot mark current work complete. Empty book annotations and absent legacy output modes do not mutate old video identities.

## Local-library integration

A read-only local converter follows existing product indexes to in-root archive records and verified media. It recognizes separate image and voice approval dialects and per-file scene confirmation in Markdown; stale product labels or paths do not override the current safe target and content digest. Unknown pointers, conflicting versions, missing files or hash/boundary failures remain preview blockers. No source candidate material or private example library is bundled into the repository.

The original character/scene panels preview generated bundles before applying them. Project assets retain external identity, baseline/look/state, independent archive/product versions, labeled views and provenance. Updates preserve missing source records and historical frozen versions. Pending voice applicability cannot become an active character voice. Confirmed reference transcripts propagate to the existing VOX profile and invalidate stale speech when changed.

Original non-grid storyboard images use confirmed imported identity/appearance/space views directly. Selection balances identities, scenes and preceding-frame continuity under the actual backend limit; prompt preview and execution share role/view labels and report selected/omitted references. Legacy video/grid routes are not silently expanded. ComfyUI rejects direct reference overflow before uploads.

## Evidence and remaining acceptance

Contract tests cover original planning/materialization, source fidelity, chapter/storyboard reuse, VOX HTTP forwarding, reference replacement, stale export guards and legacy preservation. These use fixture model responses, not real synthesis.

The branch workflow runs fixture-only Studio journeys at desktop and compact viewport sizes and archives screenshots/traces. Its actual run result must be checked before claiming UI acceptance. Local Chromium execution was unavailable in the execution environment.

Still unverified: actual local VoxCPM2 voice similarity and expressive quality; actual image-model character/scene consistency; real-library conversion/import on the user's selected machine, actual NAS mounts and model service availability. No user NAS deployment, credentials, model downloads or real paid model calls are part of this change. A browser-selected directory upload is not equivalent to a NAS-mounted server path.
