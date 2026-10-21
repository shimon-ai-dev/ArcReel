import { useState } from "react";
import { planBookKeyframes } from "./keyframe-plan";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { bookApi } from "@/api/book";
import { BookField } from "./BookFields";
import { BookSelect } from "./BookSelect";
import { BookAudioPreview } from "./BookMedia";
import type { BookDocument, BookEffect, BookKeyframe } from "@/types/book";

export function BookEvents({ project, book, illustrated, onChange, disabled, run, generateFrame }: {
  project: string; book: BookDocument; illustrated: boolean; onChange: (next: BookDocument) => void; disabled: boolean;
  run: (action: () => Promise<void>) => void; generateFrame: (id: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [density, setDensity] = useState(5);
  const options = book.chapters.flatMap((chapter) => chapter.segments.map((segment, index) => ({ value: segment.id, label: `${chapter.title} · ${index + 1} · ${segment.text.slice(0, 30)}` })));
  const updateEffect = (id: string, patch: Partial<BookEffect>) => onChange({ ...book, effects: book.effects.map((effect) => effect.id === id ? { ...effect, ...patch } : effect) });
  const updateFrame = (id: string, patch: Partial<BookKeyframe>) => onChange({ ...book, keyframes: book.keyframes.map((frame) => frame.id === id ? { ...frame, ...patch } : frame) });
  const uploadEffect = async (file: File) => {
    if (!options.length) return;
    const asset = await bookApi.upload(project, file);
    onChange({ ...book, effects: [...book.effects, {
      id: `effect-${crypto.randomUUID()}`, track: "effects", segment_id: options[0].value, offset_seconds: 0,
      path: asset.path, duration_seconds: asset.duration_seconds ?? 1, end_segment_id: null, volume: 1,
      fade_in_seconds: 0, fade_out_seconds: 0, loop: false, ducking: 0.25,
      source: file.name, voice_consistency_note: null,
    }] });
  };
  return <section className="grid gap-4">
    <h2 className="text-lg font-semibold">{t("book_effects")}</h2>
    <div className="grid gap-2"><Label htmlFor="book-effect-upload">{t("book_import_effect")}</Label><Input id="book-effect-upload" type="file" accept="audio/*" disabled={disabled || !options.length} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(() => uploadEffect(file)); event.target.value = ""; }} /></div>
    {book.effects.map((effect) => <fieldset disabled={disabled} key={effect.id} className="grid min-w-0 gap-3 rounded-lg border p-4">
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
    {illustrated && <>
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">{t("book_keyframes")}</h2><Button variant="outline" disabled={disabled || !options.length} onClick={() => onChange({ ...book, keyframes: [...book.keyframes, { id: `frame-${crypto.randomUUID()}`, segment_id: options[0].value, offset_seconds: 0, prompt: "", path: null, provider: null, model: null, reference_paths: [], status: "pending", task_id: null, error: null }] })}>{t("book_add_keyframe")}</Button></div>
      <p className="text-sm text-muted-foreground">{t("book_keyframe_hint")}</p>
      <div className="grid gap-2 rounded-lg border p-3">
        <BookField label={t("book_image_density")} type="number" min={1} step={1} value={density} disabled={disabled} onChange={(value) => setDensity(Number(value))} />
        <p className="text-sm text-muted-foreground">{t("book_image_density_hint")}</p>
        <div><Button variant="outline" disabled={disabled || !options.length || !Number.isSafeInteger(density) || density < 1} onClick={() => onChange({ ...book, keyframes: planBookKeyframes(book, density) })}>{t("book_plan_images")}</Button></div>
      </div>
      {book.keyframes.map((frame, index) => <fieldset disabled={disabled || frame.status === "queued" || frame.status === "running"} key={frame.id} className="grid min-w-0 gap-3 rounded-lg border p-4">
        <legend className="px-1 text-sm">{t("book_keyframe_number", { number: index + 1 })}</legend>
        <div className="grid gap-1.5"><Label htmlFor={`anchor-${frame.id}`}>{t("book_anchor")}</Label><BookSelect id={`anchor-${frame.id}`} value={frame.segment_id} options={options} disabled={disabled} onChange={(segment_id) => updateFrame(frame.id, { segment_id })} /></div>
        <BookField label={t("book_offset_seconds")} value={frame.offset_seconds} type="number" min={0} step={0.1} onChange={(value) => updateFrame(frame.id, { offset_seconds: Number(value) })} />
        <BookField label={t("book_image_prompt")} value={frame.prompt} multiline onChange={(prompt) => updateFrame(frame.id, { prompt })} />
        <BookField label={t("book_image_references")} value={frame.reference_paths.join("\n")} multiline onChange={(value) => updateFrame(frame.id, { reference_paths: value.split("\n").map((path) => path.trim()).filter(Boolean) })} />
        <BookField label={t("book_image_provider")} value={frame.provider ?? ""} onChange={(provider) => updateFrame(frame.id, { provider: provider || null })} />
        <BookField label={t("book_model")} value={frame.model ?? ""} onChange={(model) => updateFrame(frame.id, { model: model || null })} />
        <div className="grid gap-2"><Label htmlFor={`image-${frame.id}`}>{t("book_import_image")}</Label><Input id={`image-${frame.id}`} type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) run(async () => { const asset = await bookApi.upload(project, file); updateFrame(frame.id, { path: asset.path }); }); event.target.value = ""; }} /></div>
        <p className="text-sm text-muted-foreground">{t(`book_status_${frame.status}`)}</p>
        {frame.error && <p role="alert" className="wrap-break-word text-sm text-destructive">{frame.error}</p>}
        <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => generateFrame(frame.id)}>{t("book_generate_image")}</Button><Button variant="outline" onClick={() => onChange({ ...book, keyframes: book.keyframes.filter((item) => item.id !== frame.id) })}>{t("book_remove_draft")}</Button></div>
      </fieldset>)}
    </>}
  </section>;
}
