// Types mirror docs/api.md. Keep them in sync with the backend contract.

export type User = {
  id: string;
  email: string;
  is_admin: boolean;
  strikes: number;
  banned: boolean;
};

export type AuthResponse = { user: User; token: string };

export type RightsNotice = {
  version: string;
  title: string;
  paragraphs: string[];
  checkbox_label: string;
};

export type UploadTicket = {
  upload_id: string;
  max_bytes: number;
  upload: {
    url: string;
    method: "PUT";
    headers: Record<string, string>;
  };
};

export type SongStatus =
  | "queued"
  | "ingesting"
  | "separating"
  | "analyzing"
  | "arranging"
  | "done"
  | "failed";

export type Song = {
  id: string;
  title: string;
  artist: string | null;
  status: SongStatus;
  progress: number;
  stage_message: string;
  error: { code: string; message: string } | null;
  duration_s: number | null;
  analysis_version: number;
  created_at: string;
};

export type SongEvent = Pick<Song, "status" | "progress" | "stage_message" | "error">;

export type Level = "easy" | "medium" | "hard";
export const LEVELS: Level[] = ["easy", "medium", "hard"];

/** Integer semitones in -6..6, or "auto". */
export type TransposeRequest = number | "auto";

export type KeySegment = {
  start: number;
  tonic: string;
  mode: "major" | "minor";
  name: string;
  confidence: number;
};

export type Chord = {
  start: number;
  end: number;
  symbol: string;
  root: number | null;
  quality: string | null;
  bass: number | null;
  confidence: number;
  edited?: boolean;
};

export type Note = { start: number; end: number; pitch: number; confidence: number };

export type Meter = { beats_per_bar: number; beat_unit: number };

export type Analysis = {
  version: number;
  schema: 1;
  duration_s: number;
  tuning_cents: number;
  meter: Meter;
  bpm: number;
  tempo: { bar: number; bpm: number }[];
  beat_times: number[];
  total_beats: number;
  key: KeySegment[];
  chords: Chord[];
  melody: Note[];
  bass: Note[];
  fill: Note[];
  flags: {
    has_vocals: boolean;
    melody_source: "vocals" | "accompaniment" | "none";
    low_confidence_melody: boolean;
  };
  backends: Record<string, string>;
};

export type AnalysisEdit = {
  chords?: { start: number; end: number; symbol: string }[];
  key?: { start: number; tonic: string; mode: "major" | "minor" }[];
};

export type ScoreEvent = {
  hand: "rh" | "lh";
  start: number;
  duration: number;
  pitches: number[];
  names: string[];
};

export type ScoreJson = {
  schema: 1;
  title: string;
  level: Level;
  transpose: number;
  meter: Meter;
  key: { tonic: string; mode: "major" | "minor"; fifths: number };
  bpm: number;
  tempo: { beat: number; bpm: number }[];
  total_beats: number;
  events: ScoreEvent[];
  chords: { start: number; end: number; symbol: string; confidence: number }[];
};

export type ArrangementFiles = { musicxml: string; midi: string; pdf: string };

export type Arrangement = {
  song_id: string;
  level: Level;
  transpose: number;
  analysis_version: number;
  score: ScoreJson;
  files: ArrangementFiles;
};

export type Share = {
  slug: string;
  url: string;
  song_id: string;
  level: string;
  transpose: number;
  created_at: string;
  revoked: boolean;
  taken_down: boolean;
};

export type SharedArrangement = {
  slug: string;
  title: string;
  artist: string | null;
  level: string;
  transpose: number;
  score: ScoreJson;
  files: ArrangementFiles;
};

export type ReportCreate = {
  reason: "copyright" | "other";
  details: string;
  reporter_name: string;
  reporter_email: string;
  sworn_statement: boolean;
};

export type ReportStatus = "open" | "upheld" | "rejected";

export type Report = {
  id: string;
  status: ReportStatus;
  reason: "copyright" | "other";
  details: string;
  reporter_name: string;
  reporter_email: string;
  created_at: string;
  resolved_at: string | null;
  note: string | null;
  share: { slug: string; level: string; transpose: number };
  song: { id: string; title: string; artist: string | null };
  uploader: { id: string; email: string; strikes: number; banned: boolean };
};
