import type { Genre, LibraryItem } from "../lib/types";
import { Badge, Empty } from "../components/ui";
import { bars, tempo, when } from "../lib/format";

const COLUMNS = "1fr 76px 92px 96px 110px";

export function Library({
  items, genres, onOpen, onReveal,
}: {
  items: LibraryItem[];
  genres: Genre[];
  onOpen: (path: string) => void;
  onReveal: (dir: string) => void;
}) {
  // Library rows store the genre id; the picker's label is what people read.
  const label = new Map(genres.map((g) => [g.id, g.label]));
  if (items.length === 0) {
    return (
      <div className="view wide enter">
        <div className="label">Library</div>
        <Empty
          title="No projects yet"
          detail="Projects you open appear here with their tempo, key and status."
        />
      </div>
    );
  }

  return (
    <div className="view wide enter">
      <div className="label">Library</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>
        {items.length} project{items.length === 1 ? "" : "s"}
      </h1>

      <div style={{ marginTop: "var(--s8)" }}>
        <div className="data-head" style={{ gridTemplateColumns: COLUMNS }}>
          <span>Project</span><span>BPM</span><span>Key</span>
          <span>Style</span><span>Status</span>
        </div>

        {items.map((item) => (
          <button
            key={item.id}
            className="data-row"
            style={{ gridTemplateColumns: COLUMNS }}
            type="button"
            title={item.exists ? item.path : "Source has moved"}
            onClick={() =>
              item.exists ? onOpen(item.path) : item.outDir && onReveal(item.outDir)
            }
          >
            <span className="grow" style={{ minWidth: 0 }}>
              <span className="truncate" style={{ display: "block" }}>{item.name}</span>
              <span className="mono faint" style={{ fontSize: "var(--fs-micro)" }}>
                {bars(item.lengthBars)} bars · {when(item.updatedAt)}
                {item.exists ? "" : " · moved"}
              </span>
            </span>
            <span className="c">{tempo(item.tempo)}</span>
            <span className="c">{item.key ?? "—"}</span>
            <span className="c">{item.genre ? label.get(item.genre) ?? item.genre : "—"}</span>
            <span><Badge on={item.status === "Completed"}>{item.status}</Badge></span>
          </button>
        ))}
      </div>
    </div>
  );
}
