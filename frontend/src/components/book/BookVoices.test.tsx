import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BookVoices } from "./BookVoices";
import type { BookDocument } from "@/types/book";

const initial: BookDocument = {
  schema_version: 1, revision: 1, title: "测试", original_text: "", normalized_text: "", chapters: [], effects: [], keyframes: [],
  voices: { narrator: { id: "narrator", name: "旁白", adapter: "indextts2", model: "IndexTTS2", base_url: "http://127.0.0.1:7861", voice: "", reference_audio: "narrator.wav", reference_audio_digest: "old-digest", language: "zh", settings: {} } },
};

describe("book voice adapter controls", () => {
  it("clears incompatible parameters on adapter switch and shows only applicable fields", async () => {
    const changed = vi.fn();
    function Form() {
      const [book, setBook] = useState(initial);
      return <BookVoices book={book} disabled={false} capabilities={{}} onChange={(next) => { setBook(next); changed(next); }} />;
    }
    const user = userEvent.setup();
    render(<Form />);
    expect(screen.getByLabelText("本地服务地址")).toBeVisible();
    expect(screen.queryByLabelText("音色标识")).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "TTS 适配器" }));
    await user.click(screen.getByRole("option", { name: "已配置的 ArcReel 供应商" }));
    expect(screen.queryByLabelText("本地服务地址")).not.toBeInTheDocument();
    expect(screen.getByLabelText("音色标识")).toBeVisible();
    expect(changed.mock.lastCall?.[0].voices.narrator).toMatchObject({ adapter: "provider", model: "", base_url: "", reference_audio: null, reference_audio_digest: null, settings: {} });
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    await user.click(screen.getByRole("combobox", { name: "TTS 适配器" }));
    await user.click(await screen.findByRole("option", { name: "IndexTTS2" }));
    expect(changed.mock.lastCall?.[0].voices.narrator).toMatchObject({ adapter: "indextts2", model: "IndexTTS2", base_url: "http://127.0.0.1:7861", voice: "" });
  });
});

it("adds VoxCPM2 with explicit controllable defaults and reference transcript", async () => {
 const changed = vi.fn();
 function Form() { const [book, setBook] = useState({...initial,voices:{}}); return <BookVoices book={book} disabled={false} capabilities={{}} onChange={next=>{setBook(next);changed(next);}} />; }
 const user=userEvent.setup();render(<Form/>);
 await user.click(screen.getByRole("button",{name:"添加角色声音"}));
 expect(changed.mock.lastCall?.[0].voices.narrator).toMatchObject({adapter:"voxcpm2",model:"VoxCPM2",settings:{clone_mode:"controllable",cfg_value:2,inference_timesteps:10,seed:42}});
 expect(screen.getByLabelText("参考音频逐字文本（续写模式必填）")).toBeVisible();
 expect(screen.getByRole("combobox",{name:"音色克隆模式"})).toBeVisible();
});
