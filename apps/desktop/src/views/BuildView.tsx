import type { BuildOutcome, ProgressEvent, Stage } from "../lib/types";
import {
  Advanced, Button, KeyValues, Note, Section,
} from "../components/ui";
import { Player } from "../components/Player";
import { shell } from "../lib/api";
import { bytes } from "../lib/format";

const GLYPH: Record<string, string> = {
  pending: "·", running: "◌", ok: "●", warning: "◐", failed: "✕", skipped: "–",
};

function StageRows({ stages }: { stages: { name: string; status: string; detail: string }[] }) {
  return (
    <div className="stages">
      {stages.map((s) => (
        <div key={s.name} className="stage" data-status={s.status}>
          <span className="g" aria-hidden="true">
            {s.status === "running"
              ? <span className="spin">◌</span>
              : GLYPH[s.status] ?? "·"}
          </span>
          <span className="nm">{s.name}</span>
          <span className="dt">{s.detail}</span>
        </div>
      ))}
    </div>
  );
}

export function Progress({ events }: { events: ProgressEvent[] }) {
  // Latest status per stage, in the order they first appeared.
  const order: string[] = [];
  const latest = new Map<string, ProgressEvent>();
  for (const e of events) {
    if (!latest.has(e.stage)) order.push(e.stage);
    latest.set(e.stage, e);
  }
  const done = order.filter((s) => latest.get(s)!.status !== "running").length;
  const pct = order.length ? (done / order.length) * 100 : 0;

  return (
    <div className="view enter">
      <div className="label">Building</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>
        Working on your project
      </h1>

      <div style={{ marginTop: "var(--s8)" }}>
        <StageRows
          stages={order.map((name) => {
            const e = latest.get(name)!;
            return { name: e.stage, status: e.status, detail: e.detail };
          })}
        />
      </div>

      <div className="meter" style={{ marginTop: "var(--s7)" }}>
        <i style={{ width: `${pct}%` }} />
      </div>
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

  const headline = native
    ? "Your arranged project is ready"
    : outcome.tier === "pack"
      ? "Arrangement pack is ready"
      : "Nothing could be produced";

  return (
    <div className="view enter">
      <div className="label">{native ? "Complete" : "Complete with fallback"}</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>{headline}</h1>
      <p className="copy" style={{ marginTop: "var(--s3)" }}>{outcome.message}</p>

      {!outcome.sourceUnchanged && (
        <div style={{ marginTop: "var(--s5)" }}>
          <Note strong heading="Check this">
            The original file's hash changed during this build. That should be
            impossible — please report it before using the output.
          </Note>
        </div>
      )}

      <div className="row wrap" style={{ marginTop: "var(--s7)" }}>
        {native && outcome.flpPath && (
          <Button variant="primary"
                  onClick={() => void shell.openInFl(outcome.flpPath!, flExecutable)}>
            Open in FL Studio
          </Button>
        )}
        <Button onClick={() => void shell.reveal(outcome.outDir)}>
          Show files
        </Button>
        <Button variant="quiet" onClick={onAgain}>Build another</Button>
        <Button variant="quiet" onClick={onDone}>Done</Button>
      </div>

      {preview && (
        <div style={{ marginTop: "var(--s8)" }}>
          <Section title="Preview">
            <Player path={preview} />
          </Section>
        </div>
      )}

      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Steps">
          <StageRows stages={outcome.stages as Stage[]} />
        </Section>
      </div>

      {outcome.artifacts.length > 0 && (
        <div style={{ marginTop: "var(--s8)" }}>
          <Section title="Files" meta={`${outcome.artifacts.length}`}>
            <div className="list">
              {outcome.artifacts.map((a) => (
                <button key={a.path} className="file" type="button"
                        title={a.path}
                        onClick={() => void shell.reveal(a.path)}>
                  <span className="kind">{a.kind}</span>
                  <span className="nm truncate">{a.label}</span>
                  <span className="sz">{bytes(a.bytes)}</span>
                </button>
              ))}
            </div>
          </Section>
        </div>
      )}

      {!native && outcome.tier === "pack" && (
        <div style={{ marginTop: "var(--s7)" }}>
          <Note heading="About this pack">
            An arrangement pack holds everything except an editable FL project:
            the plan, per-role MIDI, and any audio that rendered. The
            arrangement can be rebuilt in FL from those.
          </Note>
        </div>
      )}

      <Advanced>
        <KeyValues
          rows={[
            ["Output tier", outcome.tier],
            ["Folder", <span className="mono" key="d">{outcome.outDir}</span>],
            ["Project id", <span className="mono" key="i">{outcome.projectId}</span>],
            ["Source verified unchanged", outcome.sourceUnchanged ? "yes" : "NO"],
          ]}
        />
      </Advanced>
    </div>
  );
}
