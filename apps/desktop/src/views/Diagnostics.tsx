import { useState } from "react";
import type { BackendStatus } from "../lib/types";
import { restartCore, shell } from "../lib/api";
import { Button, KeyValues, Note, Section } from "../components/ui";

/**
 * Shown when the core did not start.
 *
 * A blank window is the worst possible failure mode for a packaged app: it
 * looks broken and says nothing. This screen names what failed, where the log
 * is, and offers to try again without restarting.
 */
export function Diagnostics({
  status, onRecovered,
}: {
  status: BackendStatus;
  onRecovered: (status: BackendStatus) => void;
}) {
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const retry = async () => {
    setRetrying(true);
    setRetryError(null);
    try {
      const next = await restartCore();
      if (next.ok) onRecovered(next);
      else setRetryError(next.error ?? "The core still did not start.");
    } catch (e) {
      setRetryError(String(e));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="view enter">
      <div className="label">Diagnostics</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>
        Prosody could not start its core
      </h1>

      <div style={{ marginTop: "var(--s5)" }}>
        <Note strong heading="What failed">
          {status.error ?? "The core did not answer the startup check."}
        </Note>
      </div>

      <p className="copy" style={{ marginTop: "var(--s5)" }}>
        Everything else in Prosody depends on this process, so nothing else will
        work until it starts. If you are running from a source checkout, Prosody
        needs Python 3.10 or newer — set{" "}
        <span className="mono">PROSODY_PYTHON</span> to point at it. A packaged
        build ships its own copy and should not need Python at all; if this
        happens in a release, the log below is the place to start.
      </p>

      <div className="row wrap" style={{ marginTop: "var(--s7)" }}>
        <Button variant="primary" onClick={retry} disabled={retrying}>
          {retrying ? "Starting" : "Try again"}
        </Button>
        <Button onClick={() => void shell.reveal(status.logs)}>Open log folder</Button>
      </div>

      {retryError && (
        <div style={{ marginTop: "var(--s5)" }}>
          <Note strong heading="Still failing">{retryError}</Note>
        </div>
      )}

      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Environment">
          <KeyValues
            rows={[
              ["Mode", status.portable ? "Portable" : "Installed"],
              ["Documents", <span className="mono" key="d">{status.documents}</span>],
              ["App data", <span className="mono" key="s">{status.state}</span>],
              ["Logs", <span className="mono" key="l">{status.logs}</span>],
              ["Core", <span className="mono" key="c">{status.coreExecutable ?? "not resolved"}</span>],
            ]}
          />
        </Section>
      </div>
    </div>
  );
}
