import type { Project } from "../lib/types";
import { Advanced, Health, Notice, Panel } from "../components/Primitives";
import { bars, clock, tempo } from "../lib/format";

export function ProjectView({
  project, onChoose, onBack,
}: {
  project: Project;
  onChoose: (mode: "extract" | "arrange" | "both") => void;
  onBack: () => void;
}) {
  const c = project.counts;
  const blocked = project.health.status === "BLOCKED";

  return (
    <div className="page-inner fade">
      <button className="btn ghost" onClick={onBack} type="button"
              style={{ marginBottom: 18, padding: "6px 12px" }}>
        ← Back
      </button>

      <div className="project-head">
        <div className="titles">
          <h1>{project.name}</h1>
          <div className="facts">
            <span className="fact">
              <span className="v">{tempo(project.tempo)}</span>
              <span className="k">BPM</span>
            </span>
            {project.key && (
              <span className="fact">
                <span className="v">{project.key}</span>
                <span className="k">Key{project.keyConfidence < 0.7 ? " ·  approx" : ""}</span>
              </span>
            )}
            <span className="fact">
              <span className="v">{bars(project.lengthBars)}</span>
              <span className="k">Bars</span>
            </span>
            <span className="fact">
              <span className="v">{clock(project.durationSeconds)}</span>
              <span className="k">Length</span>
            </span>
            <span className="fact">
              <span className="v">
                {project.timeSignature[0]}/{project.timeSignature[1]}
              </span>
              <span className="k">Time</span>
            </span>
          </div>
        </div>
        <Health status={project.health.status} label={project.health.label} />
      </div>

      <div className="grid-2">
        <Panel>
          <span className="eyebrow">Project</span>
          <div className="rolelist" style={{ marginTop: 14 }}>
            {project.roles.map((r) => (
              <div
                key={r.role}
                className={`role ${r.present ? "" : r.likely ? "maybe" : "off"}`}
                title={
                  r.likely
                    ? "Detected, but below the confidence threshold. It is still used when arranging."
                    : undefined
                }
              >
                <span className="tick">{r.present ? "✓" : r.likely ? "~" : "·"}</span>
                <span>{r.label}</span>
                {r.likely && <span className="hint">likely</span>}
              </div>
            ))}
          </div>
        </Panel>

        <Panel>
          <span className="eyebrow">Contents</span>
          <div className="statlist" style={{ marginTop: 14 }}>
            <div className="stat"><span className="k">Patterns</span><span className="v">{c.patterns}</span></div>
            <div className="stat"><span className="k">Channels</span><span className="v">{c.channels}</span></div>
            <div className="stat"><span className="k">Plugins</span><span className="v">{c.plugins}</span></div>
            <div className="stat"><span className="k">Mixer tracks</span><span className="v">{c.mixerTracks}</span></div>
            <div className="stat"><span className="k">Notes</span><span className="v">{c.notes}</span></div>
            <div className="stat"><span className="k">Playlist clips</span><span className="v">{c.playlistClips}</span></div>
            {c.samplesMissing > 0 && (
              <div className="stat">
                <span className="k">Missing samples</span>
                <span className="v" style={{ color: "var(--warn)" }}>{c.samplesMissing}</span>
              </div>
            )}
          </div>
        </Panel>
      </div>

      {c.samplesMissing > 0 && (
        <Notice tone="warn">
          {c.samplesMissing} sample{c.samplesMissing === 1 ? "" : "s"} referenced by
          this project could not be found on this machine. Arranging still works —
          the derivative keeps the same references — but rendering audio will be
          incomplete until the samples are relinked in FL Studio.
        </Notice>
      )}

      {blocked && (
        <Notice tone="bad">
          This project could not be read well enough to work with. See Diagnostics
          below for what failed.
        </Notice>
      )}

      <div className="section-gap">
        <span className="eyebrow">What do you want to do?</span>
        <div className="choices">
          <button className="choice" onClick={() => onChoose("extract")}
                  disabled={blocked} type="button">
            <div className="t">Extract</div>
            <div className="d">Audio, MIDI and a portable copy of the project as it is.</div>
          </button>
          <button className="choice" onClick={() => onChoose("arrange")}
                  disabled={blocked || !project.canArrange} type="button">
            <div className="t">Arrange</div>
            <div className="d">
              {project.canArrange
                ? "Build a full song structure from the patterns you already have."
                : "Needs patterns with notes."}
            </div>
          </button>
          <button className="choice primary" onClick={() => onChoose("both")}
                  disabled={blocked || !project.canArrange} type="button">
            <div className="t">Extract + Arrange</div>
            <div className="d">The arranged project, plus every export.</div>
          </button>
        </div>
      </div>

      <Advanced title="Diagnostics">
        <dl className="kv">
          <dt>FL Studio version</dt><dd>{project.flVersion ?? "not recorded"}</dd>
          <dt>Detected state</dt><dd>{project.state}</dd>
          <dt>SHA-256</dt><dd className="mono">{project.hash}</dd>
          <dt>Source path</dt><dd className="mono">{project.path}</dd>
        </dl>

        {project.uncertain.length > 0 && (
          <>
            <p style={{ margin: "18px 0 8px" }}>
              Channels the classifier is unsure about. These are excluded from
              arrangement decisions until confidence passes 0.70.
            </p>
            <pre>
{project.uncertain
  .map((u) => `${(u.name ?? `channel ${u.channel}`).padEnd(22)} ${u.role.padEnd(9)} ${u.confidence.toFixed(2)}  ${u.sources.join(", ")}`)
  .join("\n")}
            </pre>
          </>
        )}

        <p style={{ margin: "18px 0 8px" }}>Pattern roles</p>
        <pre>
{project.patternRoles
  .map((p) => `${String(p.pattern).padStart(3)}  ${p.name.padEnd(22)} ${p.role.padEnd(9)} ${p.notes} notes`)
  .join("\n") || "none"}
        </pre>

        <p style={{ margin: "18px 0 8px" }}>Health checks</p>
        <pre>
{project.health.checks
  .map((h) => `${h.ok === true ? "ok  " : h.ok === false ? "FAIL" : "?   "} ${h.name.padEnd(22)} ${h.detail}`)
  .join("\n")}
        </pre>

        {project.warnings.length > 0 && (
          <>
            <p style={{ margin: "18px 0 8px" }}>Parser notes</p>
            <pre>
{project.warnings.map((w) => `${w.severity.padEnd(8)} ${w.code}: ${w.message}`).join("\n")}
            </pre>
          </>
        )}
      </Advanced>
    </div>
  );
}
