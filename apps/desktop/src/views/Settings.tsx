import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { Env, Settings as SettingsShape } from "../lib/types";
import { api, shell } from "../lib/api";
import { Advanced, Notice } from "../components/Primitives";

export function SettingsView({
  settings, env, onChange,
}: {
  settings: SettingsShape;
  env: Env | null;
  onChange: (next: Partial<SettingsShape>) => void;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const detected = settings.fl_executable ?? env?.flExecutable ?? null;

  const pickFl = async () => {
    const chosen = await open({
      multiple: false,
      filters: [{ name: "FL Studio", extensions: ["exe"] }],
    });
    if (typeof chosen === "string") onChange({ fl_executable: chosen });
  };

  const pickFolder = async () => {
    const chosen = await open({ directory: true, multiple: false });
    if (typeof chosen === "string") onChange({ export_root: chosen });
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testFl(detected ?? undefined);
      setTestResult(
        result.ok
          ? `FL Studio detected ✓  ${result.path}`
          : `FL Studio not configured — ${result.detail}`,
      );
    } catch (e) {
      setTestResult(String(e));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="page-inner fade">
      <span className="eyebrow">Settings</span>

      <div style={{ marginTop: 24 }}>
        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">FL Studio</div>
              <div className="d">
                Needed to render audio and stems. Everything else works without it.
              </div>
            </div>
            <div className="gap-sm">
              <button className="btn" onClick={pickFl} type="button">Change</button>
              <button className="btn" onClick={test} disabled={testing} type="button">
                {testing ? "Testing…" : "Test Connection"}
              </button>
            </div>
          </div>
          <div className="val" style={{ marginTop: 12 }}>
            {detected ?? "not configured"}
          </div>
          {testResult && (
            <Notice tone={testResult.includes("✓") ? "" : "warn"}>{testResult}</Notice>
          )}
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">Rendering</div>
              <div className="d">
                Let Asterism run FL Studio to produce WAV, MP3 and stems.
              </div>
            </div>
            <div className="seg">
              {[false, true].map((on) => (
                <button
                  key={String(on)}
                  className={settings.render_enabled === on ? "on" : ""}
                  onClick={() => onChange({ render_enabled: on })}
                  type="button"
                >
                  {on ? "On" : "Off"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">Export folder</div>
              <div className="d">Where finished projects are written.</div>
            </div>
            <div className="gap-sm">
              <button className="btn" onClick={pickFolder} type="button">Change</button>
              {env && (
                <button className="btn ghost" type="button"
                        onClick={() => void shell.reveal(env.exportRoot)}>
                  Open
                </button>
              )}
            </div>
          </div>
          <div className="val" style={{ marginTop: 12 }}>
            {settings.export_root ?? env?.exportRoot ?? "default"}
          </div>
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">Default audio format</div>
              <div className="d">Used for previews and renders.</div>
            </div>
            <div className="seg">
              {["wav", "mp3"].map((f) => (
                <button key={f} className={settings.audio_format === f ? "on" : ""}
                        onClick={() => onChange({ audio_format: f })} type="button">
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">WAV bit depth</div>
              <div className="d">Stems are always WAV at the project sample rate.</div>
            </div>
            <div className="seg">
              {[16, 24, 32].map((d) => (
                <button key={d} className={settings.wav_bit_depth === d ? "on" : ""}
                        onClick={() => onChange({ wav_bit_depth: d })} type="button">
                  {d}-bit
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">Default creativity</div>
              <div className="d">
                Preserve Composition never edits or generates notes. It is enforced
                in code, not by instructions to a model.
              </div>
            </div>
            <div className="seg">
              {[
                { v: 0, l: "Preserve" },
                { v: 1, l: "Conservative" },
                { v: 2, l: "Producer" },
              ].map((o) => (
                <button key={o.v} className={settings.creativity_level === o.v ? "on" : ""}
                        onClick={() => onChange({ creativity_level: o.v })} type="button">
                  {o.l}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="setting">
          <div className="row">
            <div className="label">
              <div className="t">Arrangement planner</div>
              <div className="d">
                Rules Only needs no account and no network. AI providers are
                optional and are only asked to rank plans the engine already made.
              </div>
            </div>
            <div className="seg">
              {[
                { v: "rules", l: "Rules Only" },
                { v: "claude", l: "Claude" },
                { v: "openai", l: "OpenAI" },
              ].map((o) => (
                <button key={o.v} className={settings.ai_provider === o.v ? "on" : ""}
                        onClick={() => onChange({ ai_provider: o.v })} type="button">
                  {o.l}
                </button>
              ))}
            </div>
          </div>
          {settings.ai_provider !== "rules" && (
            <Notice>
              Set <span className="mono">ANTHROPIC_API_KEY</span> or{" "}
              <span className="mono">OPENAI_API_KEY</span> in your environment.
              Provider ranking is not wired up yet, so arrangement falls back to
              the deterministic planner — which is what produces the plans today.
            </Notice>
          )}
        </div>
      </div>

      <Advanced title="Environment">
        {env && (
          <dl className="kv">
            <dt>Platform</dt><dd>{env.platform}</dd>
            <dt>Python</dt><dd>{env.python}</dd>
            <dt>PyFLP</dt>
            <dd>{env.pyflp}{env.compatShim ? " (compatibility shim active)" : ""}</dd>
            <dt>FL Studio</dt><dd className="mono">{env.flExecutable ?? env.flDiscovery}</dd>
            <dt>Rendering</dt><dd>{env.canRender ? "available" : env.renderReason}</dd>
            <dt>Stems</dt><dd>{env.stemStrategy ?? env.stemReason}</dd>
            <dt>Workspace</dt><dd className="mono">{env.workspace}</dd>
            <dt>ffmpeg</dt><dd className="mono">{env.ffmpeg ?? "not found"}</dd>
          </dl>
        )}
      </Advanced>
    </div>
  );
}
