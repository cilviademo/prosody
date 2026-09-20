import type { BuildOutcome, ProgressEvent, Stage } from "../lib/types";
import { Advanced, Notice, Panel } from "../components/Primitives";
import { Player } from "../components/Player";
import { api, shell } from "../lib/api";
import { bytes } from "../lib/format";

const ICON: Record<string, string> = {
  pending: "·", running: "◌", ok: "✓", warning: "!", failed: "✕", skipped: "–",
};

export function Progress({ events }: { events: ProgressEvent[] }) {
  // Collapse to the latest status per stage, preserving first-seen order.
  const order: string[] = [];
  const latest = new Map<string, ProgressEvent>();
  for (const e of events) {
    if (!latest.has(e.stage)) order.push(e.stage);
    latest.set(e.stage, e);
  }
  const done = order.filter((s) => latest.get(s)!.status !== "running").length;
  const pct = order.length ? (done / order.length) * 100 : 0;

  return (
    <div className="page-inner fade">
      <span className="eyebrow">Building</span>
      <h2 style={{ marginTop: 10, fontWeight: 300, fontSize: 28 }}>
        Working on your project
      </h2>

      <Panel style={{ marginTop: 26 }}>
        <div className="stages">
          {order.map((name) => {
            const e = latest.get(name)!;
            return (
              <div key={name} className={`stage ${e.status}`}>
                <span className="ico">
                  {e.status === "running"
                    ? <span className="spin">◌</span>
                    : ICON[e.status] ?? "·"}
                </span>
                <span className="nm">{name}</span>
                <span className="dt">{e.detail}</span>
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export function Result({
  outcome, flExecutable, onDone, onAgain,
}: {
  outcome: BuildOutcome;
  flExecutable: string | null;
  onDone: () => void;
  onAgain: () => void;
}) {
  const native = outcome.tier === "native";
  const preview = outcome.previewWav ?? outcome.previewMp3;

  const title = native
    ? "Your arranged project is ready"
    : outcome.tier === "pack"
      ? "Arrangement Pack created"
      : "Nothing could be produced";

  return (
    <div className="page-inner fade">
      <div className={`result-banner ${native ? "native" : ""}`}>
        <div className="t">{title}</div>
        <div className="d">{outcome.message}</div>
        {!outcome.sourceUnchanged && (
          <div className="d" style={{ color: "var(--bad)" }}>
            Warning: the original file's hash changed during this build. Please
            report this.
          </div>
        )}
      </div>

      <div className="actions">
        {native && outcome.flpPath && (
          <button
            className="btn accent"
            type="button"
            onClick={() => void shell.openInFl(outcome.flpPath!, flExecutable)}
          >
            Open in FL Studio
          </button>
        )}
        <button className="btn" type="button"
                onClick={() => void shell.reveal(outcome.outDir)}>
          Open output folder
        </button>
        <button className="btn ghost" type="button" onClick={onAgain}>
          Build another
        </button>
        <button className="btn ghost" type="button" onClick={onDone}>
          Done
        </button>
      </div>

      {preview && (
        <div style={{ marginTop: 26 }}>
          <span className="eyebrow">Preview</span>
          <Player path={preview} />
        </div>
      )}

      <div className="section-gap">
        <span className="eyebrow">Steps</span>
        <Panel style={{ marginTop: 12 }}>
          <div className="stages">
            {outcome.stages.map((s: Stage) => (
              <div key={s.name} className={`stage ${s.status}`}>
                <span className="ico">{ICON[s.status] ?? "·"}</span>
                <span className="nm">{s.name}</span>
                <span className="dt">{s.detail}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {outcome.artifacts.length > 0 && (
        <div className="section-gap">
          <span className="eyebrow">Files</span>
          <div className="files">
            {outcome.artifacts.map((a) => (
              <button key={a.path} className="file" type="button"
                      onClick={() => void shell.reveal(a.path)}>
                <span className="kind">{a.kind}</span>
                <span className="nm">{a.label}</span>
                <span className="sz">{bytes(a.bytes)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!native && outcome.tier === "pack" && (
        <Notice>
          An Arrangement Pack contains everything except an editable FL project:
          the arrangement plan, per-role MIDI, and any audio that was rendered.
          You can rebuild the arrangement in FL from the plan and the MIDI.
        </Notice>
      )}

      <Advanced>
        <dl className="kv">
          <dt>Output tier</dt><dd>{outcome.tier}</dd>
          <dt>Output folder</dt><dd className="mono">{outcome.outDir}</dd>
          <dt>Project id</dt><dd className="mono">{outcome.projectId}</dd>
          <dt>Source verified unchanged</dt>
          <dd>{outcome.sourceUnchanged ? "yes" : "NO"}</dd>
        </dl>
      </Advanced>
    </div>
  );
}

export { api };
