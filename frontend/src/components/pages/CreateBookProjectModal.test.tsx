import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import type { ProjectData } from "@/types";
import { CreateProjectModal } from "./CreateProjectModal";

const navigate = vi.fn();
vi.mock("wouter", () => ({ useLocation: () => ["/app/projects", navigate] }));

beforeEach(() => {
  vi.spyOn(API, "getSystemConfig").mockRejectedValue(new Error("No models configured"));
  vi.spyOn(API, "getProviders").mockRejectedValue(new Error("No providers configured"));
  vi.spyOn(API, "listCustomProviders").mockResolvedValue({ providers: [] });
  vi.spyOn(API, "getNarrationDefaults").mockRejectedValue(new Error("No default TTS"));
  vi.spyOn(API, "createProject").mockResolvedValue({ success: true, name: "book-test", project: {} as ProjectData });
});

describe("book creation", () => {
  it.each([["有声书", "audiobook"], ["图声书", "illustrated_audiobook"]])("creates %s without image or video configuration", async (label, mode) => {
    const user = userEvent.setup();
    render(<CreateProjectModal />);
    await user.click(screen.getByRole("combobox", { name: "输出模式" }));
    await user.click(await screen.findByRole("option", { name: label }));
    await user.type(screen.getByRole("textbox", { name: "项目标题" }), "完整小说");
    await user.click(screen.getByRole("button", { name: "创建项目" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/app/projects/book-test"));
    expect(API.createProject).toHaveBeenCalledWith({ title: "完整小说", output_mode: mode });
  });
});
