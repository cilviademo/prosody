/** Shapes returned by the Python backend. Mirrors prosody_core/api.py. */

export type HealthStatus =
  | "READY" | "PARTIAL" | "REQUIRES_FREEZE" | "BLOCKED" | "UNKNOWN";

export type StageStatus =
  | "pending" | "running" | "ok" | "warning" | "failed" | "skipped";

export type Tier = "native" | "pack" | "none";

export interface RoleFlag {
  role: string;
  /** Confidently detected. */
  present: boolean;
  /** Detected below the confidence threshold; the engine still uses it. */
  likely: boolean;
  label: string;
}

export interface Uncertain {
  channel: number | null;
  name: string | null;
  role: string;
  confidence: number;
  sources: string[];
}

export interface HealthCheck { name: string; ok: boolean | null; detail: string }

export interface Project {
  id: string;
  name: string;
  path: string;
  hash: string;
  tempo: number | null;
  key: string | null;
  keyConfidence: number;
  lengthBars: number;
  durationSeconds: number | null;
  timeSignature: [number, number];
  flVersion: string | null;
  state: string;
  counts: {
    patterns: number; channels: number; plugins: number; mixerTracks: number;
    notes: number; playlistClips: number; samplesMissing: number;
  };
  roles: RoleFlag[];
  uncertain: Uncertain[];
  patternRoles: { pattern: number; name: string; role: string; notes: number }[];
  health: {
    status: HealthStatus; label: string; checks: HealthCheck[]; missing: string[];
  };
  canArrange: boolean;
  warnings: { code: string; message: string; severity: string }[];
}

export interface PlanSection {
  name: string; label: string; startBar: number; bars: number;
  energy: number; roles: string[]; dropoutBars: number;
}

export interface Lane {
  role: string; label: string; blocks: { startBar: number; bars: number }[];
}

export interface Plan {
  variant: string; genre: string; structure: string; level: number; seed: number;
  tempo: number; totalBars: number; durationSeconds: number; planner: string;
  notes: string | null; sections: PlanSection[]; lanes: Lane[];
  patternRoles: { pattern: number; name: string; role: string }[];
}

export interface Artifact {
  kind: string; path: string; label: string; bytes: number;
}

export interface Stage {
  name: string; status: StageStatus; detail: string; artifacts: Artifact[];
}

export interface BuildOutcome {
  projectId: string; outDir: string; tier: Tier; message: string; ok: boolean;
  sourceUnchanged: boolean; flpPath: string | null;
  previewWav: string | null; previewMp3: string | null;
  stages: Stage[]; artifacts: Artifact[];
}

export interface Env {
  platform: string; python: string; pyflp: string; compatShim: boolean;
  flExecutable: string | null; flDiscovery: string; ffmpeg: string | null;
  canRender: boolean; renderReason: string;
  stemStrategy: string | null; stemReason: string;
  workspace: string; exportRoot: string; providers: string[];
}

export interface Genre {
  id: string; label: string; structures: string[]; rules: string[];
}

export interface LibraryItem {
  id: string; name: string; path: string; tempo: number | null;
  key: string | null; lengthBars: number; genre: string | null;
  status: string; health: HealthStatus; updatedAt: string;
  outDir: string | null; exists: boolean;
}

export interface Settings {
  fl_executable: string | null;
  export_root: string | null;
  audio_format: string;
  wav_bit_depth: number;
  creativity_level: number;
  ai_provider: string;
  structure: string;
  render_enabled: boolean;
  gui_stems_enabled: boolean;
}

export interface ProgressEvent { stage: string; status: string; detail: string }

/** What the shell reports about itself on boot. */
export interface BackendStatus {
  ok: boolean;
  portable: boolean;
  documents: string;
  state: string;
  logs: string;
  coreVersion?: string;
  coreExecutable?: string;
  error?: string;
}
