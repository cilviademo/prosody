import { useEffect, useState } from "react";
import type { Env, Genre, Plan, Project } from "../lib/types";
import { api } from "../lib/api";
import { Advanced, Check, Notice, Panel, Tile } from "../components/Primitives";
import { Timeline } from "../components/Timeline";
import { clock } from "../lib/format";

const STRUCTURES = [
  { id: "short", label: "Short", sub: "Streaming" },
  { id: "balanced", label: "Balanced", sub: "Default" },
  { id: "full", label: "Full Song", sub: "Extended" },
];

const LEVELS = [
  { id: 0, label: "Preserve Composition", sub: "Default · never edits notes" },
  { id: 1, label: "Conservative", sub: "May thin and shorten patterns" },
  { id: 2, label: "Producer Assist", sub: "May generate new material" },
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

  const stemsAvailable = Boolean(env?.stemStrategy);
  const renderAvailable = Boolean(env?.canRender);

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

  return (
    <div className="page-inner wide fade">
      <button className="btn ghost" onClick={onBack} type="button"
              style={{ marginBottom: 18, padding: "6px 12px" }}>
        ← {project.name}
      </button>

      {arranging && (
        <>
          <span className="eyebrow">Style</span>
          <div className="tiles">
            {genres.map((g) => (
              <Tile key={g.id} on={genre === g.id} label={g.label}
                    onClick={() => setGenre(g.id)} />
            ))}
          </div>

          <div className="section-gap">
            <span className="eyebrow">Structure</span>
            <div className="tiles">
              {STRUCTURES.map((s) => (
                <Tile key={s.id} on={structure === s.id} label={s.label} sub={s.sub}
                      onClick={() => setStructure(s.id)} />
              ))}
            </div>
          </div>

          <div className="section-gap">
            <span className="eyebrow">Creativity</span>
            <div className="tiles">
              {LEVELS.map((l) => (
                <Tile key={l.id} on={level === l.id} label={l.label} sub={l.sub}
                      onClick={() => setLevel(l.id)} />
              ))}
            </div>
            {level > 0 && (
              <Notice tone="warn">
                Levels above Preserve Composition are not implemented yet. The
                arrangement engine will still only reposition existing patterns —
                it will not edit or generate notes.
              </Notice>
            )}
          </div>

          <div className="section-gap">
            <div className="row-between">
              <span className="eyebrow">Arrangement</span>
              {plan && (
                <span className="faint mono">
                  {plan.totalBars} bars · {clock(plan.durationSeconds)} · {plan.sections.length} sections
                </span>
              )}
            </div>

            <Panel className="section-gap" >
              {planning && <div className="faint">Planning…</div>}
              {planError && <Notice tone="bad">{planError}</Notice>}
              {plan && !planError && <Timeline plan={plan} />}
              {plan && (
                <div className="gap-sm" style={{ marginTop: 22 }}>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => {
                      const next = variant === "A" ? "B" : variant === "B" ? "C" : "A";
                      setVariant(next);
                      if (next === "A") setSeed((s) => s + 1);
                    }}
                  >
                    Regenerate
                  </button>
                  <span className="faint" style={{ alignSelf: "center", fontSize: 12 }}>
                    Variant {variant} · seed {seed}
                  </span>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}

      <div className="section-gap">
        <span className="eyebrow">Export</span>
        <div className="checks">
          <Check on={choices.wav} onClick={() => toggle("wav")} label="WAV"
                 disabled={!renderAvailable}
                 why={renderAvailable ? undefined : "needs FL Studio"} />
          <Check on={choices.mp3} onClick={() => toggle("mp3")} label="MP3 preview"
                 disabled={!renderAvailable}
                 why={renderAvailable ? undefined : "needs FL Studio"} />
          <Check on={choices.midi} onClick={() => toggle("midi")} label="MIDI" />
          <Check on={choices.zip} onClick={() => toggle("zip")}
                 label="Portable FL project" />
        </div>

        <div style={{ marginTop: 20 }}>
          <span className="eyebrow">Stems</span>
          <div className="checks">
            <Check
              on={choices.stems}
              onClick={() => toggle("stems")}
              label="Mixer stems"
              disabled={!stemsAvailable}
              why={stemsAvailable ? `via ${env?.stemStrategy}` : "unavailable"}
            />
          </div>
          {!stemsAvailable && env && (
            <Notice>
              Stems are unavailable on this machine: {env.stemReason}. Everything
              else still exports.
            </Notice>
          )}
        </div>

        {!renderAvailable && env && (
          <Notice>
            Audio rendering is off: {env.renderReason}. Set your FL Studio path in
            Settings and enable rendering to produce WAV and MP3. MIDI, the
            portable project and the arranged .flp do not need it.
          </Notice>
        )}
      </div>

      <div style={{ marginTop: 38 }}>
        <button
          className="btn accent big"
          type="button"
          disabled={arranging && (planning || !plan)}
          onClick={() =>
            onBuild({ genre, structure, level, variant, seed, exports: choices })
          }
        >
          {arranging ? "Build Arrangement" : "Extract"}
        </button>
      </div>

      {plan && (
        <Advanced>
          <p>{plan.notes}</p>
          <p style={{ margin: "14px 0 8px" }}>
            Planner: {plan.planner} · deterministic for this seed.
          </p>
          <pre>
{plan.sections
  .map((s) =>
    `bar ${String(s.startBar).padStart(3)}  ${s.label.padEnd(10)} ${String(s.bars).padStart(2)}b  ` +
    `e=${s.energy.toFixed(2)}  drop=${s.dropoutBars}  ${s.roles.join(", ")}`)
  .join("\n")}
          </pre>
        </Advanced>
      )}
    </div>
  );
}
