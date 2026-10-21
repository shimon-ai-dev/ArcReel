import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BookPlayer } from "./BookPlayer";
import type { BookDocument, BookExports, BookTimeline } from "@/types/book";

const book: BookDocument = {
  schema_version: 1, revision: 1, title: "示例", original_text: "", normalized_text: "", voices: {}, effects: [],
  chapters: [{ id: "one", title: "第一章", segments: [] }, { id: "two", title: "第二章", segments: [] }],
  keyframes: [
    { id: "a", segment_id: "s1", offset_seconds: 0, prompt: "雨中街道", path: "a.png", provider: null, model: null, reference_paths: [], status: "succeeded", task_id: null, error: null },
    { id: "b", segment_id: "s2", offset_seconds: 0, prompt: "推开房门", path: "b.png", provider: null, model: null, reference_paths: [], status: "succeeded", task_id: null, error: null },
    { id: "c", segment_id: "s3", offset_seconds: 0, prompt: "次日清晨", path: "c.png", provider: null, model: null, reference_paths: [], status: "succeeded", task_id: null, error: null },
  ],
};
const timeline: BookTimeline = {
  duration_seconds: 15, missing_segment_ids: [], effects: [],
  segments: [
    { id: "s1", chapter_id: "one", start_seconds: 0, duration_seconds: 4, pause_after_seconds: 1, audio_path: "s1.wav" },
    { id: "s2", chapter_id: "one", start_seconds: 5, duration_seconds: 5, pause_after_seconds: 0, audio_path: "s2.wav" },
    { id: "s3", chapter_id: "two", start_seconds: 10, duration_seconds: 5, pause_after_seconds: 0, audio_path: "s3.wav" },
  ],
  keyframes: [
    { id: "a", chapter_id: "one", start_seconds: 0, duration_seconds: 5, path: "a.png" },
    { id: "b", chapter_id: "one", start_seconds: 5, duration_seconds: 5, path: "b.png" },
    { id: "c", chapter_id: "two", start_seconds: 10, duration_seconds: 5, path: "c.png" },
  ],
};
const exports: BookExports = { chapters: [{ id: "one", path: "one.wav", duration_seconds: 10 }, { id: "two", path: "two.wav", duration_seconds: 5 }], whole_book_path: "whole.wav", archive_path: "book.zip", manifest_path: "manifest.json", player_path: "index.html" };

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(new Blob(["fixture"]), { status: 200 })));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:audio-fixture"), revokeObjectURL: vi.fn() }));
});
afterEach(() => vi.unstubAllGlobals());

describe("illustrated book synchronization", () => {
  it("changes illustrations when seeking backwards and forwards, changing rate, and changing chapter", async () => {
    const user = userEvent.setup();
    render(<BookPlayer project="demo" book={book} timeline={timeline} exports={exports} />);
    expect(await screen.findByRole("img", { name: "雨中街道" })).toBeVisible();
    const audio = await screen.findByLabelText<HTMLAudioElement>("章节同步播放器", { selector: "audio" });
    fireEvent.seeking(audio, { target: { currentTime: 6 } });
    expect(await screen.findByRole("img", { name: "推开房门" })).toBeVisible();
    fireEvent.seeked(audio, { target: { currentTime: 1 } });
    expect(await screen.findByRole("img", { name: "雨中街道" })).toBeVisible();
    await user.click(screen.getByRole("combobox", { name: "播放速度" }));
    await user.click(await screen.findByRole("option", { name: "1.5×" }));
    expect(audio.playbackRate).toBe(1.5);
    fireEvent.rateChange(audio, { target: { currentTime: 6 } });
    expect(await screen.findByRole("img", { name: "推开房门" })).toBeVisible();
    await user.click(screen.getByRole("combobox", { name: "章节与发言段" }));
    await user.click(await screen.findByRole("option", { name: "第二章" }));
    expect(await screen.findByRole("img", { name: "次日清晨" })).toBeVisible();
    const secondAudio = await screen.findByLabelText<HTMLAudioElement>("章节同步播放器", { selector: "audio" });
    fireEvent.loadedMetadata(secondAudio);
    await waitFor(() => expect(secondAudio.playbackRate).toBe(1.5));
  });
});
