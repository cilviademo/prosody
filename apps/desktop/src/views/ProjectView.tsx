import type { Project, RoleFlag } from "../lib/types";
import {
  Advanced, Back, Badge, Data, KeyValues, Note, Option, Readout, Section,
} from "../components/ui";
import { bars, clock, tempo } from "../lib/format";

const ROLE_GLYPH: Record<string, string> = { on: "●", maybe: "◐", off: "·" };

function roleState(role: RoleFlag): "on" | "maybe" | "off" {
  if (role.present) return "on";
  return role.likely ? "maybe" : "off";
}

export function ProjectView({
  project, onChoose, onBack,
}: {
  project: Project;
  onChoose: (mode: "extract" | "arrange" | "both") => void;
  onBack: () => void;
}) {
  const c = project.counts;
  const blocked = project.health.status === "BLOCKED";
  const missing = c.samplesMissing;

  return (
    <div className="view enter">
      <Back onClick={onBack}>Back</Back>

      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <h1 className="title truncate grow">{project.name}</h1>
        <Badge on={project.health.status === "READY"}>{project.health.label}</Badge>
      </div>

      <div style={{ marginTop: "var(--s5)" }}>
        <Readout
          items={[
            { value: tempo(project.tempo), caption: "BPM" },
            { value: project.key ?? "—",
              caption: project.keyConfidence < 0.7 ? "Key · approx" : "Key" },
            { value: bars(project.lengthBars), caption: "Bars" },
            { value: clock(project.durationSeconds), caption: "Length" },
            { value: `${project.timeSignature[0]}/${project.timeSignature[1]}`, caption: "Time" },
          ]}
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.35fr 1fr",
          gap: "var(--s8)",
          marginTop: "var(--s8)",
        }}
      >
        <Section title="Material">
          <div className="roles">
            {project.roles.map((role) => {
              const state = roleState(role);
              return (
                <div key={role.role} className="role" data-state={state}>
                  <span className="g" aria-hidden="true">{ROLE_GLYPH[state]}</span>
                  <span>{role.label}</span>
                  {state === "maybe" && <span className="tag">likely</span>}
                </div>
              );
            })}
          </div>
        </Section>

        <Section title="Contents">
          <div className="stats">
            <div className="stat"><span className="k">Patterns</span><span className="v">{c.patterns}</span></div>
            <div className="stat"><span className="k">Channels</span><span className="v">{c.channels}</span></div>
            <div className="stat"><span className="k">Plugins</span><span className="v">{c.plugins}</span></div>
            <div className="stat"><span className="k">Mixer tracks</span><span className="v">{c.mixerTracks}</span></div>
            <div className="stat"><span className="k">Notes</span><span className="v">{c.notes}</span></div>
            <div className="stat"><span className="k">Playlist clips</span><span className="v">{c.playlistClips}</span></div>
            {missing > 0 && (
              <div className="stat" data-flag="true">
                <span className="k">Missing samples</span><span className="v">{missing}</span>
              </div>
            )}
          </div>
        </Section>
      </div>

      {(missing > 0 || blocked) && (
        <div className="stack-4" style={{ marginTop: "var(--s7)" }}>
          {missing > 0 && (
            <Note heading="Samples">
              {missing} sample{missing === 1 ? "" : "s"} could not be found here.
              Arranging still works — the new project keeps the same references —
              but rendered audio will be incomplete until they are relinked in
              FL Studio.
            </Note>
          )}
          {blocked && (
            <Note strong heading="Unreadable">
              This project could not be read well enough to work with. Diagnostics
              below list what failed.
            </Note>
          )}
        </div>
      )}

      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Next">
          <div className="option-rows">
            <Option
              title="Extract"
              detail="Audio, MIDI and a portable copy of the project as it stands."
              disabled={blocked}
              onClick={() => onChoose("extract")}
            />
            <Option
              title="Arrange"
              detail={
                project.canArrange
                  ? "Build a full song structure from the patterns already here."
                  : "Needs at least one pattern with notes."
              }
              disabled={blocked || !project.canArrange}
              onClick={() => onChoose("arrange")}
            />
            <Option
              title="Extract and arrange"
              detail="The arranged project, plus every export."
              emphasis
              disabled={blocked || !project.canArrange}
              onClick={() => onChoose("both")}
            />
          </div>
        </Section>
      </div>

      <Advanced title="Diagnostics">
        <KeyValues
          rows={[
            ["FL Studio version", project.flVersion ?? "not recorded"],
            ["Detected state", project.state],
            ["Source", <span className="mono" key="p">{project.path}</span>],
            ["SHA-256", <span className="mono" key="h">{project.hash}</span>],
          ]}
        />

        {project.uncertain.length > 0 && (
          <>
            <p className="copy" style={{ margin: "var(--s5) 0 0" }}>
              Channels below the 0.70 confidence threshold. They are marked
              “likely” rather than counted as fact.
            </p>
            <Data>
              {project.uncertain
                .map((u) =>
                  `${(u.name ?? `channel ${u.channel}`).padEnd(22)}` +
                  `${u.role.padEnd(9)}${u.confidence.toFixed(2)}  ${u.sources.join(", ")}`)
                .join("\n")}
            </Data>
          </>
        )}

        <p className="copy" style={{ margin: "var(--s5) 0 0" }}>Pattern roles</p>
        <Data>
          {project.patternRoles
            .map((p) =>
              `${String(p.pattern).padStart(3)}  ${p.name.padEnd(22)}` +
              `${p.role.padEnd(9)}${p.notes} notes`)
            .join("\n") || "none"}
        </Data>

        <p className="copy" style={{ margin: "var(--s5) 0 0" }}>Health checks</p>
        <Data>
          {project.health.checks
            .map((h) =>
              `${h.ok === true ? "ok  " : h.ok === false ? "fail" : "?   "} ` +
              `${h.name.padEnd(22)}${h.detail}`)
            .join("\n")}
        </Data>

        {project.warnings.length > 0 && (
          <>
            <p className="copy" style={{ margin: "var(--s5) 0 0" }}>Parser notes</p>
            <Data>
              {project.warnings
                .map((w) => `${w.severity.padEnd(8)}${w.code}: ${w.message}`)
                .join("\n")}
            </Data>
          </>
        )}
      </Advanced>
    </div>
  );
}
