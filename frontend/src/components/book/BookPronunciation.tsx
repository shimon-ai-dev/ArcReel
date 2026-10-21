import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { BookField } from "./BookFields";
import type { BookSegment } from "@/types/book";

export function BookPronunciation({ segment, update, disabled }: { segment: BookSegment; update: (next: BookSegment["pronunciation"]) => void; disabled: boolean }) {
  const { t } = useTranslation("dashboard");
  return <details>
    <summary className="cursor-pointer text-sm font-medium">{t("book_pronunciation")}</summary>
    <p className="my-2 text-sm text-muted-foreground">{t("book_pronunciation_hint")}</p>
    <div className="grid gap-3">{segment.pronunciation.map((item, index) => {
      const change = (patch: Partial<typeof item>) => {
        const next = { ...item, ...patch };
        next.original = segment.text.slice(next.source_start - segment.source_start, next.source_end - segment.source_start);
        update(segment.pronunciation.map((value, at) => at === index ? next : value));
      };
      return <fieldset key={index} disabled={disabled} className="grid gap-2 rounded-lg border p-3">
        <BookField label={t("book_pronunciation_start")} value={item.source_start} type="number" min={segment.source_start} max={segment.source_end - 1} step={1} onChange={(value) => change({ source_start: Number(value) })} />
        <BookField label={t("book_pronunciation_end")} value={item.source_end} type="number" min={segment.source_start + 1} max={segment.source_end} step={1} onChange={(value) => change({ source_end: Number(value) })} />
        <p className="wrap-break-word text-sm">{item.original}</p>
        <BookField label={t("book_pronunciation_spoken")} value={item.spoken} onChange={(spoken) => change({ spoken })} />
        <div><Button variant="outline" onClick={() => update(segment.pronunciation.filter((_, at) => at !== index))}>{t("book_remove_draft")}</Button></div>
      </fieldset>;
    })}</div>
    <Button variant="outline" disabled={disabled} onClick={() => update([...segment.pronunciation, { source_start: segment.source_start, source_end: segment.source_start + 1, original: segment.text.slice(0, 1), spoken: segment.text.slice(0, 1) }])}>{t("book_add_pronunciation")}</Button>
  </details>;
}
