import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { BookField } from "./BookFields";
import { BookSelect } from "./BookSelect";
import type { BookDocument, BookVoice } from "@/types/book";

export function BookVoices({ book, onChange, disabled, capabilities }: {
  book: BookDocument; onChange: (next: BookDocument) => void; disabled: boolean; capabilities: Record<string, unknown>;
}) {
  const { t } = useTranslation("dashboard");
  const update = (id: string, patch: Partial<BookVoice>) => onChange({ ...book, voices: { ...book.voices, [id]: { ...book.voices[id], ...patch } } });
  const add = () => {
    const id = book.voices.narrator ? `speaker-${crypto.randomUUID()}` : "narrator";
    update(id, { id, name: t(id === "narrator" ? "book_narrator" : "book_new_voice"), adapter: "voxcpm2", model: "VoxCPM2", base_url: "http://127.0.0.1:7862", voice: "", reference_audio: null, reference_audio_digest: null, language: "zh", settings: { clone_mode: "controllable", cfg_value: 2, inference_timesteps: 10, seed: 42 } });
  };
  return <section className="grid gap-4" aria-label={t("book_voices")}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">{t("book_voices")}</h2><Button variant="outline" disabled={disabled} onClick={add}>{t("book_add_voice")}</Button></div>
    <p className="text-sm text-muted-foreground">{t("book_voice_hint")}</p>
    {Object.values(book.voices).map((voice) => <fieldset disabled={disabled} key={voice.id} className="grid min-w-0 gap-3 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{voice.name || voice.id}</legend>
      <BookField label={t("book_voice_name")} value={voice.name} onChange={(name) => update(voice.id, { name })} />
      <div className="grid gap-1.5"><Label htmlFor={`adapter-${voice.id}`}>{t("book_adapter")}</Label>
        <BookSelect id={`adapter-${voice.id}`} value={voice.adapter} disabled={disabled} options={[{ value: "voxcpm2", label: "VoxCPM2" }, { value: "indextts2", label: "IndexTTS2" }, { value: "provider", label: t("book_existing_provider") }]} onChange={(adapter) => update(voice.id, { adapter, model: adapter === "voxcpm2" ? "VoxCPM2" : adapter === "indextts2" ? "IndexTTS2" : "", base_url: adapter === "voxcpm2" ? "http://127.0.0.1:7862" : adapter === "indextts2" ? "http://127.0.0.1:7861" : "", voice: "", reference_audio: voice.source_character ? voice.reference_audio : null, reference_audio_digest: voice.source_character ? voice.reference_audio_digest : null, reference_text: voice.reference_text ?? null, settings: adapter === "voxcpm2" ? { clone_mode: "controllable", cfg_value: 2, inference_timesteps: 10, seed: 42 } : {} })} />
      </div>
      <BookField label={t("book_model")} disabled={voice.adapter !== "provider"} value={voice.model} onChange={(model) => update(voice.id, { model })} />
      {voice.adapter !== "provider" && <BookField label={t("book_base_url")} value={voice.base_url} onChange={(base_url) => update(voice.id, { base_url })} />}
      {voice.adapter === "provider" && <BookField label={t("book_voice_id")} value={voice.voice} onChange={(value) => update(voice.id, { voice: value })} />}
      {voice.adapter !== "provider" && <BookField disabled={!!voice.source_character} label={t("book_reference_audio")} value={voice.reference_audio ?? ""} onChange={(value) => update(voice.id, { reference_audio: value || null })} />}
      {voice.adapter !== "provider" && <BookField disabled={!!voice.source_character} label={t("book_reference_digest")} value={voice.reference_audio_digest ?? ""} onChange={(value) => update(voice.id, { reference_audio_digest: value || null })} />}
      {voice.adapter === "voxcpm2" && <>
        <Label htmlFor={`clone-mode-${voice.id}`}>{t("book_clone_mode")}</Label>
        <BookSelect id={`clone-mode-${voice.id}`} value={String(voice.settings.clone_mode ?? "controllable")} options={[{ value: "controllable", label: t("book_vox_controllable") }, { value: "continuation", label: t("book_vox_continuation") }]} onChange={(clone_mode) => update(voice.id, { settings: { ...voice.settings, clone_mode } })} />
        <BookField label={t("book_reference_text")} value={voice.reference_text ?? ""} onChange={(reference_text) => update(voice.id, { reference_text: reference_text || null })} />
        <p className="text-sm text-muted-foreground">{t("book_vox_limits")}</p>
      </>}
      {voice.adapter === "provider" && <p className="text-sm text-muted-foreground">{t("book_provider_config_hint")}</p>}
      {voice.source_character && <p className="text-sm text-muted-foreground">{t("book_bound_character", { name: voice.source_character })}</p>}
      <BookField label={t("book_language")} value={voice.language} onChange={(language) => update(voice.id, { language })} />
    </fieldset>)}
    <details><summary className="cursor-pointer text-sm font-medium">{t("book_capabilities")}</summary>
    <div className="mt-3 grid gap-2">{Object.entries(capabilities).filter(([, value]) => typeof value === "object" && value !== null).map(([adapter, value]) => <div key={adapter} className="rounded-lg border p-3">
      <h3 className="text-sm font-semibold">{adapter}</h3>
      <ul className="mt-2 grid gap-1 text-sm">{Object.entries(value as Record<string, unknown>).map(([key, capability]) => <li key={key} className="wrap-break-word">{t(`book_cap_${key}`)}: {typeof capability === "boolean" ? t(capability ? "book_supported" : "book_unsupported") : Array.isArray(capability) ? capability.length ? capability.join(", ") : t("book_unsupported") : String(capability)}</li>)}</ul>
    </div>)}</div>
    </details>
  </section>;
}
