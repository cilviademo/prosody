import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type {
  BackendStatus, BuildOutcome, Env, Genre, InterruptedJob, LibraryItem,
  ProgressEvent, Project, Settings,
} from "./lib/types";
import { api, backendStatus, onProgress, saveWindow, shell } from "./lib/api";
import { Home } from "./views/Home";
import { ProjectView } from "./views/ProjectView";
import { ArrangeView, type ExportChoices } from "./views/ArrangeView";
import { Progress, Result } from "./views/BuildView";
import { Library } from "./views/Library";
import { SettingsView } from "./views/Settings";
import { Diagnostics } from "./views/Diagnostics";
import { Button, Note } from "./components/ui";

/**
 * The Prosody mark: three strokes of unequal height — a stress pattern.
 * Bars survive an 11px render where a thin star collapses into a plus sign.
 */
const Mark = () => (
  <svg className="mark" viewBox="0 0 10 11" fill="none" aria-hidden="true">
    <rect x="0" y="1"   width="2" height="9" fill="currentColor" />
    <rect x="4" y="4.5" width="2" height="5.5" fill="currentColor" opacity="0.55" />
    <rect x="8" y="3"   width="2" height="7" fill="currentColor" opacity="0.78" />
  </svg>
);

type Tab = "finish" | "library" | "settings";
type Step = "home" | "project" | "configure" | "building" | "result";

const DEFAULT_SETTINGS: Settings = {
  fl_executable: null, export_root: null, audio_format: "wav",
  wav_bit_depth: 24, creativity_level: 0, ai_provider: "rules",
  structure: "balanced", render_enabled: false, gui_stems_enabled: false,
};

