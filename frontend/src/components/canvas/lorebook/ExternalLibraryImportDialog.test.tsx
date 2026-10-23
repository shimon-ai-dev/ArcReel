import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { createDeferred } from "@/test/deferred";
import { makeTask } from "@/test/factories";
import type { ExternalLibraryPreview } from "@/types/library-import";
import { ExternalLibraryImportDialog } from "./ExternalLibraryImportDialog";

const PREVIEW: ExternalLibraryPreview = {
  preview_token: "synthetic-token", can_apply: true,
  summary: { added: 1, updated: 0, unchanged: 0, conflicts: 0, pending_voice_bindings: 1, deduplicated_files: 0 },
  entries: [{ asset_type: "character", name: "合成角色", external_id: "character-synthetic", baseline: "baseline-v1", look: "daily", archive_version: "archive-v1", product_version: "product-v1", operation: "add", changes: ["views_added"], warnings: ["voice_binding_pending"], conflicts: [] }],
};

const MANIFEST = JSON.stringify({ schema_version: 1, library_id: "synthetic", entries: [{ views: [{ file: "front.png" }] }] });

async function selectInputs(user: ReturnType<typeof userEvent.setup>) {
  const file = new File([MANIFEST], "manifest.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(MANIFEST) });
  await user.upload(screen.getByLabelText("选择清单 JSON"), file);
  await user.upload(screen.getByLabelText("改选图片 / 音频文件"), new File(["synthetic"], "front.png", { type: "image/png" }));
}

function renderDialog() {
  const onClose = vi.fn();
  render(<ExternalLibraryImportDialog projectName="demo" blocked={false} onClose={onClose} onApplyingChange={vi.fn()} />);
  return onClose;
}

describe("ExternalLibraryImportDialog", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], optimisticActive: new Set() });
    vi.spyOn(API, "previewExternalLibrary").mockResolvedValue(PREVIEW);
    vi.spyOn(API, "applyExternalLibrary").mockResolvedValue({ ...PREVIEW, applied: true });
    vi.spyOn(useProjectsStore.getState(), "refreshProject").mockResolvedValue("success");
  });
  afterEach(() => vi.restoreAllMocks());

  it("previews differences and pending voice binding, then requires explicit confirmation before applying", async () => {
    const user = userEvent.setup();
    const close = renderDialog();
    expect(screen.getByText(/NAS 或服务器不能据此读取 Mac/)).toBeInTheDocument();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    expect(await screen.findByText("新增 1 · 更新 0 · 无变化 0 · 冲突 0")).toBeInTheDocument();
    expect(screen.getByText(/1 个音色仍待确认基线绑定/)).toBeInTheDocument();
    expect(screen.getByText(/不会隐式删除/)).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "确认应用" });
    expect(apply).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(apply);
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(API.applyExternalLibrary).toHaveBeenCalledWith("demo", MANIFEST, [expect.any(File)], "synthetic-token");
  });

  it("loads a generated bundle manifest and invalidates confirmation when another folder is chosen", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderDialog();
    const manifestFile = new File([MANIFEST], "library-manifest.json", { type: "application/json" });
    Object.defineProperty(manifestFile, "text", { value: () => Promise.resolve(MANIFEST) });
    await user.upload(screen.getByLabelText("选择库根目录"), [manifestFile, new File(["synthetic"], "front.png"), new File(["private"], "preview.json")]);
    expect(await screen.findByText("只上传清单引用的 1 个文件，其余选中文件不会发送。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.click(await screen.findByRole("checkbox"));
    await user.upload(screen.getByLabelText("选择库根目录"), new File(["raw source"], "existing-library.yaml"));
    expect(await screen.findByText(/所选目录必须包含唯一的 library-manifest.json/)).toBeInTheDocument();
    expect(screen.getByText(/prepare_library_bundle/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认应用" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "预览差异" })).toBeDisabled();
  });

  it("invalidates a reviewed preview when selected content changes", async () => {
    const user = userEvent.setup();
    renderDialog();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.click(await screen.findByRole("checkbox"));
    await user.upload(screen.getByLabelText("改选图片 / 音频文件"), new File(["replacement"], "front.png", { type: "image/png" }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认应用" })).toBeDisabled();
  });

  it("rechecks current task occupancy at confirmation and does not apply", async () => {
    const user = userEvent.setup();
    renderDialog();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.click(await screen.findByRole("checkbox"));
    act(() => useTasksStore.setState({ tasks: [makeTask({ project_name: "demo", task_type: "character", resource_id: "合成角色", status: "running" })] }));
    await user.click(screen.getByRole("button", { name: "确认应用" }));
    expect(await screen.findByText("资产正在生成或写入，请等待完成后再导入。")).toBeInTheDocument();
    expect(API.applyExternalLibrary).not.toHaveBeenCalled();
  });

  it("shows source version transitions and each retained or updated view in the preview", async () => {
    vi.spyOn(API, "previewExternalLibrary").mockResolvedValue({ ...PREVIEW, entries: [{ ...PREVIEW.entries[0], operation: "update", previous_archive_version: "archive-v0", previous_product_version: "product-v0", view_changes: [{ role: "identity", view: "front", framing: "headshot", operation: "retain", previous_sha256: "synthetic", sha256: "synthetic", previous_archive_version: "archive-v0", archive_version: "archive-v0" }] }] });
    const user = userEvent.setup();
    renderDialog();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    expect(await screen.findByText("归档版：archive-v0 → archive-v1 · 成品版：product-v0 → product-v1")).toBeInTheDocument();
    expect(screen.getByText("身份 · front · headshot · 保留 · archive-v0 → archive-v0")).toBeInTheDocument();
  });

  it("blocks conflicts and does not offer an overwrite action", async () => {
    vi.spyOn(API, "previewExternalLibrary").mockResolvedValue({ ...PREVIEW, can_apply: false, summary: { ...PREVIEW.summary, added: 0, conflicts: 1 }, entries: [{ ...PREVIEW.entries[0], operation: "conflict", conflicts: ["frozen_view_conflict"] }] });
    const user = userEvent.setup();
    renderDialog();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    expect(await screen.findByText(/请先在源库解决冲突/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认应用" })).toBeDisabled();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("keeps the dialog open while applying, prevents repeat clicks, and requires re-preview after failure", async () => {
    const pending = createDeferred<ExternalLibraryPreview>();
    vi.spyOn(API, "applyExternalLibrary").mockReturnValue(pending.promise);
    const user = userEvent.setup();
    const close = renderDialog();
    await selectInputs(user);
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "确认应用" }));
    expect(screen.getByRole("button", { name: "确认应用" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(close).not.toHaveBeenCalled();
    await act(async () => pending.reject(new Error("synthetic conflict")));
    expect(await screen.findByText(/导入未能确认完成/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "预览差异" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
