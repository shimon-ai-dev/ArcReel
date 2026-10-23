import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useEditUnit } from "@/components/shared/edit-unit/useEditUnit";
import { useTasksStore, selectActiveResourceIds } from "@/stores/tasks-store";
import { bookApi } from "@/api/book";
import { exportBook, generateBookSpeech } from "@/actions/book";
import { errMsg } from "@/utils/async";
import type { BookDocument, BookState } from "@/types/book";
import { BookSegments } from "./BookSegments";
import { BookVoices } from "./BookVoices";
import { BookEvents } from "./BookEvents";
import { BookPlayer } from "./BookPlayer";

function bookBusy(project: string, store = useTasksStore.getState()) {
  return (["book_tts", "book_keyframe", "book_export"] as const).some((kind) =>
    selectActiveResourceIds(store.tasks, kind, project, store.optimisticActive).size > 0,
  );
}

/** Audio is an episode view inside the original studio, never another project workspace. */
export function BookEpisodePanel({ project, episode, view, legacyOnly = false }: {
  project: string; episode: number; view: "audio" | "listen"; legacyOnly?: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const [state, setState] = useState<BookState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const queueBusy = useTasksStore((store) => bookBusy(project, store));
  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await bookApi.get(project, signal);
    if (!signal?.aborted) setState(result);
  }, [project]);
  const save = useCallback(async (book: BookDocument | null) => {
    if (!book) return null;
    if (bookBusy(project)) throw new Error(t("book_busy"));
    await bookApi.save(project, book);
    const result = await bookApi.get(project);
    setState(result);
    return result.book;
  }, [project, t]);
  const unit = useEditUnit<BookDocument | null>({ source: state?.book ?? null, save });
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => { void load(controller.signal).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(errMsg(reason));
    }); };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [load]);
  const run = (action: () => Promise<void>) => {
    if (busyRef.current || bookBusy(project)) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    void action().catch((reason: unknown) => setError(errMsg(reason))).finally(() => {
      busyRef.current = false;
      setBusy(false);
    });
  };
  const draft = unit.value;
  const chapter = draft?.chapters.find((item) => item.episode === episode);
  const legacy = draft?.chapters.filter((item) => item.episode == null) ?? [];
  const disabled = busy || queueBusy;
  const generate = (ids: string[], force: boolean) => run(async () => {
    await unit.saveAndGenerate(async () => { await generateBookSpeech(project, ids, force); await load(); });
  });
  const correctText = async (id: string, text: string) => {
    if (busyRef.current || bookBusy(project)) throw new Error(t("book_busy"));
    busyRef.current = true;
    setBusy(true);
    try {
      const saved = await unit.saveAndGenerate(async () => { await bookApi.correctText(project, id, text); await load(); });
      if (!saved) throw new Error(t("book_save_before_correction"));
    } finally { busyRef.current = false; setBusy(false); }
  };
  const synchronize = () => run(async () => {
    await unit.saveAndGenerate(async () => { setState(await bookApi.syncEpisode(project, episode)); });
  });
  const download = () => run(async () => {
    const blob = await bookApi.blob(project, "export");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `${project}-book.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  return <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto [scrollbar-gutter:stable]">
    <div className="mx-auto grid w-full max-w-4xl gap-5 p-4">
      <p className="text-sm text-muted-foreground">{t("book_episode_reuse_hint")}</p>
      {(error || unit.error) && <p role="alert" className="whitespace-pre-wrap wrap-break-word text-sm text-destructive">{error || unit.error}</p>}
      {!state && !error && <p role="status">{t("book_loading")}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {!legacyOnly && <Button disabled={disabled || !state} onClick={synchronize}>{t("book_sync_episode")}</Button>}
        {draft && <>
          <Button variant="outline" disabled={disabled || !unit.dirty} onClick={() => run(async () => { await unit.save(); })}>{t("book_save")}</Button>
          <Button variant="outline" disabled={disabled || !unit.dirty} onClick={() => unit.discard()}>{t("book_discard")}</Button>
        </>}
        {unit.dirty && <span className="text-sm text-muted-foreground">{t("book_unsaved")}</span>}
      </div>
      {unit.externallyUpdated && <p role="alert" className="text-sm text-destructive">{t("book_conflict")}</p>}
      {state?.status.stale_episodes?.includes(episode) && <p role="alert" className="text-sm text-destructive">{t("book_episode_stale")}</p>}
      {!legacyOnly && !chapter && state && <p className="text-sm text-muted-foreground">{t("book_episode_not_synced")}</p>}
      {draft && chapter && (view === "audio" ? <>
        <div><Button variant="outline" disabled={disabled} onClick={() => generate(chapter.segments.map((segment) => segment.id), false)}>{t("book_generate_episode")}</Button></div>
        <details><summary className="cursor-pointer text-sm font-medium">{t("book_voices")}</summary><div className="mt-3"><BookVoices book={draft} onChange={unit.setValue} disabled={disabled} capabilities={state?.capabilities ?? {}} /></div></details>
        <BookSegments project={project} book={draft} chapterId={chapter.id} onChange={unit.setValue} disabled={disabled} generate={generate} correctText={correctText} />
        <details><summary className="cursor-pointer text-sm font-medium">{t("book_effects")}</summary><div className="mt-3"><BookEvents project={project} book={draft} chapterId={chapter.id} onChange={unit.setValue} disabled={disabled} run={run} /></div></details>
      </> : <>
        <BookPlayer project={project} book={{ ...draft, chapters: [chapter] }} timeline={state?.timeline ?? null} exports={!unit.dirty ? state?.exports ?? null : null} />
        <p className="text-sm text-muted-foreground">{t("book_quality_separate")}</p>
        <section className="grid gap-3">
          <h2 className="text-lg font-semibold">{t("book_export")}</h2>
          <p className="text-sm text-muted-foreground">{t("book_export_hint")}</p>
          <div className="flex flex-wrap gap-2">
            {(["wav", "mp3"] as const).map((format) => <Button key={format} variant="outline" disabled={disabled} onClick={() => run(async () => { await unit.saveAndGenerate(async () => { await exportBook(project, format); await load(); }); })}>{t("book_export_format", { format: format.toUpperCase() })}</Button>)}
            <Button variant="outline" disabled={disabled || unit.dirty || state?.status.ready_to_export === false || !state?.status.complete || !state.exports?.archive_path} onClick={download}>{t("book_download")}</Button>
          </div>
          <p role="status" className="text-sm text-muted-foreground">{t("book_missing_media", { audio: state?.status.missing_audio.length ?? 0, images: state?.status.missing_images.length ?? 0, effects: state?.status.missing_effects?.length ?? 0 })}</p>
        </section>
      </>)}
      {draft && legacy.length > 0 && <details>
        <summary className="cursor-pointer text-sm font-medium">{t("book_legacy_drafts")}</summary>
        <p className="my-3 text-sm text-muted-foreground">{t("book_legacy_drafts_hint")}</p>
        {legacy.map((item) => <details key={item.id} className="my-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">{item.title}</summary><BookSegments project={project} book={draft} chapterId={item.id} onChange={unit.setValue} disabled={disabled} generate={generate} correctText={correctText} /></details>)}
      </details>}
    </div>
  </div>;
}
