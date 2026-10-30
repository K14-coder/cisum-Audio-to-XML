export const APP_NAME = "Cisum";

/** Designated agent for copyright notices. Change this before launch. */
export const DMCA_EMAIL = "dmca@example.com";

/** Base URL for the Salamander Grand Piano samples used for playback. */
export const PIANO_SAMPLES_URL: string =
  import.meta.env.VITE_PIANO_SAMPLES_URL ?? "https://tonejs.github.io/audio/salamander/";

/** How long to wait for piano samples before falling back to a synthesizer. */
export const SAMPLE_LOAD_TIMEOUT_MS = 8000;
