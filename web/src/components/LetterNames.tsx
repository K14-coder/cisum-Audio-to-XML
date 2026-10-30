import { useEffect, useMemo, useRef, useState } from "react";
import type { ScoreEvent, ScoreJson } from "../api/types";
import { prettyChord, prettyNoteName } from "../music/format";
import { scoreEndBeat, type PlaybackClock } from "../playback/usePlayback";

type Props = {
  score: ScoreJson;
  clock: PlaybackClock;
  onSeek?: (beat: number) => void;
};

type Bar = {
  index: number;
  start: number;
  rh: ScoreEvent[];
  lh: ScoreEvent[];
  chords: { offset: number; symbol: string; confidence: number }[];
};

/** Beginner view: one row per bar, right-hand note names above left-hand note names. */
export function LetterNames({ score, clock, onSeek }: Props) {
  const bpb = score.meter.beats_per_bar || 4;
  const bars = useMemo<Bar[]>(() => {
    const count = Math.max(1, Math.ceil(scoreEndBeat(score) / bpb - 1e-9));
    const result: Bar[] = Array.from({ length: count }, (_, i) => ({
      index: i,
      start: i * bpb,
      rh: [],
      lh: [],
      chords: [],
    }));
    const barIndex = (beat: number) => Math.min(count - 1, Math.max(0, Math.floor(beat / bpb + 1e-9)));
    const sorted = [...score.events].sort((a, b) => a.start - b.start || (a.hand < b.hand ? 1 : -1));
    for (const e of sorted) result[barIndex(e.start)][e.hand].push(e);
    for (const c of score.chords) {
      const bar = result[barIndex(c.start)];
      bar.chords.push({ offset: c.start - bar.start, symbol: c.symbol, confidence: c.confidence });
    }
    return result;
  }, [score, bpb]);

  const [currentBar, setCurrentBar] = useState(-1);
  const currentRef = useRef(-1);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(
    () =>
      clock.subscribe((beat) => {
        const bar = beat <= 0 ? -1 : Math.floor(beat / bpb + 1e-9);
        if (bar !== currentRef.current) {
          currentRef.current = bar;
          setCurrentBar(bar);
        }
      }),
    [clock, bpb],
  );

  useEffect(() => {
    if (currentBar < 0) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-bar="${currentBar}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [currentBar]);

  return (
    <div className="letter-names">
      <p className="hint">
        Each card is one bar. The top row is the right hand, the bottom row the left hand. Notes that sound together are
        stacked. {onSeek ? "Click a bar to start playback there." : ""}
      </p>
      <ol className="bars" ref={listRef}>
        {bars.map((bar) => (
          <li
            key={bar.index}
            data-bar={bar.index}
            className={`bar-card${bar.index === currentBar ? " current" : ""}${onSeek ? " clickable" : ""}`}
            onClick={onSeek ? () => onSeek(bar.start) : undefined}
          >
            <div className="bar-head">
              <span className="bar-number">Bar {bar.index + 1}</span>
              <span className="bar-chords">
                {bar.chords.map((c, i) => (
                  <span
                    key={i}
                    className={`chord-chip${c.confidence < 0.5 ? " low" : ""}`}
                    title={`Beat ${Math.round((c.offset + 1) * 100) / 100}`}
                  >
                    {prettyChord(c.symbol)}
                  </span>
                ))}
              </span>
            </div>
            <HandRow label="RH" events={bar.rh} />
            <HandRow label="LH" events={bar.lh} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function HandRow({ label, events }: { label: string; events: ScoreEvent[] }) {
  return (
    <div className={`hand-row hand-${label.toLowerCase()}`}>
      <span className="hand-label">{label}</span>
      <span className="hand-notes">
        {events.length === 0 && <span className="rest">—</span>}
        {events.map((e, i) => (
          <span key={i} className="note-token" title={`${e.duration} beat${e.duration === 1 ? "" : "s"}`}>
            {[...e.names].reverse().map((n, j) => (
              <span key={j}>{prettyNoteName(n)}</span>
            ))}
          </span>
        ))}
      </span>
    </div>
  );
}
