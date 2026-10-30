# HTTP API

All endpoints live under `/api`. Request and response bodies are JSON unless noted.

## Authentication

Two ways to authenticate, both accepted on every endpoint:

- **Session cookie** `cisum_session` (httpOnly, `SameSite=Lax`), set by register/login. This is what the web app uses, and it lets plain `<a href>` downloads work.
- **Bearer token** `Authorization: Bearer <token>` (the same token is returned in the register/login body), for scripts.

When a request is authenticated with the cookie, every non-GET request must also send the header `X-Cisum-CSRF: 1`. Requests without it get `403 {"detail": "missing CSRF header"}`.

Errors use FastAPI's shape: `{"detail": "human readable message"}` (validation errors: `{"detail": [ ... ]}`) with a matching status code (400, 401, 403, 404, 409, 413, 422).

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/register` | `{email, password}` (password ≥ 8 chars) | `201 {user: User, token}` + cookie |
| POST | `/api/auth/login` | `{email, password}` | `200 {user: User, token}` + cookie |
| POST | `/api/auth/logout` | – | `204`, clears cookie |
| GET | `/api/auth/me` | – | `200 User` or `401` |

```ts
type User = { id: string; email: string; is_admin: boolean; strikes: number; banned: boolean; single_user: boolean }
```

When the server runs in personal mode (`CISUM_SINGLE_USER=true`, used by `start.sh`), every request is the one local user. `/api/auth/me` returns it with `single_user: true`, and clients should hide login and logout.

A banned user (too many upheld copyright reports) gets `403` on login and on every authenticated endpoint.

## Rights notice

| Method | Path | Response |
|---|---|---|
| GET | `/api/legal/rights-notice` | `RightsNotice` |

```ts
type RightsNotice = {
  version: string            // e.g. "2026-10-30"; send it back when uploading
  title: string              // "Only upload music you have the rights to."
  paragraphs: string[]       // body text, one entry per paragraph
  checkbox_label: string     // "I have the rights to upload this song and to share arrangements of it."
}
```

## Uploads

Uploading is three steps: create the upload (records the rights consent), send the bytes, then complete it (creates the song and queues processing).

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/uploads` | `{filename, content_type, size_bytes, rights_confirmed: true, rights_notice_version}` | `201 UploadTicket` |
| PUT | `UploadTicket.upload.url` | raw file bytes | `204` |
| POST | `/api/uploads/{upload_id}/complete` | `{title, artist?}` | `201 Song` |

```ts
type UploadTicket = {
  upload_id: string
  max_bytes: number
  upload: {
    url: string                       // relative "/api/uploads/{id}/content" (local storage) or an absolute presigned S3 URL
    method: "PUT"
    headers: Record<string, string>   // send these exactly (e.g. Content-Type); add X-Cisum-CSRF only when url is relative
  }
}
```

- `rights_confirmed` must be `true` and `rights_notice_version` must equal the current notice version, otherwise `422`.
- Files over the size limit (default 200 MB) get `413`. Accepted types: any `audio/*` or `video/*` (mp3, mp4, wav, m4a/aac, mov, flac, ogg, webm from the mic recorder); for videos only the sound is used. `application/octet-stream` is accepted when the filename has a known audio/video extension. The server checks the actual content with ffprobe during processing, so a video without sound fails with `not_audio`.

## Songs

```ts
type SongStatus = "queued" | "ingesting" | "separating" | "analyzing" | "arranging" | "done" | "failed"

type Song = {
  id: string
  title: string
  artist: string | null
  status: SongStatus
  progress: number                // 0..1 across the whole job
  stage_message: string           // e.g. "Separating instruments…"
  error: { code: string; message: string } | null   // set when status == "failed"
  duration_s: number | null
  analysis_version: number        // increments on every analysis edit
  created_at: string              // ISO 8601
}
```

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/songs` | – | `200 {songs: Song[]}` newest first |
| GET | `/api/songs/{id}` | – | `200 Song` |
| PATCH | `/api/songs/{id}` | `{title?, artist?}` | `200 Song` |
| DELETE | `/api/songs/{id}` | – | `204` |
| GET | `/api/songs/{id}/events` | – | Server-sent events (see below) |
| GET | `/api/songs/{id}/analysis` | – | `200 Analysis` (`409` until status is `done`) |
| PATCH | `/api/songs/{id}/analysis` | `AnalysisEdit` | `200 Analysis` |
| GET | `/api/songs/{id}/arrangement?level=easy&transpose=0` | – | `200 Arrangement` |
| GET | `/api/songs/{id}/files/{level}.{ext}?transpose=0` | – | file download, `ext` ∈ `musicxml`, `mid`, `pdf` |

`level` ∈ `easy | medium | hard`. `transpose` is an integer in `-6..6` semitones, or the string `auto` (picks an easier key; this is the default for `easy` when omitted). The resolved transposition is returned in `Arrangement.transpose`.

### Progress events

`GET /api/songs/{id}/events` returns `text/event-stream`. Each message is

```
event: status
data: {"status":"separating","progress":0.31,"stage_message":"Separating instruments…","error":null}
```

A message is sent immediately, then whenever something changes. The stream closes after a `done` or `failed` message. The web app reads it with `fetch` (so the cookie is sent) rather than `EventSource`; either works.

### Analysis

The song model produced once per upload. Times are in **beats** counted from the start of bar 1 (bar = `floor(start / beats_per_bar) + 1`), except `beat_times`, which maps beat index → seconds in the original audio.

```ts
type Analysis = {
  version: number                    // analysis_version
  schema: 1
  duration_s: number
  tuning_cents: number
  meter: { beats_per_bar: number; beat_unit: number }
  bpm: number                        // median tempo
  tempo: { bar: number; bpm: number }[]
  beat_times: number[]               // seconds of beat 0, 1, 2, …
  total_beats: number
  key: KeySegment[]
  chords: Chord[]
  melody: Note[]
  bass: Note[]
  fill: Note[]                       // top line of the accompaniment, used where the melody rests
  flags: { has_vocals: boolean; melody_source: "vocals" | "accompaniment" | "none"; low_confidence_melody: boolean }
  backends: Record<string, string>   // which model ran each stage, e.g. {"separation":"demucs:htdemucs", ...}
}

