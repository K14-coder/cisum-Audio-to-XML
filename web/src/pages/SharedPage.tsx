import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api, errorMessage } from "../api/client";
import type { SharedArrangement } from "../api/types";
import { ArrangementView } from "../components/ArrangementView";
import { ReportDialog } from "../components/ReportDialog";
import { LEVEL_LABELS, formatTranspose } from "../music/format";

/** Public, read-only view of a shared arrangement. No login needed. */
export function SharedPage() {
  const { slug = "" } = useParams();
  const [shared, setShared] = useState<SharedArrangement | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [error, setError] = useState("");
  const [reporting, setReporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    api
      .getSharedArrangement(slug)
      .then((s) => {
        if (cancelled) return;
        setShared(s);
        setState("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setState("missing");
        else {
          setError(errorMessage(err));
          setState("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (state === "loading") return <div className="page">Loading…</div>;
  if (state === "missing") {
    return (
      <div className="page narrow">
        <h1>This arrangement isn't available.</h1>
        <p className="muted">The link may have been revoked by its owner or removed after a report.</p>
      </div>
    );
  }
  if (state === "error" || !shared) {
    return (
      <div className="page narrow">
        <p className="error-text">{error || "Something went wrong."}</p>
      </div>
    );
  }

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>{shared.title}</h1>
          <p className="muted">
            {shared.artist ?? "Unknown artist"} · {LEVEL_LABELS[shared.level] ?? shared.level} piano arrangement ·{" "}
            {formatTranspose(shared.transpose)}
          </p>
        </div>
        <button type="button" className="button danger-outline" onClick={() => setReporting(true)}>
          Report
        </button>
      </div>
      <ArrangementView score={shared.score} files={shared.files} />
      <p className="hint shared-note">
        Shared by a Cisum user, who confirmed they have the rights to this music. If it infringes your rights, use the
        Report button.
      </p>
      {reporting && <ReportDialog slug={slug} onClose={() => setReporting(false)} />}
    </div>
  );
}
