# Cisum web app

The browser front end: upload or record a song, follow processing, then read, play and share the piano arrangement.

Built with Vite, React 18, TypeScript, [OpenSheetMusicDisplay](https://opensheetmusicdisplay.org/) (renders the MusicXML) and [Tone.js](https://tonejs.github.io/) (playback). It talks to the API described in [`../docs/api.md`](../docs/api.md).

## Develop

```bash
npm install
npm run dev
```

The dev server runs on http://localhost:5173 and proxies `/api` to the backend at http://localhost:8000 (start it from `../backend`). Point it elsewhere with `VITE_API_PROXY`:

```bash
VITE_API_PROXY=http://localhost:9000 npm run dev
```

## Build

```bash
npm run build
```

This type-checks (`tsc --noEmit`) and writes static files to `dist/`. Serve `dist/` from the same origin as the API (the app uses the session cookie and relative `/api` URLs), and route unknown paths to `index.html` so client-side routes like `/songs/:id` and `/s/:slug` work. `npm run preview` serves the build locally with the same `/api` proxy.

## Configuration

| Variable | Used | Default | Purpose |
|---|---|---|---|
| `VITE_PIANO_SAMPLES_URL` | build time | `https://tonejs.github.io/audio/salamander/` | Base URL (ending in `/`) of the Salamander Grand Piano samples. Self-host them for production. If they can't be loaded within 8 seconds, playback falls back to a synthesizer. |
| `VITE_API_PROXY` | dev/preview only | `http://localhost:8000` | Where the dev server forwards `/api`. |

The designated copyright agent's email shown on `/legal/takedown` is `DMCA_EMAIL` in `src/config.ts`. Change it before launch.

## Structure

```
src/
  api/          typed client (one function per endpoint), upload with progress, SSE reader
  auth/         session context and the RequireAuth route guard
  pages/        Library, New song, Song (progress + viewer), Shared, Admin reports, legal pages, login/register
  components/   ArrangementView (player + tabs), SheetMusic, LetterNames, FallingNotes,
                ChordEditor, ShareDialog, ReportDialog, RightsNotice, Recorder, FileDrop, Progress, Modal
  playback/     usePlayback (Tone.js transport, shared playback clock), tempo map, piano loader
  music/        formatting helpers (note names, bars/beats, chord symbols)
```

All three views read one shared playback clock, so the sheet-music cursor, the highlighted bar in Letter names and the falling notes stay in sync.

## Credits

Piano samples: Salamander Grand Piano by Alexander Holm, CC BY 3.0. Keep the credit line in the footer if you use them.
