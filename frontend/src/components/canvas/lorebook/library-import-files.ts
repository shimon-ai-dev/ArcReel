/** Only explicitly referenced browser-selected files may leave the browser. */
export function selectManifestFiles(manifest: string, selected: File[]):
  | { files: File[]; error: null }
  | { files: []; error: "manifest" | "missing" | "duplicate"; names: string[] } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(manifest);
  } catch {
    return { files: [], error: "manifest", names: [] };
  }
  if (!parsed || typeof parsed !== "object" || !("entries" in parsed) || !Array.isArray(parsed.entries)) {
    return { files: [], error: "manifest", names: [] };
  }
  const names = new Set<string>();
  for (const entry of parsed.entries as unknown[]) {
    if (!entry || typeof entry !== "object") return { files: [], error: "manifest", names: [] };
    const views: unknown[] = "views" in entry && Array.isArray(entry.views) ? entry.views : [];
    const voice = "voice" in entry ? entry.voice : null;
    const clips: unknown[] = voice && typeof voice === "object" && "clips" in voice && Array.isArray(voice.clips) ? voice.clips : [];
    for (const item of [...views, ...clips]) {
      if (!item || typeof item !== "object" || !("file" in item) || typeof item.file !== "string" || !item.file || /[/\\]/.test(item.file)) {
        return { files: [], error: "manifest", names: [] };
      }
      names.add(item.file);
    }
  }
  const files: File[] = [];
  const duplicates: string[] = [];
  const missing: string[] = [];
  for (const name of names) {
    const matches = selected.filter((file) => file.name === name);
    if (matches.length === 0) missing.push(name);
    else if (matches.length > 1) duplicates.push(name);
    else files.push(matches[0]);
  }
  if (duplicates.length) return { files: [], error: "duplicate", names: duplicates };
  if (missing.length) return { files: [], error: "missing", names: missing };
  return { files, error: null };
}
