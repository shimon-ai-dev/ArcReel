import { describe, expect, it } from "vitest";
import { planBookKeyframes } from "./keyframe-plan";
import type { BookDocument, BookSegment } from "@/types/book";

const segment = (id: string) => ({ id, text: `原文${id}` } as BookSegment);
const book: BookDocument = { schema_version: 1, revision: 1, title: "", original_text: "", normalized_text: "", voices: {}, effects: [],
  chapters: [{ id: "one", title: "", segments: [segment("a"), segment("b"), segment("c")] }, { id: "two", title: "", segments: [segment("d"), segment("e")] }],
  keyframes: [{ id: "existing", segment_id: "a", offset_seconds: 0, prompt: "Keep custom prompt", path: "image.png", provider: null, model: null, reference_paths: [], status: "succeeded", task_id: null, error: null }],
};

describe("keyframe density planning", () => {
  it("preserves existing images and adds interval anchors starting every chapter", () => {
    const frames = planBookKeyframes(book, 2);
    expect(frames.map((frame) => frame.segment_id)).toEqual(["a", "c", "d"]);
    expect(frames[0]).toBe(book.keyframes[0]);
    expect(frames[2].prompt).toBe("原文d原文e");
    expect(planBookKeyframes({ ...book, keyframes: frames }, 2)).toEqual(frames);
  });
  it("rejects invalid density without changing drafts", () => {
    for (const value of [0, -1, NaN, 1.5]) expect(planBookKeyframes(book, value)).toBe(book.keyframes);
  });
});
