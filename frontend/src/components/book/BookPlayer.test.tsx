import { describe, expect, it } from "vitest";
import { activeBookEvent } from "./BookPlayer";

describe("book audio clock", () => {
  it("switches illustrations on the exact anchor, and reverses on backward seeking", () => {
    const frames = [{ id: "first", start_seconds: 0 }, { id: "second", start_seconds: 4.25 }];
    expect(activeBookEvent(frames, 4.24)?.id).toBe("first");
    expect(activeBookEvent(frames, 4.25)?.id).toBe("second");
    expect(activeBookEvent(frames, 1)?.id).toBe("first");
  });
  it("uses updated timing after speech changes, independently of playback speed", () => {
    const frames = [{ id: "first", start_seconds: 0 }, { id: "second", start_seconds: 7.5 }];
    expect(activeBookEvent(frames, 6)?.id).toBe("first");
    expect(activeBookEvent(frames, 7.5)?.id).toBe("second");
    expect(activeBookEvent(frames, -1)).toBeUndefined();
  });
});
