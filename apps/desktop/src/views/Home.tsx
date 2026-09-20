import { useCallback, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { LibraryItem } from "../lib/types";
import { bars, tempo, when } from "../lib/format";

const DROP_GLYPH = (
  <svg className="glyph" viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <path d="M24 6v24m0 0-8-8m8 8 8-8" stroke="currentColor" strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round" />
    <path d="M8 32v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6" stroke="currentColor"
          strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

export function Home({
  onOpen, recent, busy, error,
}: {
  onOpen: (path: string) => void;
  recent: LibraryItem[];
  busy: boolean;
  error: string | null;
}) {
  const [hot, setHot] = useState(false);

  const browse = useCallback(async () => {
    const chosen = await open({
      multiple: false,
      filters: [{ name: "FL Studio project", extensions: ["flp"] }],
    });
    if (typeof chosen === "string") onOpen(chosen);
  }, [onOpen]);

  return (
    <div className="page-inner home fade">
      <div className="wordmark">Asterism</div>
      <div className="tagline">
        Turn loops into <em>records</em>.
      </div>

      <div
        className={`dropzone ${hot ? "hot" : ""} ${busy ? "busy" : ""}`}
        onClick={busy ? undefined : browse}
        data-dropzone="true"
        onDragOver={(e) => { e.preventDefault(); setHot(true); }}
        onDragLeave={() => setHot(false)}
        onDrop={() => setHot(false)}
      >
        {DROP_GLYPH}
        <div className="primary">
          {busy ? "Reading project…" : "Drop FL Studio project"}
        </div>
        <div className="secondary">.flp</div>
      </div>

      <button className="browse" onClick={browse} disabled={busy} type="button">
        Browse
      </button>

      {error && <div className="notice bad" style={{ maxWidth: 620 }}>{error}</div>}

      {recent.length > 0 && (
        <div className="recent">
          <div className="recent-head">
            <span className="eyebrow">Recent</span>
          </div>
          {recent.slice(0, 6).map((item) => (
            <button
              key={item.id}
              className={`recent-row ${item.exists ? "" : "gone"}`}
              onClick={() => item.exists && onOpen(item.path)}
              disabled={!item.exists}
              type="button"
            >
              <span className="name">{item.name}</span>
              <span className="meta">
                {item.tempo ? `${tempo(item.tempo)} BPM` : ""}
                {item.lengthBars ? ` · ${bars(item.lengthBars)} bars` : ""}
                {item.exists ? "" : " · moved"}
              </span>
              <span className="meta">{when(item.updatedAt)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
