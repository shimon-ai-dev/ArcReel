import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { BookTextCorrection } from "./BookTextCorrection";
import { BookPronunciation } from "./BookPronunciation";
import { BookField } from "./BookFields";
import { BookSelect } from "./BookSelect";
import { BookAudioPreview } from "./BookMedia";
import type { BookDocument, BookSegment } from "@/types/book";

export function BookSegments({ project, book, chapterId, onChange, disabled, generate, correctText }: {
  project: string; book: BookDocument; chapterId?: string; onChange: (next: BookDocument) => void; disabled: boolean;
  generate: (ids: string[], force: boolean) => void;
  correctText: (id: string, text: string) => Promise<void>;
}) {
  const { t } = useTranslation("dashboard");
  const segmentSelectId = useId();
  const [selectedId, setSelectedId] = useState("");
  const chapters = book.chapters.filter((chapter) => !chapterId || chapter.id === chapterId);
  const segments = chapters.flatMap((chapter) => chapter.segments);
  const selected = segments.find((segment) => segment.id === selectedId) ?? segments[0];
  const update = (id: string, patch: Partial<BookSegment>) => onChange({ ...book, chapters: book.chapters.map((chapter) => ({ ...chapter, segments: chapter.segments.map((segment) => segment.id === id ? { ...segment, ...patch } : segment) })) });
  return <section className="grid gap-4" aria-label={t("book_chapters")}>
    <h2 className="text-lg font-semibold">{t("book_chapters")}</h2>
    <p className="text-sm text-muted-foreground">{t("book_source_fidelity_hint")}</p>
    {chapters.map((chapter) => <details key={chapter.id} open className="rounded-lg border p-4">
      <summary className="cursor-pointer text-base font-semibold">{chapter.title}</summary>
      <div className="mt-4 grid gap-3"><Label htmlFor={`${segmentSelectId}-${chapter.id}`}>{t("book_current_segment")}</Label><BookSelect id={`${segmentSelectId}-${chapter.id}`} value={selected?.id ?? ""} options={chapter.segments.map((segment, index) => ({ value: segment.id, label: `${index + 1} · ${Array.from(segment.text).slice(0, 50).join("")}` }))} onChange={setSelectedId} /></div>
      <div className="mt-4 grid gap-4">{chapter.segments.filter((segment) => segment.id === selected?.id).map((segment) => {
        const voice = book.voices[segment.speaker_id];
        const vox = voice?.adapter === "voxcpm2";
        const continuation = vox && voice.settings.clone_mode === "continuation";
        const version = segment.audio_versions.find((item) => item.id === segment.selected_audio_version);
        const busy = disabled || segment.status === "queued" || segment.status === "running";
        return <article key={segment.id} className="grid min-w-0 gap-3 border-t pt-4">
          <p className="whitespace-pre-wrap wrap-break-word text-sm">{segment.text}</p>
          <details><summary className="cursor-pointer text-sm font-medium">{t("book_text_pronunciation")}</summary>
          {book.origin === "episodes" ? <p className="text-sm text-muted-foreground">{t("book_edit_original_source")}</p> : <BookTextCorrection id={segment.id} text={segment.text} disabled={busy} apply={correctText} />}
          <BookPronunciation segment={segment} disabled={busy} update={(pronunciation) => update(segment.id, { pronunciation })} />
          </details>
          <p className="text-xs text-muted-foreground">{t("book_source_span", { start: segment.source_start, end: segment.source_end })} · {t(`book_status_${segment.status}`)}{version ? ` · ${version.duration_seconds.toFixed(2)} s` : ""}</p>
          <fieldset disabled={busy} className="grid min-w-0 gap-3">
            <div className="grid gap-1.5"><Label htmlFor={`speaker-${segment.id}`}>{t("book_speaker")}</Label><BookSelect id={`speaker-${segment.id}`} disabled={busy} value={segment.speaker_id} options={Object.values(book.voices).map((voice) => ({ value: voice.id, label: voice.name || voice.id }))} onChange={(speaker_id) => update(segment.id, { speaker_id, speaker_confirmed: true })} /></div>
            <div className="flex items-center gap-2"><Checkbox id={`confirmed-${segment.id}`} checked={segment.speaker_confirmed} onCheckedChange={(value) => update(segment.id, { speaker_confirmed: value === true })} /><Label htmlFor={`confirmed-${segment.id}`}>{t("book_speaker_confirmed")}</Label></div>
            <BookField disabled={continuation} label={t("book_emotion")} value={segment.performance.emotion ?? ""} onChange={(value) => update(segment.id, { performance: { ...segment.performance, emotion: value || null } })} />
            <details><summary className="cursor-pointer text-sm font-medium">{t("book_performance_details")}</summary><div className="mt-3 grid gap-3">
            {!vox && <BookField label={t("book_intensity")} type="number" min={0} max={1} step={0.1} value={segment.performance.intensity} onChange={(value) => update(segment.id, { performance: { ...segment.performance, intensity: Number(value) } })} />}
            <BookField disabled={continuation} label={t("book_style")} value={segment.performance.style ?? ""} onChange={(value) => update(segment.id, { performance: { ...segment.performance, style: value || null } })} />
            {!vox && <BookField label={t("book_nonverbal")} value={segment.performance.nonverbal ?? ""} onChange={(value) => update(segment.id, { performance: { ...segment.performance, nonverbal: value || null } })} />}
            {!vox && <BookField label={t("book_speed")} type="number" min={0.1} max={4} step={0.1} value={segment.performance.speed ?? ""} onChange={(value) => update(segment.id, { performance: { ...segment.performance, speed: value ? Number(value) : null } })} />}
            <BookField label={t("book_pause")} type="number" min={0} max={60} step={0.1} value={segment.pause_after_seconds} onChange={(value) => update(segment.id, { pause_after_seconds: Number(value) })} />
            </div></details>
          </fieldset>
          {segment.error && <p role="alert" className="wrap-break-word text-sm text-destructive">{segment.error}</p>}
          {version && <BookAudioPreview project={project} path={version.path} />}
          <div><Button variant="outline" disabled={busy} onClick={() => generate([segment.id], true)}>{t(segment.status === "failed" ? "book_retry" : "book_regenerate")}</Button></div>
        </article>;
      })}</div>
    </details>)}
  </section>;
}
