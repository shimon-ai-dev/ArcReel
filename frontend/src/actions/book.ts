import { API } from "@/api";
import { useTasksStore, isResourceBusy, type ResourceKind } from "@/stores/tasks-store";

async function submitBook(project: string, kind: ResourceKind, ids: string[], endpoint: string, body: unknown) {
  const store = useTasksStore.getState();
  if (ids.some((id) => isResourceBusy(kind, project, id))) return;
  const marks = ids.map((id) => store.beginOptimisticActive(project, kind, id, kind));
  try {
    const response = await API.enqueueBookTask(project, endpoint, body);
    marks.forEach((mark) => mark.settle(response.task_ids));
    return response;
  } catch (error) {
    marks.forEach((mark) => mark.rollback());
    throw error;
  }
}
export function generateBookSpeech(project: string, ids: string[], force = false) {
  return submitBook(project, "book_tts", ids, "/generate", { segment_ids: ids, force });
}
export function generateBookKeyframe(project: string, id: string) {
  return submitBook(project, "book_keyframe", [id], `/keyframes/${encodeURIComponent(id)}/generate`, {});
}
export function exportBook(project: string, format: "wav" | "mp3") {
  return submitBook(project, "book_export", ["book"], "/export", { format });
}
