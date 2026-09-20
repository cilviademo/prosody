import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type {
  BuildOutcome, Env, Genre, LibraryItem, ProgressEvent, Project, Settings,
} from "./lib/types";
import { api, backendStatus, onProgress, shell } from "./lib/api";
import { Home } from "./views/Home";
import { ProjectView } from "./views/ProjectView";
import { ArrangeView, type ExportChoices } from "./views/ArrangeView";
import { Progress, Result } from "./views/BuildView";
import { Library } from "./views/Library";
import { SettingsView } from "./views/Settings";
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

  const [project, setProject] = useState<Project | null>(null);
  const [mode, setMode] = useState<"extract" | "arrange" | "both">("both");
  const [outcome, setOutcome] = useState<BuildOutcome | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);

  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

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
  useEffect(() => {
    void (async () => {
      const status = await backendStatus().catch((e) => ({ ok: false, error: String(e) }));
      if (!status.ok) {
        setFatal(status.error ?? "The Prosody backend could not be reached.");
        return;
      }
      try {
        const [environment, genreList, stored] = await Promise.all([
          api.environment(), api.genres(), api.settings(),
        ]);
        setEnv(environment);
        setGenres(genreList);
        setSettings({ ...DEFAULT_SETTINGS, ...stored });
        refreshLibrary();
      } catch (e) {
        setFatal(String((e as Error).message ?? e));
      }
    })();
  }, [refreshLibrary]);

  // -- open a project ------------------------------------------------------ //
  const openProject = useCallback((path: string) => {
    setOpening(true);
    setError(null);
    api
      .inspect(path)
      .then((p) => {
        setProject(p);
        setOutcome(null);
        setTab("finish");
        setStep("project");
        refreshLibrary();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setOpening(false));
  }, [refreshLibrary]);

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

  if (fatal) {
    return (
      <div className="shell">
        <header className="titlebar">
          <span className="wordmark"><Mark />Prosody</span>
        </header>
        <div className="page" ref={pageRef}>
          <div className="view enter">
            <div className="label">Startup</div>
            <h1 className="title" style={{ marginTop: "var(--s3)" }}>
              Prosody could not start
            </h1>
            <div style={{ marginTop: "var(--s5)" }}>
              <Note strong heading="Backend unreachable">{fatal}</Note>
            </div>
            <p className="copy" style={{ marginTop: "var(--s5)" }}>
              Prosody needs Python 3.10 or newer with its backend package
              available. Install Python, or set{" "}
              <span className="mono">PROSODY_PYTHON</span> to the interpreter you
              want it to use, then restart.
            </p>
            <div style={{ marginTop: "var(--s6)" }}>
              <Button onClick={() => window.location.reload()}>Try again</Button>
            </div>
          </div>
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
        <button
          className="status-chip"
          data-on={Boolean(env?.canRender)}
          onClick={() => setTab("settings")}
          type="button"
          title={env?.renderReason}
        >
          <span className="led" aria-hidden="true" />
          {env?.canRender ? "FL Studio ready" : "FL Studio not configured"}
        </button>
      </header>

      <div className="page" ref={pageRef}>
        {tab === "finish" && step === "home" && (
          <Home onOpen={openProject} recent={library} busy={opening} error={error} />
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
