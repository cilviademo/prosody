import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { Env, Settings as SettingsShape, SystemCheck } from "../lib/types";
import { api, shell } from "../lib/api";
import {
  Advanced, Button, KeyValues, Note, Section, Segmented,
} from "../components/ui";

export function SettingsView({
  settings, env, onChange,
}: {
  settings: SettingsShape;
  env: Env | null;
  onChange: (next: Partial<SettingsShape>) => void;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string; command?: string[] } | null>(null);
  const [check, setCheck] = useState<SystemCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [copied, setCopied] = useState(false);

  const flPath = settings.fl_executable ?? env?.flExecutable ?? null;

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
      const result = await api.testFl(flPath ?? undefined);
      setTestResult({
        ok: result.ok,
        text: result.ok ? `Connected · ${result.detail}` : result.detail,
        // The exact command, so a failure can be reproduced by hand.
        command: result.command,
      });
    } catch (e) {
      setTestResult({ ok: false, text: String(e) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="view enter">
      <div className="label">Settings</div>

      <div className="stack-8" style={{ marginTop: "var(--s7)" }}>
        {/* ------------------------------------------------- FL Studio -- */}
        <Section title="FL Studio">
          <div className="setting">
            <div className="lab">
              <div className="t">Application</div>
              <div className="d">Needed for audio and stems only.</div>
              <span className="path" data-empty={!flPath}>
                {flPath ?? "Not configured"}
              </span>
            </div>
            <div className="ctl">
              <Button onClick={pickFl} size="sm">Change</Button>
              <Button onClick={test} disabled={testing} size="sm">
                {testing ? "Testing" : "Test"}
              </Button>
            </div>
          </div>

          {testResult && (
            <div style={{ marginTop: "var(--s4)" }}>
              <Note strong={!testResult.ok}>{testResult.text}</Note>
              {testResult.command && testResult.command.length > 0 && (
                <div className="mono" style={{ marginTop: "var(--s3)", fontSize: 11, opacity: 0.8 }}>
                  {testResult.command.map((a) => (a.includes(" ") ? `"${a}"` : a)).join(" ")}
                </div>
              )}
            </div>
          )}

          <div className="setting">
            <div className="lab">
              <div className="t">Rendering</div>
              <div className="d">Let Prosody run FL Studio to render.</div>
            </div>
            <div className="ctl">
              <Segmented
                ariaLabel="Rendering"
                options={[{ value: false, label: "Off" }, { value: true, label: "On" }]}
                value={settings.render_enabled}
                onChange={(v) => onChange({ render_enabled: v })}
              />
            </div>
          </div>
        </Section>

        {/* ----------------------------------------------------- output -- */}
        <Section title="Output">
          <div className="setting">
            <div className="lab">
              <div className="t">Export folder</div>
              <div className="d">Where finished projects are written.</div>
              <span className="path">
                {settings.export_root ?? env?.exportRoot ?? "Default"}
              </span>
            </div>
            <div className="ctl">
              <Button onClick={pickFolder} size="sm">Change</Button>
              {env && (
                <Button variant="quiet" size="sm"
                        onClick={() => void shell.reveal(env.exportRoot)}>
                  Open
                </Button>
              )}
            </div>
          </div>

          {env?.exportRootCloud && !settings.cloud_export_acknowledged && (
            <Note heading={`This folder is synced by ${env.exportRootCloud}`}>
              Stems can be large, and a sync client locks files while it uploads
              them. Prosody retries a locked file and steps to the next version
              if it has to, but a local folder is recommended.
              <div className="row" style={{ marginTop: "var(--s4)" }}>
                <Button size="sm" onClick={() => onChange({ export_root: env.suggestedExportRoot })}>
                  Use {env.suggestedExportRoot}
                </Button>
                <Button size="sm" variant="quiet"
                        onClick={() => onChange({ cloud_export_acknowledged: true })}>
                  Keep it here
                </Button>
              </div>
            </Note>
          )}

          <div className="setting">
            <div className="lab">
              <div className="t">Audio format</div>
              <div className="d">Used for previews and renders.</div>
            </div>
            <div className="ctl">
              <Segmented
                ariaLabel="Audio format"
                options={[{ value: "wav", label: "WAV" }, { value: "mp3", label: "MP3" }]}
                value={settings.audio_format}
                onChange={(v) => onChange({ audio_format: v })}
              />
            </div>
          </div>

          <div className="setting">
            <div className="lab">
              <div className="t">WAV bit depth</div>
              <div className="d">Stems always render at the project sample rate.</div>
            </div>
            <div className="ctl">
              <Segmented
                ariaLabel="WAV bit depth"
                options={[16, 24, 32].map((d) => ({ value: d, label: `${d}` }))}
                value={settings.wav_bit_depth}
                onChange={(v) => onChange({ wav_bit_depth: v })}
              />
            </div>
          </div>
        </Section>

        {/* ------------------------------------------------ arrangement -- */}
        <Section title="Arrangement">
          <div className="setting">
            <div className="lab">
              <div className="t">Default creativity</div>
              <div className="d">
                Preserve never edits or generates notes — enforced in code.
              </div>
            </div>
            <div className="ctl">
              <Segmented
                ariaLabel="Default creativity"
                options={[
                  { value: 0, label: "Preserve" },
                  { value: 1, label: "Conservative" },
                  { value: 2, label: "Producer" },
                ]}
                value={settings.creativity_level}
                onChange={(v) => onChange({ creativity_level: v })}
              />
            </div>
          </div>

          <div className="setting">
            <div className="lab">
              <div className="t">Planner</div>
              <div className="d">
                Rules needs no account or network. AI only ranks plans the
                engine already made.
              </div>
            </div>
            <div className="ctl">
              <Segmented
                ariaLabel="Planner"
                options={[
                  { value: "rules", label: "Rules" },
                  { value: "claude", label: "Claude" },
                  { value: "openai", label: "OpenAI" },
                ]}
                value={settings.ai_provider}
                onChange={(v) => onChange({ ai_provider: v })}
              />
            </div>
          </div>

          {settings.ai_provider !== "rules" && (
            <Note heading="Not yet wired up">
              Set <span className="mono">ANTHROPIC_API_KEY</span> or{" "}
              <span className="mono">OPENAI_API_KEY</span> in your environment.
              Provider ranking is not implemented, so arrangement falls back to
              the deterministic planner — which is what produces plans today.
            </Note>
          )}
        </Section>
      </div>

      <Section
        title="System check"
        meta="checked now, not assumed"
      >
        <div className="row">
          <Button
            onClick={async () => {
              setChecking(true);
              setCopied(false);
              try {
                setCheck(await api.systemCheck());
              } finally {
                setChecking(false);
              }
            }}
            disabled={checking}
          >
            {checking ? "Checking…" : "Run system check"}
          </Button>
          {check && (
            <Button
              onClick={async () => {
                // The report has the user's profile path replaced with ~ and
                // never contains an API key.
                try {
                  await navigator.clipboard.writeText(check.report);
                  setCopied(true);
                } catch {
                  setCopied(false);
                }
              }}
            >
              {copied ? "Copied" : "Copy report"}
            </Button>
          )}
        </div>

        {check && (
          <>
            <Note>
              {check.counts.PASS} pass · {check.counts.WARNING} warning ·{" "}
              {check.counts.UNAVAILABLE} unavailable · {check.counts.FAIL} fail
              {check.ok
                ? " — nothing is broken."
                : " — something that should work does not."}
            </Note>
            <table className="check">
              <tbody>
                {check.rows.map((row) => (
                  <tr key={row.name} data-verdict={row.verdict}>
                    <td className="check-verdict">{row.verdict}</td>
                    <td className="check-name">{row.name}</td>
                    <td className="check-detail">{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Section>

      <Advanced title="Environment">
        {env && (
          <KeyValues
            rows={[
              ["Platform", env.platform],
              ["Python", env.python],
              ["PyFLP", `${env.pyflp}${env.compatShim ? " · compatibility shim active" : ""}`],
              ["FL Studio", <span className="mono" key="f">{env.flExecutable ?? env.flDiscovery}</span>],
              ...(env.flArchitecture ? ([["Architecture", env.flArchitecture]] as [string, React.ReactNode][]) : []),
              ["Rendering", env.canRender ? "available" : env.renderReason],
              ["Stems", env.stemStrategy ?? env.stemReason],
              ["Workspace", <span className="mono" key="w">{env.workspace}</span>],
              ["Library index", env.database],
              [
                "Build",
                <span className="mono" key="b">
                  {env.build.frozen
                    ? `${env.build.prosodyVersion ?? "?"} · ${(env.build.gitCommit ?? "").slice(0, 7)} · ${env.build.builtAt ?? ""}`
                    : "development"}
                </span>,
              ],
              // FL Studio encodes MP3 itself during a command-line render, so
              // nothing here calls ffmpeg. Saying "not found" without saying
              // "not needed" reads as a broken install on a fresh machine.
              [
                "ffmpeg",
                <span className="mono" key="g">
                  {env.ffmpeg ?? "not present — not required"}
                </span>,
              ],
            ]}
          />
        )}
      </Advanced>
    </div>
  );
}
