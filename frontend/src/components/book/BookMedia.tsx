import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi } from "@/api/book";
import { errMsg } from "@/utils/async";

export function useBookMedia(project: string, path: string | null) {
  const [media, setMedia] = useState<{ path: string; project: string; url: string } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let url: string | null = null;
    void bookApi.blob(project, `media/${path.split("/").map(encodeURIComponent).join("/")}`, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob); setMedia({ path, project, url }); setError("");
      }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(errMsg(reason)); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [project, path]);
  return { url: media?.path === path && media.project === project ? media.url : undefined, error };
}

export function BookAudioPreview({ project, path }: { project: string; path: string }) {
  const { t } = useTranslation("dashboard");
  const { url, error } = useBookMedia(project, path);
  return <div className="min-w-0">
    {/* eslint-disable-next-line jsx-a11y/media-has-caption -- Speech source appears beside each segment; imported sound effects have no caption source. */}
    {url && <audio controls preload="metadata" src={url} aria-label={t("book_preview")} className="w-full" />}
    {error && <p role="alert" className="wrap-break-word text-sm text-destructive">{error}</p>}
  </div>;
}
