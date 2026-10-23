---
id: voxcpm2
title: Local VOX voice adapter
sidebar_position: 6
update_docs: fact-check
---

# Local VOX voice adapter {#voxcpm2}

VoxCPM2 generates character speech; it does not replace chapter planning, character assets or scene audio tracks. Dialogue, speaker identity and performance intent remain part of the original chapter workflow, with source text stored separately from directions. Rain, footsteps and door sounds belong to separate assets and timeline tracks, not fictional capabilities of the speech model.

## Cloning modes {#cloning}

- **Controllable cloning** uses a reference voice with natural-language emotion and delivery directions. It suits a recurring character performing different scenes.
- **Continuation cloning** requires an exact reference transcript and follows the reference recording's rhythm, emotion and delivery. Extra performance directions are rejected in this mode instead of mixing incompatible controls.

VOX directions are not IndexTTS emotion vectors or exact numeric speed/intensity controls. At the official model boundary, controllable cloning prefixes directions in parentheses, as required by the upstream API. Stored source text stays unchanged. This convention cannot guarantee the model never speaks a direction, so audition remains necessary. Exact speed/intensity and native breath/laughter tags are not advertised as supported; requests fail rather than silently dropping them. Natural-language requests for pace or expression remain best effort. Explicit inter-segment pauses are rendered as silence by the timeline rather than guessed by the model.

## Deployment boundary {#deployment}

This adapter connects to the optional `scripts/book/vox_bridge.py` provided by this repository. It does not assume third-party VOX servers share the same HTTP API. Inspect an existing deployment's contract before attempting integration.

Run the bridge inside an independently prepared official VoxCPM2 environment, pointing to existing local VoxCPM2 model files. The bridge does not download models, create credentials or start a server on import. Reference audio uses paths relative to a read-only reference directory; traversal, missing files and symlinks are rejected.

```bash
PYTHONPATH=/path/to/ArcReel:$PYTHONPATH python /path/to/ArcReel/scripts/book/vox_bridge.py \
  --model-dir /path/to/VoxCPM2 \
  --reference-root /path/to/ArcReel/projects \
  --port 7862
```

The server binds only to `127.0.0.1`. It is not an authentication solution for a public endpoint. Separate NAS and model hosts need an independently secured connection configured by the deployer. Select the `voxcpm2` adapter, an explicit VoxCPM2 model and the bridge URL. Use reference voices only with the appropriate rights. Continuation mode also requires the reference transcript. Mode and generation settings belong to the persistent voice configuration and invalidate the affected speech cache when changed.

The bridge verifies the model architecture and encodes native 48 kHz WAV rather than mislabeling an older model or another service. A fixed seed helps reproduce settings but does not promise bit-identical output across model versions, hardware or runtimes. Update the voice asset digest and regenerate after replacing reference audio; an unchanged filename does not establish unchanged content.

## Quality acceptance {#acceptance}

Use real references to assess ordinary speech, common emotions, pauses, elongation and nonverbal expression, including cross-line voice stability, source fidelity and directions not being spoken. Breath, crying and laughter may be explored as natural-language intent, but a successful request does not prove these effects are reliable or accepted. Record shortcomings or use authorized audio assets; never silently substitute a model or voice.

Repository tests cover protocol mapping, capability rejection, 48 kHz encoding, path constraints and failure propagation. They do not run the local model or establish human-like voice reproduction quality.

Official references: [VoxCPM project](https://github.com/OpenBMB/VoxCPM), [Python API](https://github.com/OpenBMB/VoxCPM/blob/main/src/voxcpm/core.py), [CLI cloning constraints](https://github.com/OpenBMB/VoxCPM/blob/main/src/voxcpm/cli.py).

For voices bound to existing character assets, mount the same ArcReel projects directory read-only as the bridge reference root. The service sends project-name/project-relative-audio-path. Manually configured voices remain relative to that root without an automatic project prefix. Bound assets are content-hashed: replacing the file at the same path requires resync and invalidates affected speech. For independent manual references, update the configured digest when the reference changes.
