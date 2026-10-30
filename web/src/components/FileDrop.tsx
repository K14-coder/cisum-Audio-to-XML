import { useRef, useState, type DragEvent } from "react";

type Props = {
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
};

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileDrop({ file, onFile, disabled = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  return (
    <div
      className={`dropzone${over ? " over" : ""}${disabled ? " disabled" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="audio/*,video/*,.mp3,.mp4,.m4a,.mov,.wav,.flac,.ogg,.webm"
        hidden
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      {file ? (
        <div className="dropzone-file">
          <strong>{file.name}</strong>
          <span className="muted">{formatSize(file.size)} · click to choose a different file</span>
        </div>
      ) : (
        <div className="dropzone-empty">
          <strong>Drop an audio or video file here</strong>
          <span className="muted">or click to choose one · MP3, MP4, WAV, M4A, MOV, FLAC, OGG · only the sound is used</span>
        </div>
      )}
    </div>
  );
}
