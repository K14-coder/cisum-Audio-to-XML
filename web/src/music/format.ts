import type { Meter } from "../api/types";

/** "F#4" → "F♯4", "Bb3" → "B♭3". Leaves anything unexpected untouched. */
export function prettyNoteName(name: string): string {
  const m = /^([A-G])(##|bb|#|b|x|-{1,2})?(-?\d+)?$/.exec(name);
  if (!m) return name;
  const [, letter, acc = "", octave = ""] = m;
  const accidental =
    acc === "#" ? "♯" : acc === "##" || acc === "x" ? "𝄪" : acc === "b" || acc === "-" ? "♭" : acc === "bb" || acc === "--" ? "𝄫" : "";
  return `${letter}${accidental}${octave}`;
}

/** Chord symbols use ASCII accidentals; show proper ones. */
export function prettyChord(symbol: string): string {
  if (symbol === "N") return "N.C.";
  return symbol.replace(/([A-G])#/g, "$1♯").replace(/([A-G])b/g, "$1♭");
}

export function barOf(beat: number, meter: Meter): number {
  return Math.floor(beat / meter.beats_per_bar + 1e-9) + 1;
}

/** 1-based beat inside its bar, e.g. 1, 2.5. */
export function beatInBar(beat: number, meter: Meter): number {
  const pos = beat - (barOf(beat, meter) - 1) * meter.beats_per_bar;
  return Math.round((pos + 1) * 100) / 100;
}

export function formatBarBeat(beat: number, meter: Meter): string {
  return `Bar ${barOf(beat, meter)} · beat ${beatInBar(beat, meter)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatTranspose(t: number): string {
  if (t === 0) return "Original key";
  return `${t > 0 ? "+" : "−"}${Math.abs(t)} semitone${Math.abs(t) === 1 ? "" : "s"}`;
}

export const LEVEL_LABELS: Record<string, string> = { easy: "Easy", medium: "Medium", hard: "Hard" };

export const TONICS = ["C", "C#", "Db", "D", "Eb", "E", "F", "F#", "Gb", "G", "Ab", "A", "Bb", "B"];

/** Client-side sanity check; the server is the authority. */
export const CHORD_SYMBOL_RE = /^(N|[A-G](#|b)?(m|maj7|m7|7|sus2|sus4|dim|aug|6|m6|min|maj|min7|dim7|m7b5|9|add9)?(\/[A-G](#|b)?)?)$/;

export function isBlackKey(midi: number): boolean {
  return [1, 3, 6, 8, 10].includes(((midi % 12) + 12) % 12);
}
