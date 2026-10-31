/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Salamander piano samples (must end with "/"). */
  readonly VITE_PIANO_SAMPLES_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
