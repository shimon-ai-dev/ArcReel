export interface ExternalLibraryIdentity {
  library_id: string;
  external_id: string;
  baseline?: string | null;
  look?: string | null;
  action?: string | null;
  state?: string | null;
  archive_version: string;
  product_version?: string | null;
  status: "pending" | "approved" | "rejected";
  frozen: boolean;
}

export interface ExternalReferenceView {
  path: string;
  sha256: string;
  archive_version: string;
  product_version?: string | null;
  width: number;
  height: number;
  role: "identity" | "look" | "action" | "space";
  view: string;
  framing: string;
  archive_path?: string | null;
  product_path?: string | null;
  frozen: boolean;
  confirmed: boolean;
}

export interface ExternalVoice {
  library_id: string;
  external_id: string;
  voice_id: string;
  version: string;
  baseline?: string | null;
  baseline_status: "pending" | "confirmed";
  status: "pending" | "approved" | "rejected";
  technical_pass: boolean;
  agent_listened: boolean;
  model_adapted: boolean;
  clone_tested: boolean;
  clips: Array<{
    path: string;
    sha256: string;
    transcript?: string | null;
    archive_path?: string | null;
    product_path?: string | null;
    frozen: boolean;
    confirmed: boolean;
  }>;
  selected_clip?: string | null;
}

export interface LibraryImportEntry {
  asset_type: "character" | "scene";
  name: string;
  external_id: string;
  baseline?: string | null;
  look?: string | null;
  action?: string | null;
  state?: string | null;
  archive_version: string;
  product_version?: string | null;
  previous_archive_version?: string | null;
  previous_product_version?: string | null;
  view_changes?: Array<{
    role: ExternalReferenceView["role"];
    view: string;
    framing: string;
    operation: "add" | "update" | "unchanged" | "retain";
    previous_sha256: string | null;
    sha256: string;
    previous_archive_version: string | null;
    archive_version: string;
  }>;
  operation: "add" | "update" | "unchanged" | "conflict";
  changes: string[];
  warnings: string[];
  conflicts: string[];
}

export interface ExternalLibraryPreview {
  preview_token: string;
  can_apply: boolean;
  summary: {
    added: number;
    updated: number;
    unchanged: number;
    conflicts: number;
    pending_voice_bindings: number;
    deduplicated_files: number;
  };
  entries: LibraryImportEntry[];
  applied?: boolean;
}
