import { useState, type FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import { Modal } from "./Modal";

export const SWORN_STATEMENT =
  "I have a good-faith belief that this use is not authorized by the copyright owner, its agent, or the law, and the information in this report is accurate.";

type Props = {
  slug: string;
  onClose: () => void;
};

export function ReportDialog({ slug, onClose }: Props) {
  const [reason, setReason] = useState<"copyright" | "other">("copyright");
  const [details, setDetails] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [sworn, setSworn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");

  const canSubmit =
    details.trim().length > 0 && name.trim().length > 0 && email.trim().length > 0 && (reason !== "copyright" || sworn);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.reportShare(slug, {
        reason,
        details: details.trim(),
        reporter_name: name.trim(),
        reporter_email: email.trim(),
        sworn_statement: reason === "copyright" ? sworn : false,
      });
      setResult(res.message || "Thanks — your report was received.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <Modal
        title="Report received"
        onClose={onClose}
        footer={
          <button type="button" className="button primary" onClick={onClose}>
            Close
          </button>
        }
      >
        <p>{result}</p>
      </Modal>
    );
  }

  return (
    <Modal title="Report this arrangement" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <fieldset className="radio-group">
          <legend>Reason</legend>
          <label className="radio">
            <input type="radio" name="reason" checked={reason === "copyright"} onChange={() => setReason("copyright")} />
            <span>It infringes my copyright (or one I represent)</span>
          </label>
          <label className="radio">
            <input type="radio" name="reason" checked={reason === "other"} onChange={() => setReason("other")} />
            <span>Something else is wrong with it</span>
          </label>
        </fieldset>
        <label className="field">
          <span>{reason === "copyright" ? "Which work is infringed, and how?" : "What's wrong?"}</span>
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            rows={5}
            maxLength={5000}
            required
            placeholder={
              reason === "copyright" ? "Title and writer(s) of the song, and your relationship to it." : undefined
            }
          />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Your name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
          <label className="field">
            <span>Your email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
        </div>
        {reason === "copyright" && (
          <label className="checkbox">
            <input type="checkbox" checked={sworn} onChange={(e) => setSworn(e.target.checked)} required />
            <span>{SWORN_STATEMENT}</span>
          </label>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button primary" disabled={!canSubmit || busy}>
            {busy ? "Sending…" : "Send report"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
