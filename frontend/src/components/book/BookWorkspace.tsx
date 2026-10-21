import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { useTranslation } from "react-i18next";
import { BookOpen, Loader2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AgentCopilot } from "@/components/copilot/AgentCopilot";
import { useTaskRefresh } from "@/hooks/useTaskRefresh";
import { selectActiveResourceIds, useTasksStore } from "@/stores/tasks-store";
import { bookApi } from "@/api/book";
import { exportBook, generateBookKeyframe, generateBookSpeech } from "@/actions/book";
import { errMsg } from "@/utils/async";
import { useEditUnit } from "@/components/shared/edit-unit/useEditUnit";
import { BookField } from "./BookFields";
import { BookVoices } from "./BookVoices";
import { BookSegments } from "./BookSegments";
import { BookEvents } from "./BookEvents";
import { BookPlayer } from "./BookPlayer";
import type { BookDocument, BookState } from "@/types/book";

function bookIsBusy(project: string, store = useTasksStore.getState()) {
  return (["book_tts", "book_keyframe", "book_export"] as const).some((kind) => selectActiveResourceIds(store.tasks, kind, project, store.optimisticActive).size > 0);
}

export function BookWorkspace({ project, title, illustrated }: { project: string; title: string; illustrated: boolean }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [state, setState] = useState<BookState | null>(null);
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState("");
  const [copilot, setCopilot] = useState(false);
  useTaskRefresh(project);
  const queueBusy = useTasksStore((store) => bookIsBusy(project, store));
  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await bookApi.get(project, signal);
    if (signal?.aborted) return;
    setState(result);
  }, [project]);
  const saveDocument = useCallback(async (book: BookDocument | null) => {
    if (!book) return null;
    if (bookIsBusy(project)) throw new Error(t("book_busy"));
    await bookApi.save(project, book);
    const result = await bookApi.get(project);
    setState(result);
    return result.book;
  }, [project, t]);
  const unit = useEditUnit<BookDocument | null>({ source: state?.book ?? null, save: saveDocument });
  const draft = unit.value;
  const dirty = unit.dirty;
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => { void load(controller.signal).catch((reason: unknown) => { if (!controller.signal.aborted) setError(errMsg(reason)); }); };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [load]);
  const run = (action: () => Promise<void>) => {
    if (busyRef.current || bookIsBusy(project)) return;
    busyRef.current = true; setBusy(true); setError("");
    void action().catch((reason: unknown) => setError(errMsg(reason))).finally(() => { busyRef.current = false; setBusy(false); });
  };
  const change = (book: BookDocument) => unit.setValue(book);
  const save = async () => { await unit.save(); };
  const generate = (ids: string[], force: boolean) => run(async () => { await unit.saveAndGenerate(async () => { await generateBookSpeech(project, ids, force); await load(); }); });
  const generateFrame = (id: string) => run(async () => { await unit.saveAndGenerate(async () => { await generateBookKeyframe(project, id); await load(); }); });
  const correctText = async (id: string, text: string) => {
    if (busyRef.current || bookIsBusy(project)) throw new Error(t("book_busy"));
    busyRef.current = true; setBusy(true);
    try {
      const saved = await unit.saveAndGenerate(async () => { await bookApi.correctText(project, id, text); await load(); });
      if (!saved) throw new Error(t("book_save_before_correction"));
    } finally { busyRef.current = false; setBusy(false); }
  };
  const download = () => run(async () => {
    const blob = await bookApi.blob(project, "export");
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = `${project}-book.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const disabled = busy || queueBusy;
  return <div className="flex min-h-0 flex-1 flex-col">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b p-3">
      <div className="flex min-w-0 flex-wrap items-center gap-3"><Link href="~/app/projects" className={buttonVariants({ variant: "ghost", size: "sm" })}>{t("projects")}</Link><BookOpen aria-hidden className="size-4" /><span className="wrap-break-word font-medium">{title}</span><span className="text-xs text-muted-foreground">{t(illustrated ? "book_mode_illustrated" : "book_mode_audiobook")}</span></div>
      <Link href="~/app/settings" className={buttonVariants({ variant: "ghost", size: "sm" })}>{t("book_provider_settings")}</Link>
      <Button variant="outline" onClick={() => setCopilot(!copilot)}>{t("book_agent")}</Button>
    </header>
    <div className="@container/book flex min-h-0 flex-1 flex-col">
      <div role="region" className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto [scrollbar-gutter:stable]" aria-label={t("book_workspace")}>
        <div className="mx-auto grid w-full max-w-4xl gap-8 p-4">
          {(error || unit.error) && <p role="alert" className="whitespace-pre-wrap wrap-break-word text-sm text-destructive">{error || unit.error}</p>}
          {!state && !error && <p role="status">{t("book_loading")}</p>}
          {!draft && state && <section className="grid gap-3">
            <h1 className="text-xl font-semibold">{t("book_import_source")}</h1>
            <BookField label={t("source_text")} value={source} multiline disabled={disabled} onChange={setSource} />
            <div className="grid gap-2"><Label htmlFor="book-source-file">{t("book_import_text_file")}</Label><Input id="book-source-file" type="file" accept=".txt,text/plain" disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(async () => setSource(await file.text())); }} /></div>
            <div><Button disabled={disabled || !source.trim()} onClick={() => run(async () => { await bookApi.source(project, source, title); await load(); })}>{t("book_analyze_source")}</Button></div>
          </section>}
          {draft && <>
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={disabled || !dirty} onClick={() => run(save)}>{busy && <Loader2 data-icon="inline-start" className="animate-spin" />}{t("book_save")}</Button>
              <Button variant="outline" disabled={disabled || !dirty} onClick={() => unit.discard()}>{t("book_discard")}</Button>
              <Button variant="outline" disabled={disabled} onClick={() => generate(draft.chapters.flatMap((chapter) => chapter.segments.map((segment) => segment.id)), false)}>{t("book_generate_all")}</Button>
              {dirty && <span className="text-sm text-muted-foreground">{t("book_unsaved")}</span>}
            </div>
            <p className="text-sm text-muted-foreground">{t("book_missing_media", { audio: state?.status.missing_audio.length ?? 0, images: state?.status.missing_images.length ?? 0, effects: state?.status.missing_effects?.length ?? 0 })}</p>
            <p role="status" className="text-sm text-muted-foreground">{t(state?.status.coverage_valid ? "book_coverage_valid" : "book_coverage_invalid")} · {t("book_quality_separate")}</p>
            {unit.externallyUpdated && <p role="alert" className="text-sm text-destructive">{t("book_conflict")}</p>}
            <BookPlayer project={project} book={draft} timeline={state?.timeline ?? null} exports={!dirty && state?.status.complete ? state.exports ?? null : null} />
            <BookVoices book={draft} onChange={change} disabled={disabled} capabilities={state?.capabilities ?? {}} />
            <BookSegments project={project} book={draft} onChange={change} disabled={disabled} generate={generate} correctText={correctText} />
            <BookEvents project={project} book={draft} illustrated={illustrated} onChange={change} disabled={disabled} run={run} generateFrame={generateFrame} />
            <section className="grid gap-3"><h2 className="text-lg font-semibold">{t("book_export")}</h2><p className="text-sm text-muted-foreground">{t("book_export_hint")}</p>
              <div className="flex flex-wrap gap-2">{(["wav", "mp3"] as const).map((format) => <Button key={format} variant="outline" disabled={disabled} onClick={() => run(async () => { await unit.saveAndGenerate(async () => { await exportBook(project, format); await load(); }); })}>{t("book_export_format", { format: format.toUpperCase() })}</Button>)}<Button variant="outline" disabled={busy || dirty || !state?.status.complete || !state.exports?.archive_path} onClick={download}>{t("book_download")}</Button></div>
            </section>
            <details><summary className="cursor-pointer text-sm font-medium">{t("book_tasks")}</summary><ul className="mt-2 grid gap-2">{state?.tasks.map((task, index) => <li key={task.task_id ?? task.id ?? index} className="wrap-break-word text-sm">{task.task_type}: {t(`book_status_${task.status}`)}{task.error_message || task.error ? ` · ${task.error_message ?? task.error}` : ""}</li>)}</ul></details>
          </>}
        </div>
      </div>
      {copilot && <aside className="flex h-96 min-h-0 shrink-0 flex-col border-t" aria-label={t("book_agent")}><AgentCopilot /></aside>}
    </div>
  </div>;
}
