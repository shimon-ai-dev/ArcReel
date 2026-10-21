import type { BookDocument, BookKeyframe } from "@/types/book";

/** Add chapter-local source anchors without replacing any existing illustration. */
export function planBookKeyframes(book: BookDocument, every: number): BookKeyframe[] {
  if (!Number.isSafeInteger(every) || every < 1) return book.keyframes;
  const anchored = new Set(book.keyframes.map((frame) => frame.segment_id));
  const additions = book.chapters.flatMap((chapter) => chapter.segments.flatMap((segment, index) => {
    if (index % every !== 0 || anchored.has(segment.id)) return [];
    return [{ id: `frame-${crypto.randomUUID()}`, segment_id: segment.id, offset_seconds: 0,
      prompt: chapter.segments.slice(index, index + every).map((item) => item.text).join(""), path: null,
      provider: null, model: null, reference_paths: [], status: "pending" as const, task_id: null, error: null }];
  }));
  return [...book.keyframes, ...additions];
}
