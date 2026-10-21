import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BookPronunciation } from "./BookPronunciation";
import type { BookSegment } from "@/types/book";

const segment: BookSegment = {
  id: "rare", source_start: 10, source_end: 14, text: "𠀀重庆😀", speaker_id: "narrator", speaker_confirmed: true,
  performance: { emotion: null, intensity: 1, emotion_vector: null, style: null, speed: null, nonverbal: null },
  pause_after_seconds: 0, pronunciation: [], audio_versions: [], selected_audio_version: null, status: "pending", task_id: null, error: null,
};

describe("pronunciation codepoint offsets", () => {
  it("keeps non-BMP Han intact and aligns following Chinese with Python source offsets", async () => {
    const changed = vi.fn();
    function Form() {
      const [items, setItems] = useState<BookSegment["pronunciation"]>([]);
      return <BookPronunciation segment={{ ...segment, pronunciation: items }} disabled={false} update={(next) => { setItems(next); changed(next); }} />;
    }
    const user = userEvent.setup();
    render(<Form />);
    await user.click(screen.getByText("发音修正"));
    await user.click(screen.getByRole("button", { name: "添加发音映射" }));
    expect(changed.mock.lastCall?.[0]).toEqual([{ source_start: 10, source_end: 11, original: "𠀀", spoken: "𠀀" }]);
    fireEvent.change(screen.getByLabelText("结束字符位置（不含）"), { target: { value: "13" } });
    fireEvent.change(screen.getByLabelText("起始字符位置"), { target: { value: "11" } });
    expect(changed.mock.lastCall?.[0][0]).toMatchObject({ source_start: 11, source_end: 13, original: "重庆" });
    fireEvent.change(screen.getByLabelText("结束字符位置（不含）"), { target: { value: "14" } });
    fireEvent.change(screen.getByLabelText("起始字符位置"), { target: { value: "13" } });
    expect(changed.mock.lastCall?.[0][0].original).toBe("😀");
  });
});
