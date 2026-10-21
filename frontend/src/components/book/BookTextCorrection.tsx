import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useEditUnit } from "@/components/shared/edit-unit/useEditUnit";
import { BookField } from "./BookFields";

export function BookTextCorrection({ id, text, disabled, apply }: { id: string; text: string; disabled: boolean; apply: (id: string, text: string) => Promise<void> }) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState(false);
  const save = useCallback(async (value: string) => { await apply(id, value); }, [apply, id]);
  const unit = useEditUnit({ source: text, save });
  if (!editing) return <div><Button variant="ghost" disabled={disabled} onClick={() => setEditing(true)}>{t("book_correct_source")}</Button></div>;
  return <div className="grid gap-2 rounded-lg border p-3">
    <p className="text-sm text-muted-foreground">{t("book_correct_source_hint")}</p>
    <BookField label={t("book_corrected_text")} multiline value={unit.value} disabled={disabled || unit.status === "saving"} onChange={unit.setValue} />
    {unit.error && <p role="alert" className="wrap-break-word text-sm text-destructive">{unit.error}</p>}
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={disabled || !unit.value.trim() || !unit.dirty || unit.status === "saving"} onClick={() => { void unit.save().then((success) => { if (success) setEditing(false); }); }}>{t("book_apply_correction")}</Button><Button variant="ghost" disabled={unit.status === "saving"} onClick={() => { unit.discard(); setEditing(false); }}>{t("book_discard")}</Button></div>
  </div>;
}