export default function App() {
  const [tab, setTab] = useState<Tab>("finish");
  const [step, setStep] = useState<Step>("home");

  const [env, setEnv] = useState<Env | null>(null);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  // Builds that never reported finishing. Surfaced once at startup rather than
  // cleaned up silently: the folder may hold the only copy of something the
  // user wants (HARDENING P0.4).
  const [interrupted, setInterrupted] = useState<InterruptedJob[]>([]);

  const [project, setProject] = useState<Project | null>(null);
  const [mode, setMode] = useState<"extract" | "arrange" | "both">("both");
  const [outcome, setOutcome] = useState<BuildOutcome | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);

  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The path that failed to open, so its event inventory can be copied: the
  // report that finishes a parser diagnosis without sharing the project.
  const [failedPath, setFailedPath] = useState<string | null>(null);
  const [inventoryCopied, setInventoryCopied] = useState(false);
  const [status, setStatus] = useState<BackendStatus | null>(null);

  const pageRef = useRef<HTMLDivElement | null>(null);

  // Each screen starts at the top. Without this the scroll position carries
  // over and a new screen appears already scrolled halfway down.
  useEffect(() => {
    pageRef.current?.scrollTo({ top: 0 });
  }, [step, tab]);

  const refreshLibrary = useCallback(() => {
    api.library().then(setLibrary).catch(() => undefined);
  }, []);

  // -- boot ---------------------------------------------------------------- //
  const loadWorkspace = useCallback(async () => {
    const [environment, genreList, stored] = await Promise.all([
      api.environment(), api.genres(), api.settings(),
    ]);
    setEnv(environment);
    setGenres(genreList);
    setSettings({ ...DEFAULT_SETTINGS, ...stored });
    refreshLibrary();
  }, [refreshLibrary]);

  useEffect(() => {
    void (async () => {
      let reported: BackendStatus;
      try {
        reported = await backendStatus();
      } catch (e) {
        reported = {
          ok: false, portable: false, documents: "", state: "", logs: "",
          error: String(e),
        };
      }
      setStatus(reported);
      if (!reported.ok) return;
      try {
        await loadWorkspace();
      } catch (e) {
        setStatus({ ...reported, ok: false, error: String((e as Error).message ?? e) });
      }
    })();
  }, [loadWorkspace]);

  // Remember where the window was left. The DOM only fires `resize`, so a
  // window that is dragged to another monitor and never resized would be
  // restored to its old screen; Tauri's own events cover both.
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const unlisten: Array<() => void> = [];

    const remember = () => {
      window.clearTimeout(timer);
      // Dragging emits a move event per frame; only the resting place matters.
      timer = window.setTimeout(() => {
        void saveWindow({
          width: window.outerWidth, height: window.outerHeight,
          x: window.screenX, y: window.screenY,
        });
      }, 500);
    };

    void (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const w = getCurrentWindow();
        const off = await Promise.all([w.onMoved(remember), w.onResized(remember)]);
        if (cancelled) off.forEach((fn) => fn());
        else unlisten.push(...off);
      } catch {
        // Not running under Tauri (vite preview); the DOM listener is enough.
        window.addEventListener("resize", remember);
        unlisten.push(() => window.removeEventListener("resize", remember));
      }
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      unlisten.forEach((fn) => fn());
    };
  }, []);

  // -- open a project ------------------------------------------------------ //
  const openProject = useCallback((path: string) => {
    setOpening(true);
    setError(null);
    setFailedPath(null);
    setInventoryCopied(false);
    api
      .inspect(path)
      .then((p) => {
        setProject(p);
        setOutcome(null);
        setTab("finish");
        setStep("project");
        refreshLibrary();
      })
      .catch((e) => {
        setError(String((e as Error).message ?? e));
        setFailedPath(path);
      })
      .finally(() => setOpening(false));
  }, [refreshLibrary]);

  const copyInventory = useCallback(async (path: string) => {
    try {
      const inv = await api.events(path);
      await navigator.clipboard.writeText(inv.report);
      setInventoryCopied(true);
    } catch {
      setInventoryCopied(false);
    }
  }, []);

  // Look for interrupted builds once, at startup.
  useEffect(() => {
    void api
      .interrupted()
      .then((found) => setInterrupted(found.interrupted))
      .catch(() => setInterrupted([]));
  }, []);

  // -- native file drop ---------------------------------------------------- //
  useEffect(() => {
    let dispose: (() => void) | undefined;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (event.payload.type !== "drop") return;
        const paths = event.payload.paths ?? [];
        const flp = paths.find((p) => p.toLowerCase().endsWith(".flp"));
        if (flp) {
          openProject(flp);
        } else if (paths.length) {
          setError("That is not an .flp file. Drop an FL Studio project.");
        }
      })
      .then((un) => { dispose = un; })
      .catch(() => undefined);
    return () => dispose?.();
  }, [openProject]);

  // -- build progress ------------------------------------------------------ //
  useEffect(() => onProgress((e) => setEvents((prev) => [...prev, e])), []);

  const runBuild = useCallback(
    (opts: {
      genre: string; structure: string; level: number; variant: string;
      seed: number; exports: ExportChoices;
    }) => {
      if (!project) return;
      setEvents([]);
      setStep("building");
      setError(null);

      api
        .build({
          path: project.path,
          genre: opts.genre,
          structure: opts.structure,
          level: opts.level,
          variant: opts.variant,
          seed: opts.seed,
          arrange: mode !== "extract",
          extract: true,
          wav: opts.exports.wav,
          mp3: opts.exports.mp3,
          midi: opts.exports.midi,
          zip: opts.exports.zip,
          stems: opts.exports.stems,
          exportRoot: settings.export_root,
        })
        .then((result) => {
          setOutcome(result);
          setStep("result");
          refreshLibrary();
        })
        .catch((e) => {
          setError(String((e as Error).message ?? e));
          setStep("configure");
        });
    },
    [project, mode, settings.export_root, refreshLibrary],
  );

  const changeSettings = useCallback((next: Partial<Settings>) => {
    setSettings((prev) => ({ ...prev, ...next }));
    api
      .saveSettings(next)
      .then((saved) => {
        setSettings({ ...DEFAULT_SETTINGS, ...saved });
        return api.environment();
      })
      .then(setEnv)
      .catch(() => undefined);
  }, []);

  if (status && !status.ok) {
    return (
      <div className="shell">
        <header className="titlebar">
          <span className="wordmark"><Mark />Prosody</span>
        </header>
        <div className="page">
          <Diagnostics
            status={status}
            onRecovered={(next) => {
              setStatus(next);
              void loadWorkspace().catch((e) =>
                setStatus({ ...next, ok: false, error: String(e) }));
            }}
          />
        </div>
      </div>
    );
  }

  const flPath = settings.fl_executable ?? env?.flExecutable ?? null;

  return (
    <div className="shell">
      <header className="titlebar">
        <span className="wordmark">
          <Mark />
          Prosody
        </span>
        <nav className="nav">
          {(["finish", "library", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              aria-current={tab === t ? "page" : undefined}
              onClick={() => {
                setTab(t);
                if (t === "library") refreshLibrary();
              }}
            >
              {t}
            </button>
          ))}
        </nav>
        <span className="grow" />
        {/* "Ready" is a claim about rendering. A configured path proves
            nothing about that; only a passing Test does, and the studio PC
            showed green after a failed one (TESTING_HANDOFF P1.1). */}
        <button
          className="status-chip"
          data-on={Boolean(env?.canRender && env?.renderTested)}
          onClick={() => setTab("settings")}
          type="button"
          title={env?.renderReason}
        >
          <span className="led" aria-hidden="true" />
          {env?.canRender && env?.renderTested
            ? "FL Studio ready"
            : env?.canRender
              ? "FL Studio configured · render untested"
              : "FL Studio not configured"}
        </button>
      </header>

      {interrupted.length > 0 && (
        <div className="interrupted" role="status">
          <strong>
            {interrupted.length === 1
              ? "A build did not finish."
              : `${interrupted.length} builds did not finish.`}
          </strong>{" "}
          {interrupted[0].name} stopped at “{interrupted[0].lastStage}”. Your
          original project was not touched. The folder is kept so you can look
          at what it did produce.
          <div className="row" style={{ marginTop: "var(--s4)" }}>
            <Button onClick={() => void shell.reveal(interrupted[0].outDir)}>
              Open folder
            </Button>
            <Button
              onClick={async () => {
                // Reuses every stage whose hashes still match; re-verifies
                // the source first; writes to a new folder.
                const outcome = await api.resumeJob(interrupted[0].outDir);
                setOutcome(outcome);
                setTab("finish");
                setStep("result");
                setInterrupted((await api.interrupted()).interrupted);
              }}
            >
              Resume
            </Button>
            <Button
              onClick={async () => {
                await api.discardJob(interrupted[0].outDir);
                setInterrupted((await api.interrupted()).interrupted);
              }}
            >
              Discard it
            </Button>
            <Button onClick={() => setInterrupted([])}>Dismiss</Button>
          </div>
        </div>
      )}

      {env?.safeMode && (
        <div className="safe-mode" role="status">
          <strong>Safe Mode.</strong> Prosody will not write files or start FL
          Studio. You can inspect projects, browse the Library and read
          Diagnostics. To leave Safe Mode, close Prosody, delete{" "}
          <span className="mono">safemode.flag</span> from the Prosody folder if
          it is there, and start it again without holding Shift.
        </div>
      )}

      <div className="page" ref={pageRef}>
        {tab === "finish" && step === "home" && (
          <Home
            onOpen={openProject}
            recent={library}
            busy={opening}
            error={error}
            errorAction={failedPath ? (
              <div className="row" style={{ marginTop: "var(--s4)" }}>
                <Button onClick={() => void copyInventory(failedPath)}>
                  {inventoryCopied ? "Copied" : "Copy event inventory"}
                </Button>
                <span className="copy" style={{ fontSize: 12, opacity: 0.8 }}>
                  ids, counts and name previews only — no notes, plugin state or sample paths
                </span>
              </div>
            ) : undefined}
          />
        )}

        {tab === "finish" && step === "project" && project && (
          <ProjectView
            project={project}
            onBack={() => setStep("home")}
            onChoose={(chosen) => { setMode(chosen); setStep("configure"); }}
          />
        )}

        {tab === "finish" && step === "configure" && project && (
          <>
            {error && (
              <div className="view" style={{ paddingBottom: 0 }}>
                <Note strong heading="Build failed">{error}</Note>
              </div>
            )}
            <ArrangeView
              project={project}
              genres={genres}
              env={env}
              mode={mode}
              onBack={() => setStep("project")}
              onBuild={runBuild}
            />
          </>
        )}

        {tab === "finish" && step === "building" && <Progress events={events} />}

        {tab === "finish" && step === "result" && outcome && (
          <Result
            outcome={outcome}
            flExecutable={flPath}
            onDone={() => { setStep("home"); setProject(null); }}
            onAgain={() => setStep("configure")}
          />
        )}

        {tab === "library" && (
          <Library
            items={library}
            genres={genres}
            onOpen={openProject}
            onReveal={(dir) => void shell.reveal(dir)}
          />
        )}

        {tab === "settings" && (
          <SettingsView settings={settings} env={env} onChange={changeSettings} />
        )}
      </div>
    </div>
  );
}
