import type { Plan } from "../lib/types";
import { DRUM_ROLES } from "../lib/format";

/** Visual arrangement preview: section blocks plus one lane per role. */
export function Timeline({ plan }: { plan: Plan }) {
  const total = Math.max(plan.totalBars, 1);

  return (
    <div className="timeline">
      <div className="ruler">
        {plan.sections.map((s) => (
          <span key={s.startBar} style={{ flex: s.bars, minWidth: 0 }}>
            {s.startBar}
          </span>
        ))}
      </div>

      <div className="sections">
        {plan.sections.map((s) => (
          <div
            key={s.startBar}
            className="sect"
            style={{ flex: s.bars, minWidth: 0 }}
            title={`${s.label} · ${s.bars} bars · energy ${s.energy.toFixed(2)}${
              s.dropoutBars ? ` · ${s.dropoutBars} bar dropout` : ""
            }`}
          >
            <span
              className="fill"
              style={{ opacity: 0.08 + s.energy * 0.26 }}
            />
            <span className="n">{s.label}</span>
            <span className="b">{s.bars}</span>
          </div>
        ))}
      </div>

      <div className="lanes">
        {plan.lanes.map((lane) => (
          <div
            key={lane.role}
            className={`lane ${DRUM_ROLES.has(lane.role) ? "drum" : ""}`}
          >
            <span className="label">{lane.label}</span>
            <span className="track">
              {lane.blocks.map((b, i) => (
                <span
                  key={i}
                  className="blk"
                  style={{
                    left: `${((b.startBar - 1) / total) * 100}%`,
                    width: `${Math.max((b.bars / total) * 100, 0.35)}%`,
                  }}
                />
              ))}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
