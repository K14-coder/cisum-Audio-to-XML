import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { Song } from "../api/types";
import { ProgressBar, StatusBadge, isProcessing } from "../components/Progress";
import { formatDate, formatDuration } from "../music/format";

export function LibraryPage() {
  const [songs, setSongs] = useState<Song[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.listSongs();
      setSongs(res.songs);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep progress bars moving while anything is still processing.
  const anyProcessing = songs?.some((s) => isProcessing(s.status)) ?? false;
  useEffect(() => {
    if (!anyProcessing) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [anyProcessing, load]);

  const remove = async (song: Song) => {
    if (!window.confirm(`Delete “${song.title}”? Its arrangements and share links will be removed too.`)) return;
    try {
      await api.deleteSong(song.id);
      setSongs((list) => list?.filter((s) => s.id !== song.id) ?? null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Your songs</h1>
        <Link to="/new" className="button primary">
          + New song
        </Link>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {songs === null && !error && <p>Loading…</p>}
      {songs && songs.length === 0 && (
        <div className="empty card">
          <h2>No songs yet</h2>
          <p className="muted">Upload a recording you have the rights to, and we'll write it out for piano.</p>
          <Link to="/new" className="button primary">
            Upload your first song
          </Link>
        </div>
      )}
      {songs && songs.length > 0 && (
        <ul className="song-list">
          {songs.map((song) => (
            <li key={song.id} className="song-item card">
              <Link to={`/songs/${song.id}`} className="song-link">
                <div className="song-title">
                  <strong>{song.title}</strong>
                  {song.artist && <span className="muted"> · {song.artist}</span>}
                </div>
                <div className="song-meta muted">
                  {formatDate(song.created_at)}
                  {song.duration_s ? ` · ${formatDuration(song.duration_s)}` : ""}
                </div>
                {isProcessing(song.status) && (
                  <div className="song-progress">
                    <ProgressBar value={song.progress} label={`${song.title} progress`} />
                    <span className="muted small-text">{song.stage_message}</span>
                  </div>
                )}
                {song.status === "failed" && song.error && <div className="error-text small-text">{song.error.message}</div>}
              </Link>
              <div className="song-side">
                <StatusBadge status={song.status} />
                <button type="button" className="button small danger" onClick={() => remove(song)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
