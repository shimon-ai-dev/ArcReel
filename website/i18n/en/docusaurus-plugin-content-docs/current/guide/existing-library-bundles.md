---
id: existing-library-bundles
title: Import an existing local asset library
sidebar_position: 6
update_docs: fact-check
---

# Import an existing local asset library {#existing-library-bundles}

Import existing characters and scenes in the original asset panels without writing a new JSON manifest or creating a separate workspace. The converter reads the existing product indexes, archive approval records, and safe links, then produces a portable directory for the browser to upload.

## Local conversion and preview {#local-conversion}

On a computer authorized to read the library, with this branch's ArcReel development dependencies installed, run from the repository:

```bash
uv run python -m scripts.book.prepare_library_bundle "/path/to/existing-library"
```

Without `--output`, this prints a JSON preview and creates no files. Select the complete library root containing both `成品` and the `characters` / `scenes` archives, not only the published-products subdirectory.

After reviewing the preview, choose a new output directory outside the source library:

```bash
uv run python -m scripts.book.prepare_library_bundle "/path/to/existing-library" \
  --library-id "my-character-library" \
  --output "/path/to/new-portable-bundle"
```

Keep `--library-id` stable for subsequent updates. Its default is the selected root directory's name; specify it explicitly if that directory might be renamed or different libraries share a name. To select only certain existing product entries, repeat `--entry person-9001 --entry scene-9002`. Replace these fictitious IDs with actual product-entry directory names. The selected root must still include the archives.

A successful output contains:

- `library-manifest.json`: the generated upload manifest and relative provenance paths.
- SHA-256-named images and audio: only selected media, deduplicated by content.
- `preview.json`: entries, provenance, unresolved states, and warnings; it is not uploaded.

Select the generated directory in the original character or scene asset panel, review additions, updates, conflicts, and pending voice relationships, then confirm the import. Alternatively, select the manifest and its referenced media files individually. The converter never uploads, deploys, connects a NAS, or updates a project. Project changes happen only after confirmation in the asset panel.

Any blocker produces exit code `2`. With an output directory, only `preview.json` is written, with no importable manifest or media. Inspect the source location, line, and reason, correct the selection or provide a redacted format example, then use another new output directory. Do not edit the generated manifest to bypass provenance conflicts.

## Supported existing layouts and records {#supported-layout}

Entries begin at `成品/人物/person-NNNN/索引.md` and `成品/场景/scene-NNNN/索引.md`. The parser supports the following explicit table and field dialects, not arbitrary Markdown, registries, or historical formats:

- Character indexes: `分类 / 文件 / 成品V / 精确来源版本 / 确认范围`. Exact source pointers identify the person, baseline, look, action, archive version, and file. Image approvals live at `characters/person-NNNN/packs/baseline-NNN_look-NNN_action-NNN/vNNN/approval.json`, using `files[].archive / product / sha256 / slot / width / height / frozen / user_confirmed`.
- Voice archives: `characters/person-NNNN/voices/voice-NNN/vNNN/approval.json`. Identity fields are `person / voice / version`, with `files[].path / role / sha256`. Verified matching transcripts can be embedded beside selected clips; transcripts are not additional upload files. Historical absolute `product` paths are not read.
- The character registry, `character.md`: matching `包` or `声音设定` rows are checked against their `最后已批准版本` links. A voice baseline is confirmed only when `适用 baseline` is exactly one `baseline-NNN` identifier. Pending or undecided prose remains pending.
- Scene indexes: direct source links in `成品文件 / 精确来源包与文件 / SHA-256`, or `分类 / 文件 / 成品版本 / 确认范围 / 来源与记录` linking to `scene-assets/asset-map.md`. The latter requires the current safe product link to identify the archive object, then its exact `views/...` section and SHA-256 in the map. Stale publication links in that map do not replace the current product entry.

Explicit current recommendations and product rows determine selection, never the highest version or newest modification time. Multiple selected versions of the same character variant or scene state, registry/index conflicts, and unknown pointer formats block export. A display entry can reference another scene's archive object: the archive's scene ID is preserved instead of treating the display grouping as its identity.

## Safety and approval boundaries {#safety}

- Sources are read-only. Output must be outside the library and must not overwrite an existing directory.
- Product symlinks must resolve within the same selected root. Escapes, broken links, and inconsistent content block export. Select the complete root containing the archives rather than disabling this boundary.
- Only selected index references and matching voice transcripts are processed. Work candidates, `source_candidate`, credentials, full index documents, and unrelated files are not copied.
- Person ID, baseline, look, action, scene state, archive version, and product version remain independent. `action-000` is retained as a normal static-action identifier.
- Per-file confirmation, per-file freezing, and whole-pack approval remain separate. A scene pack marked `validated` does not thereby become approved. Successful decoding or matching hashes do not imply user confirmation.
- Voice technical validation, listening, model adaptation, and clone testing remain separate. A pending voice baseline produces a standalone voice entry rather than inheriting an image baseline. Import preview continues to show this limitation.
- Missing source or project references are not deleted. The project importer protects frozen content within the same version; explicit upgrades to different versions require preview and retain history.

## Verification and limitations {#validation}

Supported images are PNG, JPEG, and WebP, up to 40 million pixels. Voice references must be nonempty mono or stereo PCM WAV. Limits are 20 MiB per file, 200 media files, and 128 MiB per bundle. Use `--entry` to process larger catalogs in batches, with a new output directory each time.

Conversion verifies source SHA-256 hashes, image dimensions and decoding, and audio completeness, then verifies content again while exporting. Project preview and apply verify the uploaded content again. Hash checks do not establish visual consistency, voice-cloning quality, or permission to use the material.

Tests use fictitious IDs, temporary directories, and synthetic media. They do not establish compatibility with every real registry dialect, access to a user's actual local paths, NAS mounts, model output quality, or human listening acceptance. For an unknown dialect, supply the smallest redacted index/approval example needed to explain the structure, not credentials, complete ledgers, or private media.
