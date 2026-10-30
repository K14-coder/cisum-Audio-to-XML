import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { Level, Share } from "../api/types";
import { LEVEL_LABELS, formatDate, formatTranspose } from "../music/format";
import { Modal } from "./Modal";

type Props = {
  songId: string;
  level: Level;
  transpose: number;
  onClose: () => void;
};

function absoluteUrl(url: string): string {
  return /^https?:\/\//.test(url) ? url : window.location.origin + url;
}

export function ShareDialog({ songId, level, transpose, onClose }: Props) {
  const [shares, setShares] = useState<Share[] | null>(null);
  const [created, setCreated] = useState<Share | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.listShares(songId);
      setShares(res.shares);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [songId]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const share = await api.createShare(songId, level, transpose);
      setCreated(share);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (slug: string) => {
    if (!window.confirm("Revoke this link? Anyone who has it won't be able to open it any more.")) return;
    setError("");
    try {
      await api.revokeShare(slug);
      if (created?.slug === slug) setCreated(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const copy = async (share: Share) => {
    const url = absoluteUrl(share.url);
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      window.prompt("Copy this link:", url);
    }
    setCopied(share.slug);
    window.setTimeout(() => setCopied((s) => (s === share.slug ? "" : s)), 2000);
  };

  return (
    <Modal title="Share this arrangement" onClose={onClose}>
      <p className="hint">
        Anyone with the link can view and play the {LEVEL_LABELS[level]} arrangement ({formatTranspose(transpose).toLowerCase()})
        without logging in. Only share music you have the rights to share. Shared pages include a button to report
        infringement.
      </p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <button type="button" className="button primary" onClick={create} disabled={busy}>
        {busy ? "Creating…" : "Create link"}
      </button>

      {created && (
        <div className="share-created">
          <input readOnly value={absoluteUrl(created.url)} onFocus={(e) => e.target.select()} aria-label="Share link" />
          <button type="button" className="button" onClick={() => copy(created)}>
            {copied === created.slug ? "Copied!" : "Copy"}
          </button>
        </div>
      )}

      <h3 className="subhead">Existing links</h3>
      {shares === null && !error && <p>Loading…</p>}
      {shares && shares.length === 0 && <p className="muted">No links yet.</p>}
      {shares && shares.length > 0 && (
        <ul className="share-list">
          {shares.map((s) => {
            const inactive = s.revoked || s.taken_down;
            return (
              <li key={s.slug} className={inactive ? "inactive" : ""}>
                <div className="share-info">
                  <a href={s.url} target="_blank" rel="noreferrer">
                    {absoluteUrl(s.url)}
                  </a>
                  <span className="muted">
                    {LEVEL_LABELS[s.level] ?? s.level} · {formatTranspose(s.transpose)} · {formatDate(s.created_at)}
                    {s.revoked && " · revoked"}
                    {s.taken_down && " · taken down"}
                  </span>
                </div>
                {!inactive && (
                  <span className="share-actions">
                    <button type="button" className="button small" onClick={() => copy(s)}>
                      {copied === s.slug ? "Copied!" : "Copy"}
                    </button>
                    <button type="button" className="button small danger" onClick={() => revoke(s.slug)}>
                      Revoke
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}
