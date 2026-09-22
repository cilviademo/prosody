import type { ReactNode } from "react";
import { useCallback, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { LibraryItem } from "../lib/types";
import { Button, Note } from "../components/ui";
import { bars, tempo, when } from "../lib/format";

const Glyph = () => (
  <svg className="glyph" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M16 4v18m0 0-6-6m6 6 6-6" stroke="currentColor" strokeWidth="1.25"
          strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export function Home({
  onOpen, recent, busy, error, errorAction,
}: {
  onOpen: (path: string) => void;
  recent: LibraryItem[];
  busy: boolean;
  error: string | null;
  /** Rendered under the error: the way to send a report about it. */
  errorAction?: ReactNode;
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
    <div className="home enter">
      <header className="hero">
        <div className="name">Prosody</div>
        <div className="line">Turn loops into records.</div>
      </header>

      <div
        className="drop"
        data-hot={hot}
        data-busy={busy}
        onClick={busy ? undefined : browse}
        onDragOver={(e) => { e.preventDefault(); setHot(true); }}
        onDragLeave={() => setHot(false)}
        onDrop={() => setHot(false)}
      >
        <span className="grid" aria-hidden="true" />
        <span className="tick tl" aria-hidden="true" />
        <span className="tick tr" aria-hidden="true" />
        <span className="tick bl" aria-hidden="true" />
        <span className="tick br" aria-hidden="true" />
        <Glyph />
        <div className="lead">
          {busy ? "Reading project" : "Drop an FL Studio project"}
        </div>
        <div className="ext">flp</div>
      </div>

      <div className="browse">
        <Button onClick={browse} disabled={busy} variant="quiet">
          Browse files
        </Button>
      </div>

      {error && (
        <div style={{ marginTop: "var(--s6)", width: "100%" }}>
          <Note strong heading="Could not open">{error}</Note>
          {errorAction}
        </div>
      )}

      {recent.length > 0 && (
        <section className="recent">
          <div className="head">
            <span className="label">Recent</span>
            <span className="label">{recent.length}</span>
          </div>
          {recent.slice(0, 6).map((item) => (
            <button
              key={item.id}
              className="recent-row"
              type="button"
              disabled={!item.exists}
              title={item.exists ? item.path : "This file has moved"}
              onClick={() => item.exists && onOpen(item.path)}
            >
              <span className="nm">{item.name}</span>
              <span className="meta">
                {item.tempo ? `${tempo(item.tempo)} BPM` : "—"}
                {item.lengthBars ? `  ·  ${bars(item.lengthBars)} bars` : ""}
              </span>
              <span className="meta">{when(item.updatedAt)}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
