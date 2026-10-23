import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { bookApi } from "@/api/book";
import { BookField } from "./BookFields";
import { BookSelect } from "./BookSelect";
import { BookAudioPreview } from "./BookMedia";
import type { BookDocument, BookEffect } from "@/types/book";

export function BookEvents({ project, book, chapterId, onChange, disabled, run }: {
  project: string; book: BookDocument; chapterId: string; onChange: (next: BookDocument) => void; disabled: boolean;
  run: (action: () => Promise<void>) => void;
}) {
  const { t } = useTranslation("dashboard");
  const options = book.chapters.filter((chapter) => chapter.id === chapterId).flatMap((chapter) => chapter.segments.map((segment, index) => ({ value: segment.id, label: `${chapter.title} · ${index + 1} · ${Array.from(segment.text).slice(0, 30).join("")}` })));
  const updateEffect = (id: string, patch: Partial<BookEffect>) => onChange({ ...book, effects: book.effects.map((effect) => effect.id === id ? { ...effect, ...patch } : effect) });
  const uploadEffect = async (file: File, cue?: NonNullable<BookDocument["sound_cues"]>[number]) => {
    if (!options.length) return;
    const asset = await bookApi.upload(project, file);
    onChange({ ...book, effects: [...book.effects, {
      id: cue?.id ?? `effect-${crypto.randomUUID()}`, track: cue?.track === "sfx" ? "effects" : cue?.track ?? "effects", segment_id: cue?.segment_id ?? options[0].value, offset_seconds: 0,
      path: asset.path, duration_seconds: asset.duration_seconds ?? 1, end_segment_id: cue?.end_segment_id ?? null, volume: 1,
      fade_in_seconds: 0, fade_out_seconds: 0, loop: false, ducking: 0.25,
      source: cue?.description ?? file.name, voice_consistency_note: null,
    }] });
  };
  return <section className="grid gap-4">
    <h2 className="text-lg font-semibold">{t("book_effects")}</h2>
    {(book.sound_cues ?? []).filter((cue) => options.some((option) => option.value === cue.segment_id) && !book.effects.some((effect) => effect.id === cue.id)).map((cue) => <div key={cue.id} className="grid gap-2 rounded-lg border p-3">
      <p className="text-sm">{cue.description}</p>
      <Label htmlFor={`cue-${cue.id}`}>{t("book_cue_needs_asset")}</Label>
      <Input id={`cue-${cue.id}`} type="file" accept="audio/*" disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(() => uploadEffect(file, cue)); event.target.value = ""; }} />
    </div>)}
    <div className="grid gap-2"><Label htmlFor="book-effect-upload">{t("book_import_effect")}</Label><Input id="book-effect-upload" type="file" accept="audio/*" disabled={disabled || !options.length} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(() => uploadEffect(file)); event.target.value = ""; }} /></div>
    {book.effects.filter((effect) => options.some((option) => option.value === effect.segment_id)).map((effect) => <fieldset disabled={disabled} key={effect.id} className="grid min-w-0 gap-3 rounded-lg border p-4">
      <legend className="px-1 text-sm">{effect.source}</legend>
      <div className="grid gap-1.5"><Label htmlFor={`anchor-${effect.id}`}>{t("book_anchor")}</Label><BookSelect id={`anchor-${effect.id}`} value={effect.segment_id} options={options} disabled={disabled} onChange={(segment_id) => updateEffect(effect.id, { segment_id })} /></div>
      <div className="grid gap-1.5"><Label htmlFor={`track-${effect.id}`}>{t("book_track")}</Label><BookSelect id={`track-${effect.id}`} value={effect.track} disabled={disabled} options={["effects", "ambience", "music"].map((value) => ({ value, label: t(`book_track_${value}`) }))} onChange={(track) => updateEffect(effect.id, { track: track as BookEffect["track"] })} /></div>
      {(["offset_seconds", "duration_seconds", "volume", "fade_in_seconds", "fade_out_seconds", "ducking"] as const).map((field) => <BookField key={field} label={t(`book_${field}`)} type="number" step={0.1} value={effect[field]} onChange={(value) => updateEffect(effect.id, { [field]: Number(value) })} />)}
      <div className="flex items-center gap-2"><Checkbox id={`loop-${effect.id}`} checked={effect.loop} onCheckedChange={(value) => updateEffect(effect.id, { loop: value === true })} /><Label htmlFor={`loop-${effect.id}`}>{t("book_loop")}</Label></div>
      <div className="grid gap-1.5"><Label htmlFor={`end-${effect.id}`}>{t("book_end_anchor")}</Label><BookSelect id={`end-${effect.id}`} value={effect.end_segment_id ?? ""} disabled={disabled} options={[{ value: "", label: t("book_use_duration") }, ...options]} onChange={(end_segment_id) => updateEffect(effect.id, { end_segment_id: end_segment_id || null })} /></div>
      <BookField label={t("book_consistency_note")} value={effect.voice_consistency_note ?? ""} onChange={(value) => updateEffect(effect.id, { voice_consistency_note: value || null })} />
      <BookField label={t("book_sound_source")} value={effect.source} onChange={(source) => updateEffect(effect.id, { source })} />
      <BookAudioPreview project={project} path={effect.path} />
      <div className="grid gap-2"><Label htmlFor={`replace-${effect.id}`}>{t("book_replace_media")}</Label><Input id={`replace-${effect.id}`} type="file" accept="audio/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) run(async () => { const asset = await bookApi.upload(project, file); updateEffect(effect.id, { path: asset.path }); }); event.target.value = ""; }} /></div>
      <div><Button variant="outline" onClick={() => onChange({ ...book, effects: book.effects.filter((item) => item.id !== effect.id) })}>{t("book_remove_draft")}</Button></div>
    </fieldset>)}
  </section>;
}
