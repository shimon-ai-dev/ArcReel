import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { BookSelect } from "./BookSelect";
import { useBookMedia } from "./BookMedia";
import type { BookDocument, BookExports, BookTimeline } from "@/types/book";

export function activeBookEvent<T extends { start_seconds: number }>(events: T[], seconds: number): T | undefined {
  return events.filter((event) => event.start_seconds <= seconds).sort((a, b) => b.start_seconds - a.start_seconds)[0];
}

export function BookPlayer({ project, book, timeline, exports }: {
  project: string; book: BookDocument; timeline: BookTimeline | null; exports: BookExports | null;
}) {
  const { t } = useTranslation("dashboard");
  const [selectedChapter, setSelectedChapter] = useState("");
  const [time, setTime] = useState(0);
  const [rate, setRate] = useState("1");
  const audioRef = useRef<HTMLAudioElement>(null);
  const chapter = book.chapters.find((item) => item.id === selectedChapter) ?? book.chapters[0];
  const exported = exports?.chapters?.find((item) => item.id === chapter?.id);
  const audio = useBookMedia(project, exported?.path ?? null);
  const timings = timeline?.segments.filter((segment) => segment.chapter_id === chapter?.id) ?? [];
  const chapterStart = timings[0]?.start_seconds ?? 0;
  const frames = timeline?.keyframes.filter((frame) => frame.chapter_id === chapter?.id && frame.path) ?? [];
  const frame = activeBookEvent(frames, chapterStart + time);
  const image = useBookMedia(project, frame?.path ?? null);
  const segment = activeBookEvent(timings, chapterStart + time);
  const text = chapter?.segments.find((item) => item.id === segment?.id)?.text;
  return <section className="grid min-w-0 gap-3" aria-label={t("book_player")}>
    <h2 className="text-lg font-semibold">{t("book_player")}</h2>
    <div className="flex flex-wrap gap-3">
      <div className="grid gap-1.5"><Label htmlFor="book-player-chapter">{t("book_chapters")}</Label><BookSelect id="book-player-chapter" value={chapter?.id ?? ""} options={book.chapters.map((item) => ({ value: item.id, label: item.title }))} onChange={(id) => { setSelectedChapter(id); setTime(0); }} /></div>
      <div className="grid gap-1.5"><Label htmlFor="book-player-rate">{t("book_playback_rate")}</Label><BookSelect id="book-player-rate" value={rate} options={["0.75", "1", "1.25", "1.5", "2"].map((value) => ({ value, label: `${value}×` }))} onChange={(value) => { setRate(value); if (audioRef.current) audioRef.current.playbackRate = Number(value); }} /></div>
    </div>
    {!exported && <p className="text-sm text-muted-foreground">{t("book_preview_export_hint")}</p>}
    {/* eslint-disable-next-line jsx-a11y/media-has-caption -- The active source segment is synchronized and rendered immediately below the audio player. */}
    {audio.url && <audio key={exported?.path} ref={audioRef} controls src={audio.url} preload="metadata" className="w-full" aria-label={t("book_player")} onLoadedMetadata={(event) => { event.currentTarget.playbackRate = Number(rate); setTime(event.currentTarget.currentTime); }} onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)} onSeeking={(event) => setTime(event.currentTarget.currentTime)} onSeeked={(event) => setTime(event.currentTarget.currentTime)} onRateChange={(event) => setTime(event.currentTarget.currentTime)} onEnded={() => {
      const index = book.chapters.findIndex((item) => item.id === chapter?.id);
      const next = book.chapters[index + 1]; if (next) { setSelectedChapter(next.id); setTime(0); }
    }} />}
    {image.url && <img src={image.url} alt={book.keyframes.find((item) => item.id === frame?.id)?.prompt || t("book_keyframes")} className="max-h-80 w-full rounded-lg object-contain" />}
    {text && <p className="whitespace-pre-wrap wrap-break-word text-sm">{text}</p>}
    {(audio.error || image.error) && <p role="alert" className="wrap-break-word text-sm text-destructive">{audio.error || image.error}</p>}
  </section>;
}