type KeySegment = { start: number; tonic: string; mode: "major" | "minor"; name: string; confidence: number }
type Chord = {
  start: number; end: number
  symbol: string                     // "G", "Em7", "D/F#", "Bbmaj7", "Csus4", or "N" for no chord
  root: number | null                // pitch class 0..11 (C = 0), null for "N"
  quality: string | null             // "maj" | "min" | "7" | "maj7" | "min7" | "sus2" | "sus4" | "dim" | "aug" | "6" | "min6"
  bass: number | null                // pitch class of the bass note (differs from root for slash chords)
  confidence: number                 // 0..1; below 0.5 is worth highlighting in the editor
  edited?: boolean                   // true when a user set it
}
type Note = { start: number; end: number; pitch: number; confidence: number }   // pitch = MIDI number, 60 = middle C
```

### Editing the analysis

```ts
type AnalysisEdit = {
  chords?: { start: number; end: number; symbol: string }[]   // full replacement list; gaps become "N"
  key?: { start: number; tonic: string; mode: "major" | "minor" }[]
}
```

Invalid chord symbols return `422` with the offending symbol in `detail`. A successful edit bumps `analysis_version`, so every level regenerates with the fix the next time it's requested.

### Arrangement

```ts
type Arrangement = {
  song_id: string
  level: "easy" | "medium" | "hard"
  transpose: number                  // resolved semitones
  analysis_version: number
  score: ScoreJson
  files: { musicxml: string; midi: string; pdf: string }   // relative URLs under /api/songs/{id}/files/...
}

type ScoreJson = {
  schema: 1
  title: string
  level: "easy" | "medium" | "hard"
  transpose: number
  meter: { beats_per_bar: number; beat_unit: number }
  key: { tonic: string; mode: "major" | "minor"; fifths: number }   // after transposition; fifths < 0 = flats
  bpm: number
  tempo: { beat: number; bpm: number }[]      // tempo changes, for playback that follows the song
  total_beats: number
  events: {
    hand: "rh" | "lh"
    start: number                             // beats
    duration: number                          // beats
    pitches: number[]                         // MIDI numbers, ascending
    names: string[]                           // spelled for the key, same order as pitches, e.g. ["F#4", "A4"]
  }[]
  chords: { start: number; end: number; symbol: string; confidence: number }[]   // transposed symbols
}
```

Within one hand, events never overlap: notes that sound together are one event with several pitches.

## Sharing

```ts
type Share = {
  slug: string; url: string                  // url = "/s/{slug}" (web route)
  song_id: string; level: string; transpose: number
  created_at: string; revoked: boolean; taken_down: boolean
}
```

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/songs/{id}/shares` | `{level, transpose}` | `201 Share` |
| GET | `/api/songs/{id}/shares` | – | `200 {shares: Share[]}` |
| DELETE | `/api/shares/{slug}` | – | `204` (owner revokes) |

### Public (no login)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/public/shares/{slug}` | – | `200 SharedArrangement`, `404` if revoked, taken down or hidden pending review |
| GET | `/api/public/shares/{slug}/files/score.{ext}` | – | file download, `ext` ∈ `musicxml`, `mid`, `pdf` |
| POST | `/api/public/shares/{slug}/reports` | `ReportCreate` | `201 {id, message}` |

```ts
type SharedArrangement = {
  slug: string; title: string; artist: string | null
  level: string; transpose: number
  score: ScoreJson
  files: { musicxml: string; midi: string; pdf: string }
}

type ReportCreate = {
  reason: "copyright" | "other"
  details: string                        // what is infringed / what is wrong (required, ≤ 5000 chars)
  reporter_name: string
  reporter_email: string
  sworn_statement: boolean               // required true when reason == "copyright": good-faith + accuracy statement
}
```

A copyright report hides the share right away while it's reviewed.

## Admin (users with `is_admin`)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/admin/reports?status=open` | – | `200 {reports: Report[]}` (`status` ∈ `open`, `upheld`, `rejected`, `all`) |
| POST | `/api/admin/reports/{id}/resolve` | `{action: "uphold" \| "reject", note?}` | `200 Report` |

```ts
type Report = {
  id: string; status: "open" | "upheld" | "rejected"
  reason: "copyright" | "other"; details: string
  reporter_name: string; reporter_email: string
  created_at: string; resolved_at: string | null; note: string | null
  share: { slug: string; level: string; transpose: number }
  song: { id: string; title: string; artist: string | null }
  uploader: { id: string; email: string; strikes: number; banned: boolean }
}
```

Upholding takes down every share of that song and adds a strike to the uploader; at the strike limit (default 3) the account is banned and all its shares are taken down. Rejecting restores the share if it was hidden.
