import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { Report, ReportStatus } from "../api/types";
import { LEVEL_LABELS, formatDate } from "../music/format";

const FILTERS: (ReportStatus | "all")[] = ["open", "upheld", "rejected", "all"];

export function AdminReportsPage() {
  const [filter, setFilter] = useState<ReportStatus | "all">("open");
  const [reports, setReports] = useState<Report[] | null>(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api.listReports(filter);
      setReports(res.reports);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [filter]);

  useEffect(() => {
    setReports(null);
    void load();
  }, [load]);

  const resolve = async (report: Report, action: "uphold" | "reject") => {
    const verb = action === "uphold" ? "Uphold" : "Reject";
    const extra =
      action === "uphold"
        ? " This takes down every share of the song and adds a strike to the uploader."
        : " A share hidden for review will be restored.";
    if (!window.confirm(`${verb} this report?${extra}`)) return;
    setBusyId(report.id);
    try {
      const updated = await api.resolveReport(report.id, action, notes[report.id]?.trim() || undefined);
      setReports((list) =>
        list ? (filter === "all" ? list.map((r) => (r.id === updated.id ? updated : r)) : list.filter((r) => r.id !== updated.id)) : list,
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <h1>Reports</h1>
        <div className="segmented" role="radiogroup" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={filter === f}
              className={filter === f ? "active" : ""}
              onClick={() => setFilter(f)}
            >
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {reports === null && !error && <p>Loading…</p>}
      {reports && reports.length === 0 && <p className="muted">No {filter === "all" ? "" : `${filter} `}reports.</p>}
      {reports && reports.length > 0 && (
        <div className="table-wrap">
          <table className="reports-table">
            <thead>
              <tr>
                <th>Received</th>
                <th>Shared arrangement</th>
                <th>Uploader</th>
                <th>Report</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.created_at)}</td>
                  <td>
                    <a href={`/s/${r.share.slug}`} target="_blank" rel="noreferrer">
                      {r.song.title}
                    </a>
                    {r.song.artist && <div className="muted">{r.song.artist}</div>}
                    <div className="muted small-text">
                      {LEVEL_LABELS[r.share.level] ?? r.share.level}, transpose {r.share.transpose}
                    </div>
                  </td>
                  <td>
                    {r.uploader.email}
                    <div className="muted small-text">
                      {r.uploader.strikes} strike{r.uploader.strikes === 1 ? "" : "s"}
                      {r.uploader.banned && " · banned"}
                    </div>
                  </td>
                  <td className="report-details">
                    <span className={`badge ${r.reason === "copyright" ? "badge-error" : "badge-busy"}`}>{r.reason}</span>
                    <p>{r.details}</p>
                    <div className="muted small-text">
                      {r.reporter_name} &lt;{r.reporter_email}&gt;
                    </div>
                  </td>
                  <td>
                    {r.status}
                    {r.resolved_at && <div className="muted small-text">{formatDate(r.resolved_at)}</div>}
                    {r.note && <div className="muted small-text">“{r.note}”</div>}
                  </td>
                  <td>
                    {r.status === "open" ? (
                      <div className="resolve">
                        <input
                          placeholder="Note (optional)"
                          value={notes[r.id] ?? ""}
                          onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))}
                          aria-label="Resolution note"
                        />
                        <div className="resolve-buttons">
                          <button
                            type="button"
                            className="button small danger"
                            disabled={busyId === r.id}
                            onClick={() => resolve(r, "uphold")}
                          >
                            Uphold
                          </button>
                          <button
                            type="button"
                            className="button small"
                            disabled={busyId === r.id}
                            onClick={() => resolve(r, "reject")}
                          >
                            Reject
                          </button>
                        </div>
                      </div>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
