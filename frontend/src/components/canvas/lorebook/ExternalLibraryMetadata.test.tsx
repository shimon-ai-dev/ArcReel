import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExternalLibraryMetadata } from "./ExternalLibraryMetadata";
import type { ExternalLibraryIdentity, ExternalReferenceView, ExternalVoice } from "@/types/library-import";

const identity: ExternalLibraryIdentity = { library_id: "synthetic", external_id: "char-01", baseline: "identity-v1", look: "daily-v2", archive_version: "archive-03", product_version: "product-02", status: "approved", frozen: true };
const views: ExternalReferenceView[] = ["front-head", "left-head", "right-head", "front-body", "left-body", "right-body", "back-body"].map((name) => ({ path: `library/${name}.png`, sha256: name, archive_version: "archive-03", product_version: "product-02", width: 100, height: 100, role: "identity", view: name, framing: name.endsWith("head") ? "head" : "full_body", frozen: false, confirmed: true }));
const voice: ExternalVoice = { library_id: "synthetic", external_id: "char-01", voice_id: "voice-01", version: "voice-v1", baseline_status: "pending", status: "pending", technical_pass: true, agent_listened: false, model_adapted: false, clone_tested: false, clips: [{ path: "library/synthetic.wav", sha256: "synthetic", transcript: "合成试听文本", frozen: false, confirmed: false }] };

describe("ExternalLibraryMetadata", () => {
  it("retains all seven labeled views and distinguishes voice binding from technical checks", () => {
    render(<ExternalLibraryMetadata projectName="demo" identity={identity} views={views} voice={voice} />);
    expect(screen.getByText(/身份基线：identity-v1 · 外观：daily-v2/)).toBeInTheDocument();
    expect(screen.getAllByText(/归档版：archive-03 · 成品版：product-02/)).toHaveLength(8);
    expect(within(screen.getByRole("list", { name: "外部库参考视图" })).getAllByRole("img")).toHaveLength(7);
    expect(screen.getByText(/7 张视图不能同时塞入 4 个槽位/)).toBeInTheDocument();
    expect(screen.getByText(/基线绑定待确认，不自动启用此音色/)).toBeInTheDocument();
    expect(screen.getByText(/技术：已记录通过 · 听验：未确认/)).toBeInTheDocument();
    expect(screen.getByLabelText("音色样本 1：voice-01")).toHaveAttribute("preload", "none");
    expect(screen.getByText("合成试听文本")).toBeInTheDocument();
    expect(screen.getByText(/试听不会确认基线绑定/)).toBeInTheDocument();
  });

  it("leaves legacy single-image assets unchanged", () => {
    render(<ExternalLibraryMetadata projectName="demo" />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
});
