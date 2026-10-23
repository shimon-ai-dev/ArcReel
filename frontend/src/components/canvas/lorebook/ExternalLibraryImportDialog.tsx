import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen, Loader2, Upload } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useAppStore } from "@/stores/app-store";
import type { ExternalLibraryPreview, LibraryImportEntry } from "@/types/library-import";
import { errMsg } from "@/utils/async";
import { refreshAfterWrite } from "../shared/refreshAfterWrite";
import { isAssetBusy } from "./assetBusyGuard";
import { selectManifestFiles } from "./library-import-files";

const DETAIL_LABELS = {
  description: "external_import_detail_description",
  external_library: "external_import_detail_external_library",
  reference_views: "external_import_detail_reference_views",
  external_voice: "external_import_detail_external_voice",
  reference_audio: "external_import_detail_reference_audio",
  reference_audio_transcript: "external_import_detail_reference_audio_transcript",
  reference_image: "external_import_detail_reference_image",
  voice_style: "external_import_detail_voice_style",
  external_library_history: "external_import_detail_external_library_history",
  external_voice_history: "external_import_detail_external_voice_history",
  source_views_retained: "external_import_detail_source_views_retained",
  source_voice_retained: "external_import_detail_source_voice_retained",
  source_voice_clips_retained: "external_import_detail_source_voice_clips_retained",
  existing_voice_binding_retained: "external_import_detail_existing_voice_binding_retained",
  voice_binding_pending: "external_import_detail_voice_binding_pending",
  voice_only_entry: "external_import_detail_voice_only_entry",
  image_confirmation_pending: "external_import_detail_image_confirmation_pending",
  frozen_view_conflict: "external_import_detail_frozen_view_conflict",
  frozen_voice_conflict: "external_import_detail_frozen_voice_conflict",
  frozen_pack_conflict: "external_import_detail_frozen_pack_conflict",
  identity_conflict: "external_import_detail_identity_conflict",
  identity_already_mapped: "external_import_detail_identity_already_mapped",
  name_conflict: "external_import_detail_name_conflict",
} as const;

