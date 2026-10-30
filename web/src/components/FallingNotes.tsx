import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ScoreJson } from "../api/types";
import { isBlackKey } from "../music/format";
import type { PlaybackClock } from "../playback/usePlayback";

type Props = {
  score: ScoreJson;
  clock: PlaybackClock;
};

type FallingNote = { pitch: number; start: number; end: number; hand: "rh" | "lh" };
type KeyRect = { pitch: number; x: number; w: number; black: boolean };

/** Seconds of music visible above the keyboard. */
const WINDOW_SECONDS = 3.5;

/** Canvas "falling notes" view: notes drop onto a keyboard in sync with playback. */
export function FallingNotes({ score, clock }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const { notes, low, high, barTimes } = useMemo(() => {
    const notes: FallingNote[] = [];
    let min = Infinity;
    let max = -Infinity;
    for (const e of score.events) {
      const start = clock.secondsAt(e.start);
      const end = clock.secondsAt(e.start + e.duration);
      for (const p of e.pitches) {
        notes.push({ pitch: p, start, end, hand: e.hand });
        min = Math.min(min, p);
        max = Math.max(max, p);
      }
    }
    if (!Number.isFinite(min)) {
      min = 48;
      max = 72;
    }
    let low = Math.floor(min / 12) * 12;
    let high = Math.ceil((max + 1) / 12) * 12 - 1;
    if (high - low < 23) high = low + 23;
    low = Math.max(21, low);
    high = Math.min(108, high);
    const bpb = score.meter.beats_per_bar || 4;
    const barTimes: number[] = [];
    for (let b = 0; b <= score.total_beats + bpb; b += bpb) barTimes.push(clock.secondsAt(b));
    notes.sort((a, b) => a.start - b.start);
    return { notes, low, high, barTimes };
  }, [score, clock]);

  const keys = useMemo(() => layoutKeys(low, high), [low, high]);

  const draw = useCallback(
    (beat: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      if (width <= 0 || height <= 0) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const css = getComputedStyle(canvas);
      const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
      const bg = color("--canvas-bg", "#111827");
      const rh = color("--rh", "#6366f1");
      const lh = color("--lh", "#f59e0b");
      const grid = color("--canvas-grid", "rgba(255,255,255,0.08)");

      const keyboardH = Math.min(130, Math.max(70, height * 0.22));
      const keyTop = height - keyboardH;
      const pxPerSec = keyTop / WINDOW_SECONDS;
      const now = clock.secondsAt(beat);
      const scaleX = width / keys.totalWidth;

      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, width, height);

      // Bar lines.
      ctx.strokeStyle = grid;
      ctx.lineWidth = 1;
      for (const t of barTimes) {
        const y = keyTop - (t - now) * pxPerSec;
        if (y < 0 || y > keyTop) continue;
        ctx.beginPath();
        ctx.moveTo(0, Math.round(y) + 0.5);
        ctx.lineTo(width, Math.round(y) + 0.5);
        ctx.stroke();
      }

      // Falling notes, plus which keys are down right now.
      const active = new Map<number, "rh" | "lh">();
      const horizon = now + WINDOW_SECONDS;
      for (const n of notes) {
        if (n.start > horizon) break;
        if (n.end < now) continue;
        if (n.start <= now) active.set(n.pitch, n.hand);
        const k = keys.byPitch.get(n.pitch);
        if (!k) continue;
        const yBottom = Math.min(keyTop, keyTop - (n.start - now) * pxPerSec);
        const yTop = Math.max(0, keyTop - (n.end - now) * pxPerSec);
        if (yBottom - yTop < 1) continue;
        const x = k.x * scaleX + 1;
        const w = Math.max(2, k.w * scaleX - 2);
        ctx.fillStyle = n.hand === "rh" ? rh : lh;
        roundRect(ctx, x, yTop, w, yBottom - yTop, Math.min(4, w / 2));
        ctx.fill();
      }

      // Keyboard: white keys first, then black keys on top.
      for (const pass of [false, true]) {
        for (const k of keys.list) {
          if (k.black !== pass) continue;
          const x = k.x * scaleX;
          const w = k.w * scaleX;
          const h = k.black ? keyboardH * 0.62 : keyboardH;
          const hand = active.get(k.pitch);
          ctx.fillStyle = hand ? (hand === "rh" ? rh : lh) : k.black ? "#1f2937" : "#f9fafb";
          ctx.fillRect(x + (k.black ? 0 : 0.5), keyTop, w - (k.black ? 0 : 1), h);
          if (!k.black) {
            ctx.strokeStyle = "rgba(0,0,0,0.25)";
            ctx.strokeRect(x + 0.5, keyTop + 0.5, w - 1, h - 1);
            if (k.pitch % 12 === 0 && w > 14) {
              ctx.fillStyle = hand ? "#fff" : "#6b7280";
              ctx.font = `${Math.min(11, w * 0.45)}px system-ui, sans-serif`;
              ctx.textAlign = "center";
              ctx.fillText(`C${Math.floor(k.pitch / 12) - 1}`, x + w / 2, keyTop + h - 6);
            }
          }
        }
      }
    },
    [notes, keys, barTimes, clock],
  );

  // Size the canvas to its container (and the device pixel ratio).
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = wrap.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      draw(clock.getBeat());
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [draw, clock]);

  useEffect(() => clock.subscribe(draw), [clock, draw]);

  // Redraw when the color scheme flips.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => draw(clock.getBeat());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [draw, clock]);

  return (
    <div className="falling-notes">
      <div className="falling-legend">
        <span className="legend-item">
          <span className="swatch swatch-rh" /> Right hand
        </span>
        <span className="legend-item">
          <span className="swatch swatch-lh" /> Left hand
        </span>
      </div>
      <div className="falling-wrap" ref={wrapRef}>
        <canvas ref={canvasRef} aria-label="Falling notes piano view" role="img" />
      </div>
    </div>
  );
}

function layoutKeys(low: number, high: number) {
  // Units: one white key = 1 wide; black keys are 0.6 wide, centered on the boundary.
  const list: KeyRect[] = [];
  let whiteIndex = 0;
  for (let p = low; p <= high; p++) {
    if (isBlackKey(p)) {
      list.push({ pitch: p, x: whiteIndex - 0.3, w: 0.6, black: true });
    } else {
      list.push({ pitch: p, x: whiteIndex, w: 1, black: false });
      whiteIndex++;
    }
  }
  const byPitch = new Map(list.map((k) => [k.pitch, k]));
  return { list, byPitch, totalWidth: Math.max(1, whiteIndex) };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.max(0, Math.min(r, h / 2, w / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}
