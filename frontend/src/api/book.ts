import { API } from "@/api";
import { API_BASE, throwIfNotOk, withAuth } from "@/api/transport";
import type { BookDocument, BookState } from "@/types/book";

export function bookPath(project: string) { return `/projects/${encodeURIComponent(project)}/book`; }
export const bookApi = {
  syncEpisode(project: string, episode: number): Promise<BookState> {
    return API.request(`${bookPath(project)}/episodes/${episode}/sync`, { method: "POST" });
  },
  get(project: string, signal?: AbortSignal): Promise<BookState> {
    return API.request(bookPath(project), { signal });
  },
  save(project: string, book: BookDocument): Promise<unknown> {
    return API.request(`${bookPath(project)}/document`, { method: "PUT", body: JSON.stringify(book) });
  },
  source(project: string, text: string, title: string): Promise<unknown> {
    return API.request(`${bookPath(project)}/source`, { method: "PUT", body: JSON.stringify({ text, title }) });
  },
  correctText(project: string, id: string, text: string): Promise<unknown> {
    return API.request(`${bookPath(project)}/segments/${encodeURIComponent(id)}/text`, { method: "PUT", body: JSON.stringify({ text }) });
  },
  async upload(project: string, file: File): Promise<{ path: string; duration_seconds?: number }> {
    const path = `${bookPath(project)}/assets`;
    const body = new FormData(); body.append("file", file);
    const response = await fetch(`${API_BASE}${path}`, withAuth(path, { method: "POST", body }));
    await throwIfNotOk(response, response.statusText);
    return response.json() as Promise<{ path: string; duration_seconds?: number }>;
  },
  async blob(project: string, resource: string, signal?: AbortSignal): Promise<Blob> {
    const path = `${bookPath(project)}/${resource}`;
    const response = await fetch(`${API_BASE}${path}`, withAuth(path, { signal }));
    await throwIfNotOk(response, response.statusText);
    return response.blob();
  },
};
