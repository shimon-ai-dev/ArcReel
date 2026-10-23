export interface BookPerformance {
  emotion: string | null;
  intensity: number;
  emotion_vector: number[] | null;
  style: string | null;
  speed: number | null;
  nonverbal: string | null;
}
export interface BookVoice {
  source_character?: string | null;
  id: string; name: string; adapter: string; model: string; base_url: string; voice: string;
  reference_text?: string | null; reference_audio: string | null; reference_audio_digest: string | null;
  language: string; settings: Record<string, string | number | boolean>;
}
export interface BookAudioVersion {
  id: string; path: string; duration_seconds: number; fingerprint: string; created_at: string; content_digest: string | null;
}
export interface BookSegment {
  unit_id?: string | null;
  id: string; source_start: number; source_end: number; text: string;
  speaker_id: string; speaker_confirmed: boolean; performance: BookPerformance; pause_after_seconds: number;
  pronunciation: { source_start: number; source_end: number; original: string; spoken: string }[];
  audio_versions: BookAudioVersion[]; selected_audio_version: string | null;
  status: "pending" | "queued" | "running" | "succeeded" | "failed"; task_id: string | null; error: string | null;
}
export interface BookChapter { episode?: number; id: string; title: string; segments: BookSegment[] }
export interface BookEffect {
  id: string; track: "effects" | "ambience" | "music"; segment_id: string; offset_seconds: number;
  path: string; duration_seconds: number; end_segment_id: string | null; volume: number;
  fade_in_seconds: number; fade_out_seconds: number; loop: boolean; ducking: number;
  source: string; voice_consistency_note: string | null;
}
export interface BookKeyframeVersion {
  id: string; path: string; prompt: string; provider: string | null; model: string | null;
  reference_paths: string[]; created_at: string; content_digest: string;
}
export interface BookKeyframe {
  id: string; segment_id: string; offset_seconds: number; prompt: string; path: string | null;
  provider: string | null; model: string | null; reference_paths: string[];
  status: BookSegment["status"]; task_id: string | null; error: string | null; versions?: BookKeyframeVersion[];
}
export interface BookDocument {
  origin?: string;
  sound_cues?: { id: string; episode: number; unit_id: string; segment_id: string; end_segment_id: string | null; description: string; track: "ambience" | "sfx" | "music" }[];
  schema_version: 1; revision: number; title: string; original_text: string; normalized_text: string;
  chapters: BookChapter[]; voices: Record<string, BookVoice>; effects: BookEffect[]; keyframes: BookKeyframe[];
}
export interface BookSegmentTiming {
  id: string; chapter_id: string; start_seconds: number; duration_seconds: number;
  pause_after_seconds: number; audio_path: string | null;
}
export interface BookEventTiming {
  id: string; chapter_id: string; start_seconds: number; duration_seconds: number; path: string | null;
}
export interface BookTimeline {
  segments: BookSegmentTiming[]; effects: BookEventTiming[]; keyframes: BookEventTiming[];
  duration_seconds: number; missing_segment_ids: string[];
}
export interface BookState {
  exports?: BookExports | null;
  book: BookDocument | null; timeline: BookTimeline | null;
  capabilities: Record<string, unknown>;
  status: { stale_episodes?: number[]; ready_to_export?: boolean; missing_effects?: string[]; complete: boolean; coverage_valid: boolean; missing_audio: string[]; missing_images: string[] };
  tasks: { task_id?: string; id?: string; task_type: string; status: string; error?: string | null; error_message?: string | null }[];
}
export interface BookExports {
  chapters: { id: string; path: string; duration_seconds: number }[];
  whole_book_path: string; archive_path: string; manifest_path: string; player_path: string;
}
