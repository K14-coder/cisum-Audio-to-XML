import type { SongStatus } from "../api/types";

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

const STATUS_LABELS: Record<SongStatus, string> = {
  queued: "Queued",
  ingesting: "Preparing audio",
  separating: "Separating",
  analyzing: "Analyzing",
  arranging: "Arranging",
  done: "Ready",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: SongStatus }) {
  const tone = status === "done" ? "ok" : status === "failed" ? "error" : "busy";
  return <span className={`badge badge-${tone}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function isProcessing(status: SongStatus): boolean {
  return status !== "done" && status !== "failed";
}

const STAGES: { key: SongStatus | "uploaded"; label: string }[] = [
  { key: "uploaded", label: "Uploaded" },
  { key: "ingesting", label: "Preparing audio" },
  { key: "separating", label: "Separating instruments" },
  { key: "analyzing", label: "Analyzing (beats, melody, chords, key)" },
  { key: "arranging", label: "Writing arrangements" },
];

const ORDER: Record<string, number> = {
  uploaded: 0,
  queued: 0,
  ingesting: 1,
  separating: 2,
  analyzing: 3,
  arranging: 4,
  done: 5,
};

/**
 * `status` is the current status; `lastActive` is the last non-failed status we saw,
 * so a failure can be pinned to the stage it happened in.
 */
export function StageChecklist({ status, lastActive }: { status: SongStatus; lastActive: SongStatus }) {
  const failed = status === "failed";
  const current = ORDER[failed ? lastActive : status] ?? 0;
  return (
    <ol className="stages">
      {STAGES.map((stage, i) => {
        let state: "done" | "active" | "pending" | "failed";
        if (i === 0) state = "done";
        else if (failed && i === Math.max(1, current)) state = "failed";
        else if (i < current || (!failed && current === 5)) state = "done";
        else if (i === current && !failed) state = "active";
        else state = "pending";
        return (
          <li key={stage.key} className={`stage stage-${state}`}>
            <span className="stage-icon" aria-hidden="true">
              {state === "done" ? "✓" : state === "failed" ? "!" : state === "active" ? "" : ""}
            </span>
            <span className="stage-label">{stage.label}</span>
            {state === "active" && <span className="sr-only"> (in progress)</span>}
          </li>
        );
      })}
    </ol>
  );
}
