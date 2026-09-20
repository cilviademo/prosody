import type { LibraryItem } from "../lib/types";
import { Empty } from "../components/Primitives";
import { bars, tempo, when } from "../lib/format";

const TONE: Record<string, string> = {
  Completed: "done", Warning: "warn",
};

export function Library({
  items, onOpen, onReveal,
}: {
  items: LibraryItem[];
  onOpen: (path: string) => void;
  onReveal: (dir: string) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="page-inner wide fade">
        <span className="eyebrow">Library</span>
        <Empty title="No projects yet"
               hint="Projects you open appear here with their tempo, key and status." />
      </div>
    );
  }

  return (
    <div className="page-inner wide fade">
      <span className="eyebrow">Library</span>
      <h2 style={{ marginTop: 10, fontWeight: 300, fontSize: 28 }}>
        {items.length} project{items.length === 1 ? "" : "s"}
      </h2>

      <div className="lib-head" style={{ marginTop: 26 }}>
        <span>Project</span><span>BPM</span><span>Key</span>
        <span>Genre</span><span>Status</span>
      </div>

      <div className="lib">
        {items.map((item) => (
          <button
            key={item.id}
            className="lib-row"
            type="button"
            onClick={() =>
              item.exists
                ? onOpen(item.path)
                : item.outDir && onReveal(item.outDir)
            }
          >
            <span>
              <span className="nm">{item.name}</span>
              <span className="sub">
                {bars(item.lengthBars)} bars · {when(item.updatedAt)}
                {item.exists ? "" : " · source moved"}
              </span>
            </span>
            <span className="c">{tempo(item.tempo)}</span>
            <span className="c">{item.key ?? "—"}</span>
            <span className="c">{item.genre ?? "—"}</span>
            <span>
              <span className={`pill ${TONE[item.status] ?? ""}`}>{item.status}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
