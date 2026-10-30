# Rights, takedowns and licenses

This describes what the software does. It is not legal advice; have a music copyright lawyer review your setup before launch, especially the questions flagged below.

## Rights notice and consent

Before uploading, users see the notice in [`backend/cisum/api/legal.py`](../backend/cisum/api/legal.py) and must tick:

> I have the rights to upload this song and to share arrangements of it.

The upload button stays disabled until the box is ticked. The API also refuses an upload unless `rights_confirmed` is true and the client sends back the current notice version, so an old cached page can't skip a reworded notice.

Each upload stores a consent record: user, time, IP address, user agent, and the notice version agreed to (`uploads` table). **If you change the wording, bump `RIGHTS_NOTICE_VERSION`.**

Uploaded audio is deleted once it has been analyzed (`CISUM_DELETE_AUDIO_AFTER_PROCESSING=true`). Only the derived analysis and arrangements are kept.

## Reports, takedowns and repeat infringers

- Every shared arrangement has a **Report** button. A copyright report needs the reporter's name, email, details, and a good-faith statement.
- A copyright report **hides the share right away** while it's reviewed (`CISUM_AUTO_HIDE_ON_COPYRIGHT_REPORT`).
- Admins (accounts listed in `CISUM_ADMIN_EMAILS`) review reports at `/admin/reports`:
  - **Uphold:** takes down every share of that song and adds a strike to the uploader.
  - **Reject:** restores the share if no other copyright report is open.
- **Repeat infringers:** at `CISUM_STRIKE_LIMIT` upheld reports (default 3), the account is banned. It can't log in, and all of its shares are taken down. Reports and songs are kept for the audit trail.

Before launch:
1. Register a designated DMCA agent with the US Copyright Office (a short online filing).
2. Put that contact in `web/src/config.ts` (`DMCA_EMAIL`). It's shown on `/legal/takedown`.
3. Add a counter-notice process if you want one. Uploaders currently have no in-app way to contest a takedown.
4. Ask counsel about the open question: the safe harbor for user-uploaded material was written for files users store, while this service *generates* the arrangement.

## Software and model licenses

Everything the engine uses by default allows commercial use under its code license:

| Component | Used for | License |
|---|---|---|
| Demucs | stem separation | MIT |
| Beat This! | beats and downbeats | MIT |
| torchcrepe | melody pitch | MIT |
| Basic Pitch | note transcription | Apache 2.0 |
| librosa | DSP fallbacks, features | ISC |
| music21 | MusicXML | BSD-3 |
| mido | MIDI | MIT |
| Verovio | PDF engraving | LGPL-3.0 (used unmodified, as a library) |
| cairosvg | SVG → PDF | LGPL-3.0 (used unmodified, as a library) |
| OpenSheetMusicDisplay | sheet music in the browser | BSD-3 |
| Tone.js | playback | MIT |
| Salamander Grand Piano samples | playback sound | CC BY 3.0 (credit is in the footer) |

Deliberately **not** used: madmom (its models are CC BY-NC-SA, non-commercial), Essentia (AGPL-3.0), and Pop2Piano (trained on piano covers scraped from YouTube). Key detection and chord recognition are implemented in this repo instead.

**Training data caveat:** most open music models, including the MIT and Apache ones above, were trained on research datasets with non-commercial terms. Whether those terms carry over to the trained weights is unsettled. The fully clean long-term path is training on data you own, for example audio rendered from MIDI.
