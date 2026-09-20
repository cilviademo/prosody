import { useEffect, useState } from "react";
import type { Env, Genre, Plan, Project } from "../lib/types";
import { api } from "../lib/api";
import {
  Advanced, Back, Button, Data, Note, Section, Segmented, Toggle,
} from "../components/ui";
import { Timeline } from "../components/Timeline";
import { clock } from "../lib/format";

const STRUCTURES = [
  { value: "short", label: "Short", caption: "Streaming" },
  { value: "balanced", label: "Balanced", caption: "Default" },
  { value: "full", label: "Full", caption: "Extended" },
];

const LEVELS = [
  { value: 0, label: "Preserve", caption: "Never edits notes" },
  { value: 1, label: "Conservative", caption: "Thins patterns" },
  { value: 2, label: "Producer", caption: "Generates material" },
];

export interface ExportChoices {
  wav: boolean; mp3: boolean; midi: boolean; zip: boolean; stems: boolean;
}

export function ArrangeView({
  project, genres, env, mode, onBuild, onBack,
}: {
  project: Project;
  genres: Genre[];
  env: Env | null;
  mode: "extract" | "arrange" | "both";
  onBuild: (opts: {
    genre: string; structure: string; level: number; variant: string;
    seed: number; exports: ExportChoices;
  }) => void;
  onBack: () => void;
}) {
  const arranging = mode !== "extract";
  const [genre, setGenre] = useState(genres[0]?.id ?? "hiphop");
  const [structure, setStructure] = useState("balanced");
  const [level, setLevel] = useState(0);
  const [seed, setSeed] = useState(1234);
  const [variant, setVariant] = useState("A");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const canRender = Boolean(env?.canRender);
  const canStem = Boolean(env?.stemStrategy);

  const [choices, setChoices] = useState<ExportChoices>({
    wav: true, mp3: true, midi: true, zip: true, stems: false,
  });

  useEffect(() => {
    if (!arranging) return;
    let cancelled = false;
    setPlanning(true);
    setPlanError(null);
    api
      .plan({ path: project.path, genre, structure, level, variant, seed })
      .then((p) => !cancelled && setPlan(p))
      .catch((e) => !cancelled && setPlanError(String(e.message ?? e)))
      .finally(() => !cancelled && setPlanning(false));
    return () => { cancelled = true; };
  }, [arranging, project.path, genre, structure, level, variant, seed]);

  const toggle = (key: keyof ExportChoices) =>
    setChoices((c) => ({ ...c, [key]: !c[key] }));

  const regenerate = () => {
    const next = variant === "A" ? "B" : variant === "B" ? "C" : "A";
    setVariant(next);
    if (next === "A") setSeed((s) => s + 1);
  };

  return (
    <div className="view wide enter">
      <Back onClick={onBack}>{project.name}</Back>

      {arranging && (
        <div className="stack-8">
          <Section title="Style">
            <Segmented
              ariaLabel="Style"
              block
              options={genres.map((g) => ({ value: g.id, label: g.label }))}
              value={genre}
              onChange={setGenre}
            />
          </Section>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--s8)" }}>
            <Section title="Structure">
              <Segmented ariaLabel="Structure" block tall
                         options={STRUCTURES} value={structure} onChange={setStructure} />
            </Section>
            <Section title="Creativity">
              <Segmented ariaLabel="Creativity" block tall
                         options={LEVELS} value={level} onChange={setLevel} />
            </Section>
          </div>

          {level > 0 && (
            <Note heading="Not yet available">
              Levels above Preserve are not implemented. The engine still only
              repositions existing patterns — it will not edit or generate notes.
            </Note>
          )}

          <Section
            title="Arrangement"
            meta={plan
              ? `${plan.totalBars} bars · ${clock(plan.durationSeconds)} · ${plan.sections.length} sections`
              : undefined}
          >
            {planError ? (
              <Note strong heading="Could not plan">{planError}</Note>
            ) : plan ? (
              <>
                <Timeline plan={plan} />
                <div className="arranger-actions row" style={{ marginTop: "var(--s4)" }}>
                  <Button onClick={regenerate} size="sm">Regenerate</Button>
                  <span className="mono faint">Variant {variant} · seed {seed}</span>
                </div>
              </>
            ) : (
              <div className="empty"><div className="d">{planning ? "Planning" : ""}</div></div>
            )}
          </Section>
        </div>
      )}

      <div style={{ marginTop: arranging ? "var(--s8)" : 0 }}>
        <Section title="Export">
          <div className="toggle-rows">
            <Toggle on={choices.wav} onChange={() => toggle("wav")} label="WAV"
                    disabled={!canRender} why={canRender ? undefined : "needs FL Studio"} />
            <Toggle on={choices.mp3} onChange={() => toggle("mp3")} label="MP3 preview"
                    disabled={!canRender} why={canRender ? undefined : "needs FL Studio"} />
            <Toggle on={choices.midi} onChange={() => toggle("midi")} label="MIDI per role" />
            <Toggle on={choices.zip} onChange={() => toggle("zip")} label="Portable project" />
            <Toggle on={choices.stems} onChange={() => toggle("stems")} label="Mixer stems"
                    disabled={!canStem}
                    why={canStem ? env?.stemStrategy ?? undefined : "unavailable"} />
          </div>

          {(!canRender || !canStem) && (
            <div className="stack-4" style={{ marginTop: "var(--s5)" }}>
              {!canRender && (
                <Note heading="Audio is off">
                  Set your FL Studio path in Settings and turn rendering on to
                  produce WAV and MP3. The arranged project, MIDI and the
                  portable package do not need it.
                </Note>
              )}
              {!canStem && canRender && (
                <Note heading="Stems unavailable">{env?.stemReason}</Note>
              )}
            </div>
          )}
        </Section>
      </div>

      <div style={{ marginTop: "var(--s8)" }}>
        <Button
          variant="primary"
          size="lg"
          disabled={arranging && (planning || !plan)}
          onClick={() => onBuild({ genre, structure, level, variant, seed, exports: choices })}
        >
          {arranging ? "Build arrangement" : "Extract"}
        </Button>
      </div>

      {plan && (
        <Advanced>
          <p className="copy">{plan.notes}</p>
          <p className="copy" style={{ marginTop: "var(--s3)" }}>
            Planner: {plan.planner}. Deterministic for this seed.
          </p>
          <Data>
            {plan.sections
              .map((s) =>
                `bar ${String(s.startBar).padStart(3)}  ${s.label.padEnd(11)}` +
                `${String(s.bars).padStart(2)}b  e=${s.energy.toFixed(2)}  ` +
                `drop=${s.dropoutBars}  ${s.roles.join(", ")}`)
              .join("\n")}
          </Data>
        </Advanced>
      )}
    </div>
  );
}
