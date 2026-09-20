import type { Plan } from "../lib/types";
import { DRUM_ROLES } from "../lib/format";

/**
 * Arrangement preview.
 *
 * Section fill lightness encodes energy (0.04–0.20 white), so the shape of a
 * song is legible at a glance without a single colour. Section boundaries
 * continue down through the lanes as hairlines, the way an arranger grid does.
 */
export function Timeline({ plan }: { plan: Plan }) {
  const total = Math.max(plan.totalBars, 1);
  const boundaries = plan.sections.slice(1).map((s) => ((s.startBar - 1) / total) * 100);

  return (
    <div className="arranger">
      <div className="ruler" aria-hidden="true">
        {plan.sections.map((s) => (
          <span className="m" key={s.startBar} style={{ flex: s.bars, minWidth: 0 }}>
            {s.startBar}
          </span>
        ))}
      </div>

      <div className="sections">
        {plan.sections.map((s) => (
          <div
            key={s.startBar}
            className="sect"
            style={{
              flex: s.bars,
              minWidth: 0,
              // energy 0..1 → a restrained 0.04..0.20 white wash
              ["--fill" as string]: (0.04 + s.energy * 0.16).toFixed(3),
            }}
            title={`${s.label} · ${s.bars} bars · energy ${s.energy.toFixed(2)}${
              s.dropoutBars ? ` · ${s.dropoutBars}-bar dropout` : ""
            }`}
          >
            <span className="n">{s.label}</span>
            <span className="b">{s.bars}</span>
            {s.dropoutBars > 0 && (
              <span
                className="notch"
                style={{ width: `${(s.dropoutBars / s.bars) * 100}%` }}
                aria-hidden="true"
              />
            )}
          </div>
        ))}
      </div>

      <div className="lanes">
        {plan.lanes.map((lane) => (
          <div
            key={lane.role}
            className="lane"
            data-kind={DRUM_ROLES.has(lane.role) ? "drum" : "pitched"}
          >
            <span className="nm">{lane.label}</span>
            <span className="track">
              {boundaries.map((left, i) => (
                <span key={i} className="div" style={{ left: `${left}%` }} aria-hidden="true" />
              ))}
              {lane.blocks.map((b, i) => (
                <span
                  key={i}
                  className="blk"
                  style={{
                    left: `${((b.startBar - 1) / total) * 100}%`,
                    width: `${Math.max((b.bars / total) * 100, 0.3)}%`,
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