export function ExternalLibraryImportDialog({ projectName, blocked, onClose, onApplyingChange }: {
  projectName: string;
  blocked: boolean;
  onClose: () => void;
  onApplyingChange: (applying: boolean) => void;
}) {
  const { t } = useTranslation(["assets", "common"]);
  const manifestRef = useRef<HTMLInputElement>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const confirmId = useId();
  const [manifest, setManifest] = useState("");
  const [manifestName, setManifestName] = useState("");
  const [selected, setSelected] = useState<File[]>([]);
  const [preview, setPreview] = useState<ExternalLibraryPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const selection = selectManifestFiles(manifest, selected);
  const hasChanges = preview && preview.summary.added + preview.summary.updated > 0;

  const invalidate = () => {
    setPreview(null);
    setReviewed(false);
    setError(null);
    setErrorDetail(null);
  };

  const readManifest = async (file: File | undefined) => {
    if (!file || working) return;
    invalidate();
    setManifest("");
    setManifestName(file.name);
    setWorking(true);
    try {
      setManifest(await file.text());
    } catch (err) {
      setError(t("external_import_read_failed"));
      setErrorDetail(errMsg(err));
    } finally {
      setWorking(false);
    }
  };

  const chooseFiles = async (files: FileList | null, fromFolder = false) => {
    if (!files || working) return;
    invalidate();
    const chosen = Array.from(files);
    setSelected(chosen);
    if (fromFolder) {
      const manifests = chosen.filter((file) => file.name === "library-manifest.json");
      setManifest("");
      setManifestName("");
      if (manifests.length === 1) await readManifest(manifests[0]);
      else setError(t("external_import_bundle_manifest"));
    }
  };

  const inspect = async () => {
    if (working || blocked || selection.error) return;
    invalidate();
    setWorking(true);
    try {
      setPreview(await API.previewExternalLibrary(projectName, manifest, selection.files));
    } catch (err) {
      setError(t("external_import_preview_failed"));
      setErrorDetail(errMsg(err));
    } finally {
      setWorking(false);
    }
  };

  const apply = async () => {
    if (working || blocked || !reviewed || !preview?.can_apply || !hasChanges || selection.error) return;
    if (preview.entries.some((entry) => entry.operation !== "unchanged" && isAssetBusy(entry.asset_type, projectName, entry.name))) {
      setError(t("external_import_busy"));
      return;
    }
    setWorking(true);
    onApplyingChange(true);
    setError(null);
    setErrorDetail(null);
    try {
      await API.applyExternalLibrary(projectName, manifest, selection.files, preview.preview_token);
      await refreshAfterWrite(projectName, t);
      useAppStore.getState().pushToast(t("external_import_applied"), "success");
      onClose();
    } catch (err) {
      setPreview(null);
      setReviewed(false);
      setError(t("external_import_apply_failed"));
      setErrorDetail(errMsg(err));
    } finally {
      setWorking(false);
      onApplyingChange(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !working) onClose(); }}>
      <DialogContent size="lg" showCloseButton={false}>
        <DialogHeader><DialogTitle>{t("external_import_title")}</DialogTitle></DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-4">
            <p className="text-sm text-subtle-foreground">{t("external_import_intro")}</p>
            <p className="text-xs text-muted-foreground wrap-break-word">{t("external_import_converter_hint")}</p>
            <p className="text-sm text-muted-foreground">{t("external_import_path_hint")}</p>
            <p className="text-sm text-muted-foreground">{t("external_import_symlink_hint")}</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={working} onClick={() => manifestRef.current?.click()}>
                <Upload aria-hidden data-icon="inline-start" />{t("external_import_manifest")}
              </Button>
              <Button variant="outline" disabled={working} onClick={() => folderRef.current?.click()}>
                <FolderOpen aria-hidden data-icon="inline-start" />{t("external_import_folder")}
              </Button>
              <Button variant="outline" disabled={working} onClick={() => filesRef.current?.click()}>{t("external_import_files")}</Button>
            </div>
            <input ref={manifestRef} type="file" accept=".json,application/json" hidden disabled={working} aria-label={t("external_import_manifest")} onChange={(event) => { void readManifest(event.target.files?.[0]); event.target.value = ""; }} />
            <input ref={folderRef} type="file" multiple {...{ webkitdirectory: "" }} hidden disabled={working} aria-label={t("external_import_folder")} onChange={(event) => { void chooseFiles(event.target.files, true); event.target.value = ""; }} />
            <input ref={filesRef} type="file" multiple accept="image/*,audio/*" hidden disabled={working} aria-label={t("external_import_files")} onChange={(event) => { void chooseFiles(event.target.files); event.target.value = ""; }} />
            {manifestName && <p className="text-sm wrap-break-word">{t("external_import_selection", { name: manifestName, count: selected.length })}</p>}
            {manifest && selection.error && <p role="alert" className="text-sm text-destructive wrap-break-word">{t(selection.error === "manifest" ? "external_import_manifest_error" : `external_import_${selection.error}`, { names: selection.names.join(", ") })}</p>}
            {manifest && !selection.error && <p className="text-sm text-muted-foreground">{t("external_import_only_referenced", { count: selection.files.length })}</p>}
            {blocked && <p role="status" className="text-sm text-warn">{t("external_import_busy")}</p>}
            {preview && (
              <>
                <p role="status" className="text-sm font-medium">{t("external_import_summary", preview.summary)}</p>
                <p className="text-sm text-muted-foreground">{t("external_import_no_delete")}</p>
                {preview.summary.pending_voice_bindings > 0 && <p className="text-sm text-warn">{t("external_import_pending_voice", { count: preview.summary.pending_voice_bindings })}</p>}
                <ul aria-label={t("external_import_entries")} className="flex flex-col gap-3">
                  {preview.entries.map((entry, index) => <PreviewEntry key={`${entry.asset_type}/${entry.external_id}/${index}`} entry={entry} />)}
                </ul>
                {hasChanges && preview.can_apply && (
                  <div className="flex items-start gap-2">
                    <Checkbox id={confirmId} checked={reviewed} disabled={working} onCheckedChange={(checked) => setReviewed(checked === true)} />
                    <Label htmlFor={confirmId} className="wrap-break-word">{t("external_import_confirm")}</Label>
                  </div>
                )}
                {!hasChanges && preview.can_apply && <p className="text-sm text-muted-foreground">{t("external_import_no_changes")}</p>}
              </>
            )}
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            {errorDetail && <details className="text-xs text-muted-foreground wrap-break-word"><summary>{t("external_import_details")}</summary><p>{errorDetail}</p></details>}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" disabled={working} onClick={onClose}>{t("cancel")}</Button>
          <Button variant="outline" disabled={working || blocked || !manifest || Boolean(selection.error)} onClick={() => void inspect()}>
            {working && <Loader2 aria-hidden data-icon="inline-start" className="animate-spin" />}{t("external_import_preview")}
          </Button>
          <Button disabled={working || blocked || !preview?.can_apply || !reviewed || !hasChanges} onClick={() => void apply()}>{t("external_import_apply")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PreviewEntry({ entry }: { entry: LibraryImportEntry }) {
  const { t } = useTranslation("assets");
  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-lg border border-border p-3 text-sm">
      <p className="font-medium wrap-break-word">{entry.name} · {t(`external_import_op_${entry.operation}`)}</p>
      <p className="text-muted-foreground wrap-break-word">{t(`type.${entry.asset_type}`)} · {entry.external_id}</p>
      <p className="text-muted-foreground wrap-break-word">{t("external_identity_versions", { archive: entry.previous_archive_version ? `${entry.previous_archive_version} → ${entry.archive_version}` : entry.archive_version, product: entry.previous_product_version ? `${entry.previous_product_version} → ${entry.product_version || t("external_unspecified")}` : entry.product_version || t("external_unspecified") })}</p>
      {(entry.baseline || entry.look) && <p className="wrap-break-word">{t("external_identity_baseline_look", { baseline: entry.baseline || t("external_unspecified"), look: entry.look || t("external_unspecified") })}</p>}
      {Boolean(entry.view_changes?.length) && (
        <ul className="flex flex-col gap-1 text-xs">
          {entry.view_changes?.map((view, index) => <li key={`${view.role}/${view.view}/${view.framing}/${index}`} className="wrap-break-word">{t(`external_role_${view.role}`)} · {view.view} · {view.framing} · {t(`external_import_op_${view.operation}`)} · {view.previous_archive_version ? `${view.previous_archive_version} → ` : ""}{view.archive_version}</li>)}
        </ul>
      )}
      {entry.conflicts.length > 0 && <p className="text-destructive">{t("external_import_conflict_hint")}</p>}
      {(entry.changes.length + entry.warnings.length + entry.conflicts.length > 0) && (
        <details className="text-xs text-muted-foreground wrap-break-word">
          <summary>{t("external_import_details")}</summary>
          <ul className="list-inside list-disc">{[...entry.changes, ...entry.warnings, ...entry.conflicts].map((code, index) => <li key={`${code}/${index}`}>{Object.hasOwn(DETAIL_LABELS, code) ? t(DETAIL_LABELS[code as keyof typeof DETAIL_LABELS]) : code}</li>)}</ul>
        </details>
      )}
    </li>
  );
}
