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
import { Notice } from "./components/Primitives";

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

  const stepRef = useRef(step);
  stepRef.current = step;

  const refreshLibrary = useCallback(() => {
    api.library().then(setLibrary).catch(() => undefined);
  }, []);

  // -- boot ---------------------------------------------------------------- //
  useEffect(() => {
    void (async () => {
      const status = await backendStatus().catch((e) => ({ ok: false, error: String(e) }));
      if (!status.ok) {
        setFatal(status.error ?? "The Asterism backend could not be reached.");
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
        <div className="titlebar">
          <span className="brand">Asterism</span>
        </div>
        <div className="page">
          <div className="page-inner">
            <h2 style={{ fontWeight: 300 }}>Asterism could not start</h2>
            <Notice tone="bad">{fatal}</Notice>
            <p className="dim" style={{ marginTop: 18, lineHeight: 1.6 }}>
              Asterism needs Python 3.10 or newer with its backend package
              available. Install Python, or set the{" "}
              <span className="mono">ASTERISM_PYTHON</span> environment variable to
              the interpreter you want it to use, then restart.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const flPath = settings.fl_executable ?? env?.flExecutable ?? null;

  return (
    <div className="shell">
      <div className="titlebar">
        <span className="brand">
          <b>✳</b> Asterism
        </span>
        <nav className="nav">
          {(["finish", "library", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "on" : ""}
              onClick={() => {
                setTab(t);
                if (t === "library") refreshLibrary();
              }}
              type="button"
            >
              {t}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        <button
          className={`fl-chip ${env?.canRender ? "on" : ""}`}
          onClick={() => setTab("settings")}
          type="button"
        >
          <span className="dot" />
          {env?.canRender ? "FL Studio connected" : "FL Studio not configured"}
        </button>
      </div>

      <div className="page">
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
              <div className="page-inner" style={{ paddingBottom: 0 }}>
                <Notice tone="bad">{error}</Notice>
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
