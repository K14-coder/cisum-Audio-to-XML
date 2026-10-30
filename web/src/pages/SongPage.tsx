import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, errorMessage, streamSongEvents } from "../api/client";
import type { Arrangement, Level, Song, SongEvent, SongStatus, TransposeRequest } from "../api/types";
import { LEVELS } from "../api/types";
import { ArrangementView } from "../components/ArrangementView";
import { ChordEditor } from "../components/ChordEditor";
import { ProgressBar, StageChecklist, StatusBadge, isProcessing } from "../components/Progress";
import { ShareDialog } from "../components/ShareDialog";
import { LEVEL_LABELS, formatDuration } from "../music/format";

export function SongPage() {
  const { id = "" } = useParams();
  const [song, setSong] = useState<Song | null>(null);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const lastActive = useRef<SongStatus>("queued");

  const loadSong = useCallback(async () => {
    try {
      const s = await api.getSong(id);
      if (s.status !== "failed") lastActive.current = s.status;
      setSong(s);
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    setSong(null);
    setNotFound(false);
    void loadSong();
  }, [loadSong]);

  const processing = song ? isProcessing(song.status) : false;

  // Follow progress with server-sent events; fall back to polling if the stream breaks.
  useEffect(() => {
    if (!processing) return;
    const controller = new AbortController();
    let pollTimer: number | null = null;
    const apply = (ev: SongEvent) => {
      if (ev.status !== "failed") lastActive.current = ev.status;
      setSong((prev) => (prev ? { ...prev, ...ev } : prev));
      if (!isProcessing(ev.status)) void loadSong();
    };
    const poll = () => {
      pollTimer = window.setInterval(async () => {
        try {
          const s = await api.getSong(id);
          apply(s);
          if (!isProcessing(s.status) && pollTimer !== null) window.clearInterval(pollTimer);
        } catch {
          // Keep trying; transient errors are expected while the server restarts.
        }
      }, 2000);
    };
    streamSongEvents(id, apply, controller.signal)
      .then(() => {
        // The stream closes after done/failed. If it closed early, poll to be sure.
        if (!controller.signal.aborted) void loadSong();
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        console.warn("Progress stream failed, polling instead:", err);
        poll();
      });
    return () => {
      controller.abort();
      if (pollTimer !== null) window.clearInterval(pollTimer);
    };
  }, [id, processing, loadSong]);

  if (notFound) {
    return (
      <div className="page narrow">
        <h1>Song not found</h1>
        <p>
          It may have been deleted. <Link to="/">Back to your songs</Link>
        </p>
      </div>
    );
  }
  if (!song) {
    return <div className="page">{error ? <p className="error-text">{error}</p> : <p>Loading…</p>}</div>;
  }

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>{song.title}</h1>
          <p className="muted">
            {song.artist ?? "Unknown artist"}
            {song.duration_s ? ` · ${formatDuration(song.duration_s)}` : ""}
          </p>
        </div>
        <StatusBadge status={song.status} />
      </div>

      {song.status === "done" ? (
        <SongViewer song={song} onAnalysisSaved={loadSong} />
      ) : (
        <div className="card processing">
          <StageChecklist status={song.status} lastActive={lastActive.current} />
          {song.status === "failed" ? (
            <div className="failure">
              <p className="error-text">{song.error?.message ?? "Processing failed."}</p>
              <Link to="/new" className="button">
                Try another file
              </Link>
            </div>
          ) : (
            <>
              <ProgressBar value={song.progress} label="Processing progress" />
              <p className="muted">
                {song.stage_message || "Waiting for a free worker…"} · {Math.round(song.progress * 100)}%
              </p>
              <p className="hint">This usually takes under a minute. You can leave this page; it keeps going.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SongViewer({ song, onAnalysisSaved }: { song: Song; onAnalysisSaved: () => Promise<void> }) {
  const [level, setLevel] = useState<Level>("easy");
  const [transpose, setTranspose] = useState<TransposeRequest>("auto");
  const [arrangement, setArrangement] = useState<Arrangement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .getArrangement(song.id, level, transpose, controller.signal)
      .then((a) => {
        setArrangement(a);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => controller.abort();
  }, [song.id, level, transpose, song.analysis_version, reloadKey]);

  const resolved = arrangement?.transpose ?? 0;

  const toolbar = (
    <>
      <div className="segmented" role="radiogroup" aria-label="Difficulty">
        {LEVELS.map((l) => (
          <button
            key={l}
            type="button"
            role="radio"
            aria-checked={level === l}
            className={level === l ? "active" : ""}
            onClick={() => setLevel(l)}
          >
            {LEVEL_LABELS[l]}
          </button>
        ))}
      </div>
      <label className="inline-field">
        <span>Transpose</span>
        <select
          value={String(transpose)}
          onChange={(e) => setTranspose(e.target.value === "auto" ? "auto" : Number(e.target.value))}
        >
          <option value="auto">Auto{transpose === "auto" && arrangement ? ` (${signed(resolved)})` : ""}</option>
          {Array.from({ length: 13 }, (_, i) => i - 6).map((t) => (
            <option key={t} value={t}>
              {t === 0 ? "Original key" : signed(t)}
            </option>
          ))}
        </select>
      </label>
      <span className="toolbar-spacer" />
      <button type="button" className="button" onClick={() => setEditing(true)}>
        Edit chords
      </button>
      <button type="button" className="button" onClick={() => setSharing(true)} disabled={!arrangement}>
        Share
      </button>
    </>
  );

  return (
    <>
      {error && (
        <div className="card error-card">
          <p className="error-text">{error}</p>
          <button type="button" className="button" onClick={() => setReloadKey((k) => k + 1)}>
            Try again
          </button>
        </div>
      )}
      {arrangement ? (
        <ArrangementView score={arrangement.score} files={arrangement.files} toolbar={toolbar} busy={loading} />
      ) : (
        !error && (
          <div className="card">
            <div className="toolbar">{toolbar}</div>
            <p>Writing the {LEVEL_LABELS[level]} arrangement…</p>
          </div>
        )
      )}
      {editing && (
        <ChordEditor
          songId={song.id}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            void onAnalysisSaved();
            setReloadKey((k) => k + 1);
          }}
        />
      )}
      {sharing && arrangement && (
        <ShareDialog songId={song.id} level={level} transpose={resolved} onClose={() => setSharing(false)} />
      )}
    </>
  );
}

function signed(t: number): string {
  return t === 0 ? "0" : t > 0 ? `+${t}` : `−${Math.abs(t)}`;
}
