import { useState, type ReactNode } from "react";
import type { ArrangementFiles, ScoreJson } from "../api/types";
import { prettyChord } from "../music/format";
import { usePlayback } from "../playback/usePlayback";
import { FallingNotes } from "./FallingNotes";
import { LetterNames } from "./LetterNames";
import { SheetMusic } from "./SheetMusic";

type Tab = "sheet" | "letters" | "falling";

const TABS: { key: Tab; label: string }[] = [
  { key: "sheet", label: "Sheet music" },
  { key: "letters", label: "Letter names" },
  { key: "falling", label: "Falling notes" },
];

type Props = {
  score: ScoreJson;
  files: ArrangementFiles;
  /** Owner-only controls (difficulty, transpose, edit, share) rendered above the player. */
  toolbar?: ReactNode;
  /** Shown over the views while a new arrangement loads. */
  busy?: boolean;
};

function loadTab(): Tab {
  try {
    const t = window.localStorage.getItem("cisum.tab");
    if (t === "sheet" || t === "letters" || t === "falling") return t;
  } catch {
    // Storage can be unavailable (private mode); fall through to the default.
  }
  return "sheet";
}

/** Player controls, downloads and the three views of one arrangement. Used by the owner and the shared page. */
export function ArrangementView({ score, files, toolbar, busy = false }: Props) {
  const [tab, setTabState] = useState<Tab>(loadTab);
  const playback = usePlayback(score);
  const { status, play, pause, stop, tempoFactor, setTempoFactor, instrument, seek, clock } = playback;

  const setTab = (t: Tab) => {
    setTabState(t);
    try {
      window.localStorage.setItem("cisum.tab", t);
    } catch {
      // Ignore.
    }
  };

  const keyLabel = `${prettyChord(score.key.tonic)} ${score.key.mode}`;

  return (
    <div className="arrangement">
      {toolbar && <div className="toolbar">{toolbar}</div>}

      <div className="player">
        <div className="player-buttons">
          {status === "playing" ? (
            <button type="button" className="button primary" onClick={pause}>
              ❚❚ Pause
            </button>
          ) : (
            <button type="button" className="button primary" onClick={play} disabled={status === "loading"}>
              {status === "loading" ? "Loading piano…" : status === "paused" ? "▶ Resume" : "▶ Play"}
            </button>
          )}
          <button type="button" className="button" onClick={stop} disabled={status === "stopped"}>
            ■ Stop
          </button>
        </div>
        <label className="tempo">
          <span>
            Tempo {Math.round(tempoFactor * 100)}% · {Math.round(score.bpm * tempoFactor)} BPM
          </span>
          <input
            type="range"
            min={50}
            max={150}
            step={5}
            value={Math.round(tempoFactor * 100)}
            onChange={(e) => setTempoFactor(Number(e.target.value) / 100)}
          />
        </label>
        <div className="player-meta">
          <span>
            {score.meter.beats_per_bar}/{score.meter.beat_unit}
          </span>
          <span>{keyLabel}</span>
          {instrument === "synth" && <span title="Piano samples couldn't be loaded">Synth sound</span>}
        </div>
        <div className="downloads">
          <span className="downloads-label">Download</span>
          <a className="button small" href={files.pdf} download>
            PDF
          </a>
          <a className="button small" href={files.midi} download>
            MIDI
          </a>
          <a className="button small" href={files.musicxml} download>
            MusicXML
          </a>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tab${tab === t.key ? " active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className={`tab-panel${busy ? " busy" : ""}`} role="tabpanel">
        {busy && <div className="busy-overlay">Updating arrangement…</div>}
        {tab === "sheet" && <SheetMusic musicxmlUrl={files.musicxml} clock={clock} />}
        {tab === "letters" && <LetterNames score={score} clock={clock} onSeek={seek} />}
        {tab === "falling" && <FallingNotes score={score} clock={clock} />}
      </div>
    </div>
  );
}
