import { useEffect, useRef, useState } from "react";

type Props = {
  onRecording: (blob: Blob | null) => void;
  disabled?: boolean;
};

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg", "audio/mp4"];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
}

function formatClock(seconds: number): string {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Records from the microphone; hands the finished recording to the parent as a Blob. */
export function Recorder({ onRecording, disabled = false }: Props) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);

  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const cleanupStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
  };

  useEffect(
    () => () => {
      cleanupStream();
      if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    },
    [],
  );

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const start = async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        cleanupStream();
        const type = (recorder.mimeType || mimeType || "audio/webm").split(";")[0];
        const blob = new Blob(chunksRef.current, { type });
        setPreviewUrl(URL.createObjectURL(blob));
        setState("done");
        onRecording(blob);
      };
      recorderRef.current = recorder;
      recorder.start(1000);
      startedAtRef.current = Date.now();
      setElapsed(0);
      timerRef.current = window.setInterval(() => setElapsed((Date.now() - startedAtRef.current) / 1000), 250);
      setState("recording");
      onRecording(null);
    } catch (err) {
      cleanupStream();
      setError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow it in your browser's site settings and try again."
          : "Couldn't start recording. Check that a microphone is connected.",
      );
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
  };

  const reset = () => {
    setPreviewUrl(null);
    setElapsed(0);
    setState("idle");
    onRecording(null);
  };

  if (!supported) {
    return <p className="muted">Recording isn't supported in this browser. Upload a file instead.</p>;
  }

  return (
    <div className="recorder">
      <p className="hint">Play or sing the song into your microphone. A quiet room and a clear melody work best.</p>
      <div className="recorder-controls">
        {state !== "recording" ? (
          <button type="button" className="button primary" onClick={start} disabled={disabled}>
            ● {state === "done" ? "Record again" : "Start recording"}
          </button>
        ) : (
          <button type="button" className="button danger" onClick={stop}>
            ■ Stop
          </button>
        )}
        <span className={`rec-clock${state === "recording" ? " live" : ""}`}>{formatClock(elapsed)}</span>
        {state === "done" && (
          <button type="button" className="button small" onClick={reset} disabled={disabled}>
            Discard
          </button>
        )}
      </div>
      {previewUrl && <audio className="rec-preview" controls src={previewUrl} />}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
