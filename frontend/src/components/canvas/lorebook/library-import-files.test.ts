import { describe, expect, it } from "vitest";
import { selectManifestFiles } from "./library-import-files";

const manifest = JSON.stringify({ schema_version: 1, library_id: "synthetic", entries: [{ views: [{ file: "front.png" }, { file: "front.png" }], voice: { clips: [{ file: "voice.wav" }] } }] });

describe("selectManifestFiles", () => {
  it("uploads each referenced file once without transmitting unrelated folder content", () => {
    const front = new File(["synthetic"], "front.png");
    const voice = new File(["synthetic"], "voice.wav");
    expect(selectManifestFiles(manifest, [front, new File(["private"], "unrelated.txt"), voice])).toEqual({ files: [front, voice], error: null });
  });

  it("rejects duplicate referenced basenames instead of guessing the source directory", () => {
    const result = selectManifestFiles(manifest, [new File(["one"], "front.png"), new File(["two"], "front.png"), new File(["voice"], "voice.wav")]);
    expect(result).toEqual({ files: [], error: "duplicate", names: ["front.png"] });
  });

  it("reports absent references, including files omitted by a directory picker", () => {
    expect(selectManifestFiles(manifest, [new File(["front"], "front.png")])).toEqual({ files: [], error: "missing", names: ["voice.wav"] });
  });

  it.each(["invalid json", "null", '{"entries":[null]}', '{"entries":[{"views":[{"file":"/Users/synthetic/front.png"}]}]}', '{"entries":[{"views":[{"file":"..\\\\front.png"}]}]}'])("rejects invalid or path-based file references: %s", (input) => {
    expect(selectManifestFiles(input, [])).toEqual({ files: [], error: "manifest", names: [] });
  });
});
