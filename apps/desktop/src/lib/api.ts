/** Thin wrapper over the Tauri command that talks to the Python backend. */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  BuildOutcome, Env, Genre, LibraryItem, Plan, ProgressEvent, Project, Settings,
} from "./types";

export class BackendError extends Error {
  readonly code: string;
  constructor(code: string, detail: string) {
    super(detail);
    this.code = code;
    this.name = "BackendError";
  }
}

interface Envelope<T> { ok: boolean; data?: T; error?: string; detail?: string }

async function call<T>(method: string, payload: Record<string, unknown> = {}): Promise<T> {
  let envelope: Envelope<T>;
  try {
    envelope = await invoke<Envelope<T>>("api", { method, payload });
  } catch (err) {
    throw new BackendError("bridge", String(err));
  }
  if (!envelope.ok) {
    throw new BackendError(envelope.error ?? "unknown", envelope.detail ?? "Something went wrong.");
  }
  return envelope.data as T;
}

export const api = {
  environment: () => call<Env>("environment"),
  genres: () => call<{ genres: Genre[] }>("genres").then((r) => r.genres),
  settings: () => call<Settings>("settings.get"),
  saveSettings: (settings: Partial<Settings>) =>
    call<Settings>("settings.set", { settings }),
  inspect: (path: string) => call<Project>("project.inspect", { path }),
  plan: (opts: {
    path: string; genre: string; structure: string; level: number;
    variant?: string; seed?: number; provider?: string;
  }) => call<Plan>("arrange.plan", opts),
  build: (opts: {
    path: string; genre: string; structure: string; level: number;
    arrange: boolean; extract: boolean; wav: boolean; mp3: boolean;
    midi: boolean; zip: boolean; stems: boolean; variant?: string; seed?: number;
    exportRoot?: string | null;
  }) => call<BuildOutcome>("build.run", opts),
  library: () => call<{ projects: LibraryItem[] }>("library.list").then((r) => r.projects),
  forget: (id: string) => call<{ removed: string }>("library.forget", { id }),
  testFl: (path?: string) =>
    call<{ ok: boolean; path: string | null; detail: string }>("fl.test", { path }),
};

/** Subscribe to build progress. Returns an unsubscribe function. */
export function onProgress(handler: (event: ProgressEvent) => void) {
  const promise = listen<ProgressEvent>("build-progress", (e) => handler(e.payload));
  return () => { void promise.then((un) => un()); };
}

export async function backendStatus() {
  return invoke<{ ok: boolean; python?: string; root?: string; error?: string }>(
    "backend_status",
  );
}

export const shell = {
  reveal: (path: string) => invoke<void>("reveal", { path }),
  openInFl: (flp: string, flExecutable: string | null) =>
    invoke<void>("open_in_fl", { flExecutable, flp }),
  readMedia: (path: string) => invoke<number[]>("read_media", { path }),
};
