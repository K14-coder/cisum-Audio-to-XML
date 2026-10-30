import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, errorMessage, uploadBytes } from "../api/client";
import type { RightsNotice as Notice } from "../api/types";
import { FileDrop } from "../components/FileDrop";
import { ProgressBar } from "../components/Progress";
import { Recorder } from "../components/Recorder";
import { RightsNotice } from "../components/RightsNotice";

const EXTENSION_TYPES: Record<string, string> = {
  mp3: "audio/mpeg",
  wav: "audio/wav",
  wave: "audio/wav",
  m4a: "audio/mp4",
  mp4: "audio/mp4",
  aac: "audio/aac",
  flac: "audio/flac",
  ogg: "audio/ogg",
  oga: "audio/ogg",
  opus: "audio/ogg",
  webm: "audio/webm",
  aif: "audio/aiff",
  aiff: "audio/aiff",
};

function contentTypeFor(file: Blob, filename: string): string | null {
  const type = file.type.split(";")[0].trim();
  if (type.startsWith("audio/")) return type;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TYPES[ext] ?? null;
}

function recordingName(type: string): string {
  const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return `recording-${stamp}.${ext}`;
}

type Phase = "idle" | "preparing" | "uploading" | "finishing";

export function NewSongPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"file" | "record">("file");
  const [file, setFile] = useState<File | null>(null);
  const [recording, setRecording] = useState<Blob | null>(null);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [noticeError, setNoticeError] = useState("");
  const [rightsOk, setRightsOk] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .rightsNotice()
      .then(setNotice)
      .catch((err) => setNoticeError(errorMessage(err)));
  }, []);

  // Suggest a title from the file name.
  const onFile = (f: File | null) => {
    setFile(f);
    setError("");
    if (f && !title.trim()) setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").trim());
  };

  const source: { blob: Blob; name: string } | null =
    tab === "file"
      ? file && { blob: file, name: file.name }
      : recording && { blob: recording, name: recordingName(recording.type) };

  const busy = phase !== "idle";
  const canSubmit = !!source && !!notice && rightsOk && title.trim().length > 0 && !busy;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!source || !notice || !rightsOk) return;
    const contentType = contentTypeFor(source.blob, source.name);
    if (!contentType) {
      setError("That doesn't look like an audio file. Try MP3, WAV, M4A, FLAC or OGG.");
      return;
    }
    setError("");
    setProgress(0);
    try {
      setPhase("preparing");
      const ticket = await api.createUpload({
        filename: source.name,
        content_type: contentType,
        size_bytes: source.blob.size,
        rights_confirmed: true,
        rights_notice_version: notice.version,
      });
      if (source.blob.size > ticket.max_bytes) {
        throw new ApiError(413, `That file is too large. The limit is ${Math.floor(ticket.max_bytes / 1048576)} MB.`, null);
      }
      setPhase("uploading");
      await uploadBytes(ticket, source.blob, setProgress);
      setPhase("finishing");
      const song = await api.completeUpload(ticket.upload_id, {
        title: title.trim(),
        ...(artist.trim() ? { artist: artist.trim() } : {}),
      });
      navigate(`/songs/${song.id}`);
    } catch (err) {
      setPhase("idle");
      if (err instanceof ApiError && err.status === 422 && /notice|rights/i.test(err.message)) {
        // The notice changed since the page loaded: show the new one and ask again.
        setRightsOk(false);
        api.rightsNotice().then(setNotice).catch(() => undefined);
        setError(`${err.message} Please read the notice again and confirm.`);
      } else if (err instanceof ApiError && err.status === 413) {
        setError(err.message || "That file is too large.");
      } else {
        setError(errorMessage(err));
      }
    }
  };

  return (
    <div className="page narrow">
      <h1>New song</h1>
      <form className="form" onSubmit={submit}>
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "file"}
            className={`tab${tab === "file" ? " active" : ""}`}
            onClick={() => setTab("file")}
            disabled={busy}
          >
            Upload a file
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "record"}
            className={`tab${tab === "record" ? " active" : ""}`}
            onClick={() => setTab("record")}
            disabled={busy}
          >
            Record
          </button>
        </div>
        <div className="card">
          {tab === "file" ? (
            <FileDrop file={file} onFile={onFile} disabled={busy} />
          ) : (
            <Recorder onRecording={setRecording} disabled={busy} />
          )}
        </div>

        <div className="field-row">
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} disabled={busy} />
          </label>
          <label className="field">
            <span>
              Artist <span className="muted">(optional)</span>
            </span>
            <input value={artist} onChange={(e) => setArtist(e.target.value)} maxLength={200} disabled={busy} />
          </label>
        </div>

        {notice ? (
          <RightsNotice notice={notice} checked={rightsOk} onChange={setRightsOk} />
        ) : noticeError ? (
          <p className="error-text">Couldn't load the rights notice: {noticeError}</p>
        ) : (
          <p className="muted">Loading the rights notice…</p>
        )}

        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}

        {busy && (
          <div className="upload-progress">
            <ProgressBar value={phase === "uploading" ? progress : phase === "finishing" ? 1 : 0} label="Upload progress" />
            <span className="muted">
              {phase === "preparing" && "Preparing upload…"}
              {phase === "uploading" && `Uploading… ${Math.round(progress * 100)}%`}
              {phase === "finishing" && "Starting processing…"}
            </span>
          </div>
        )}

        <button type="submit" className="button primary block" disabled={!canSubmit}>
          {busy ? "Uploading…" : "Upload and create sheet music"}
        </button>
        {!rightsOk && notice && <p className="hint center">Tick the box above to confirm you have the rights.</p>}
      </form>
    </div>
  );
}
