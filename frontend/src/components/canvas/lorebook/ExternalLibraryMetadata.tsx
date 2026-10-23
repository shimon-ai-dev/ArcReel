import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { AssetThumb } from "@/components/assets/AssetThumb";
import type { ExternalLibraryIdentity, ExternalReferenceView, ExternalVoice } from "@/types/library-import";

export function ExternalLibraryMetadata({ projectName, identity, views, voice }: {
  projectName: string;
  identity?: ExternalLibraryIdentity;
  views?: ExternalReferenceView[];
  voice?: ExternalVoice;
}) {
  const { t } = useTranslation("assets");
  if (!identity && !views?.length && !voice) return null;
  return (
    <section aria-label={t("external_identity_title")} className="flex min-w-0 flex-col gap-3">
      <h3 className="text-sm font-medium">{t("external_identity_title")}</h3>
      {identity && (
        <div className="flex flex-col gap-1 text-sm wrap-break-word">
          <p>{identity.library_id} · {identity.external_id}</p>
          <p>{t("external_identity_baseline_look", { baseline: identity.baseline || t("external_unspecified"), look: identity.look || t("external_unspecified") })}</p>
          <p>{t("external_identity_versions", { archive: identity.archive_version, product: identity.product_version || t("external_unspecified") })}</p>
          {(identity.action || identity.state) && <p>{t("external_identity_action_state", { action: identity.action || t("external_unspecified"), state: identity.state || t("external_unspecified") })}</p>}
          <p className="text-muted-foreground">{t(`external_status_${identity.status}`)}{identity.frozen ? ` · ${t("external_frozen")}` : ""}</p>
        </div>
      )}
      {Boolean(views?.length) && (
        <>
          <h4 className="text-sm font-medium">{t("external_views_title", { count: views?.length })}</h4>
          <p className="text-xs text-muted-foreground">{t("external_views_budget")}</p>
          <ul aria-label={t("external_views_list")} className="grid grid-cols-2 gap-3">
            {views?.map((view, index) => (
              <li key={`${view.path}/${index}`} className="flex min-w-0 flex-col gap-1">
                <AssetThumb imageUrl={API.getFileUrl(projectName, view.path, view.sha256)} alt={`${t(`external_role_${view.role}`)} · ${view.view} · ${view.framing}`} fallback={<span>{t("external_view_unavailable")}</span>} className="rounded-md border border-border" />
                <p className="text-sm wrap-break-word">{t(`external_role_${view.role}`)} · {view.view} · {view.framing}</p>
                <p className="text-xs text-muted-foreground wrap-break-word">{t("external_identity_versions", { archive: view.archive_version, product: view.product_version || t("external_unspecified") })}</p>
                <p className="text-xs text-muted-foreground">{t(view.confirmed ? "external_view_confirmed" : "external_view_pending")}{view.frozen ? ` · ${t("external_frozen")}` : ""}</p>
              </li>
            ))}
          </ul>
        </>
      )}
      {voice && (
        <div className="flex flex-col gap-1 text-sm wrap-break-word">
          <h4 className="font-medium">{t("external_voice_title")}</h4>
          <p>{voice.voice_id} · {voice.version}</p>
          <p>{t("external_voice_baseline", { baseline: voice.baseline || t("external_unspecified") })}</p>
          <p className="text-muted-foreground">{t(voice.baseline_status === "confirmed" ? "external_voice_confirmed" : "external_voice_pending")}</p>
          <p className="text-xs text-muted-foreground">{t("external_voice_checks", { technical: t(voice.technical_pass ? "external_check_pass" : "external_check_pending"), listening: t(voice.agent_listened ? "external_check_pass" : "external_check_pending"), adaptation: t(voice.model_adapted ? "external_check_pass" : "external_check_pending"), clone: t(voice.clone_tested ? "external_check_pass" : "external_check_pending") })}</p>
          {voice.clips.length > 0 && (
            <>
              <p className="text-xs text-muted-foreground">{t("external_voice_audition")}</p>
              <ul aria-label={t("external_voice_clips", { count: voice.clips.length })} className="flex flex-col gap-2">
                {voice.clips.map((clip, index) => (
                  <li key={clip.path} className="flex min-w-0 flex-col gap-1">
                    {/* Voice samples have optional transcripts below, not timed caption tracks. */}
                    {/* eslint-disable-next-line jsx-a11y/media-has-caption -- 音色样本没有同步字幕轨道；已有转写在播放器下方展示 */}
                    <audio controls preload="none" src={API.getFileUrl(projectName, clip.path, clip.sha256)} aria-label={t("external_voice_clip_label", { index: index + 1, voice: voice.voice_id })} className="w-full" />
                    {clip.transcript && <p className="text-xs text-muted-foreground whitespace-pre-wrap wrap-break-word">{clip.transcript}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
