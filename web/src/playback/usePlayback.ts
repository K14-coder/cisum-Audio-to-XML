import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ScoreJson } from "../api/types";
import { loadInstrument, type Instrument } from "./piano";
import { TempoMap } from "./timing";

type ToneModule = typeof import("tone");

export type PlaybackStatus = "stopped" | "loading" | "playing" | "paused";

/** Shared "current beat" for every view (sheet cursor, letter names, falling notes). */
export type PlaybackClock = {
  getBeat: () => number;
  subscribe: (listener: (beat: number) => void) => () => void;
  /** Seconds in song time (tempo map, not scaled by the tempo slider). */
  secondsAt: (beat: number) => number;
};

export type Playback = {
  status: PlaybackStatus;
  instrument: Instrument["kind"] | null;
  tempoFactor: number;
  setTempoFactor: (factor: number) => void;
  play: () => void;
  pause: () => void;
  stop: () => void;
  seek: (beat: number) => void;
  clock: PlaybackClock;
};

const RH_VELOCITY = 0.72;
const LH_VELOCITY = 0.55;
const START_DELAY = 0.08;

let toneModule: ToneModule | null = null;
async function getTone(): Promise<ToneModule> {
  if (!toneModule) toneModule = await import("tone");
  return toneModule;
}

export function scoreEndBeat(score: ScoreJson | null): number {
  if (!score) return 0;
  let end = score.total_beats || 0;
  for (const e of score.events) end = Math.max(end, e.start + e.duration);
  return end;
}

export function usePlayback(score: ScoreJson | null): Playback {
  const [status, setStatusState] = useState<PlaybackStatus>("stopped");
  const [instrument, setInstrument] = useState<Instrument["kind"] | null>(null);
  const [tempoFactor, setTempoFactorState] = useState(1);

  const statusRef = useRef<PlaybackStatus>("stopped");
  const factorRef = useRef(1);
  const positionRef = useRef(0); // beat while stopped/paused
  const startBeatRef = useRef(0); // beat the transport started from
  const instrumentRef = useRef<Instrument | null>(null);
  const tokenRef = useRef(0); // invalidates in-flight play() calls
  const rafRef = useRef<number | null>(null);
  const listenersRef = useRef(new Set<(beat: number) => void>());
  const scoreRef = useRef<ScoreJson | null>(score);

  const tempoMap = useMemo(
    () => new TempoMap(score?.tempo ?? [], score?.bpm ?? 120),
    [score],
  );
  const tempoMapRef = useRef(tempoMap);
  tempoMapRef.current = tempoMap;
  scoreRef.current = score;

  const setStatus = useCallback((s: PlaybackStatus) => {
    statusRef.current = s;
    setStatusState(s);
  }, []);

  const getBeat = useCallback((): number => {
    if (statusRef.current !== "playing" || !toneModule) return positionRef.current;
    const Tone = toneModule;
    const transport = Tone.getTransport();
    const elapsed = Math.max(0, transport.getSecondsAtTime(Tone.immediate()));
    const map = tempoMapRef.current;
    return map.beatAt(map.secondsAt(startBeatRef.current) + elapsed * factorRef.current);
  }, []);

  const emit = useCallback((beat: number) => {
    for (const listener of listenersRef.current) listener(beat);
  }, []);

  const stopLoop = useCallback(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
  }, []);

  const haltTransport = useCallback(() => {
    if (!toneModule) return;
    const transport = toneModule.getTransport();
    transport.stop();
    transport.cancel(0);
    instrumentRef.current?.releaseAll();
  }, []);

  const stop = useCallback(() => {
    tokenRef.current++;
    stopLoop();
    haltTransport();
    positionRef.current = 0;
    setStatus("stopped");
    emit(0);
  }, [emit, haltTransport, setStatus, stopLoop]);

  const startLoop = useCallback(() => {
    stopLoop();
    const tick = () => {
      if (statusRef.current !== "playing") return;
      const beat = getBeat();
      emit(beat);
      if (beat >= scoreEndBeat(scoreRef.current) + 0.5) {
        stop();
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [emit, getBeat, stop, stopLoop]);

  const playFrom = useCallback(
    async (fromBeat: number) => {
      const current = scoreRef.current;
      if (!current) return;
      const token = ++tokenRef.current;
      setStatus("loading");
      const Tone = await getTone();
      await Tone.start();
      const inst = await loadInstrument(Tone);
      if (token !== tokenRef.current) return;
      instrumentRef.current = inst;
      setInstrument(inst.kind);

      const transport = Tone.getTransport();
      transport.stop();
      transport.cancel(0);
      transport.position = 0;

      const map = tempoMapRef.current;
      const factor = factorRef.current;
      const origin = map.secondsAt(fromBeat);
      for (const event of current.events) {
        if (event.start < fromBeat - 1e-6) continue;
        const at = (map.secondsAt(event.start) - origin) / factor;
        const dur = (map.secondsAt(event.start + event.duration) - map.secondsAt(event.start)) / factor;
        const velocity = event.hand === "rh" ? RH_VELOCITY : LH_VELOCITY;
        const pitches = event.pitches;
        transport.schedule((time) => inst.play(pitches, dur, time, velocity), at);
      }
      startBeatRef.current = fromBeat;
      positionRef.current = fromBeat;
      transport.start(`+${START_DELAY}`);
      setStatus("playing");
      startLoop();
    },
    [setStatus, startLoop],
  );

  const play = useCallback(() => {
    const s = statusRef.current;
    if (s === "playing" || s === "loading") return;
    if (s === "paused" && toneModule) {
      toneModule.getTransport().start();
      setStatus("playing");
      startLoop();
      return;
    }
    const end = scoreEndBeat(scoreRef.current);
    const from = positionRef.current >= end ? 0 : positionRef.current;
    void playFrom(from);
  }, [playFrom, setStatus, startLoop]);

  const pause = useCallback(() => {
    if (statusRef.current !== "playing" || !toneModule) return;
    const beat = getBeat();
    toneModule.getTransport().pause();
    instrumentRef.current?.releaseAll();
    stopLoop();
    positionRef.current = beat;
    setStatus("paused");
    emit(beat);
  }, [emit, getBeat, setStatus, stopLoop]);

  const seek = useCallback(
    (beat: number) => {
      const target = Math.max(0, Math.min(beat, scoreEndBeat(scoreRef.current)));
      const wasPlaying = statusRef.current === "playing" || statusRef.current === "loading";
      tokenRef.current++;
      stopLoop();
      haltTransport();
      positionRef.current = target;
      if (wasPlaying) {
        void playFrom(target);
      } else {
        setStatus("stopped");
        emit(target);
      }
    },
    [emit, haltTransport, playFrom, setStatus, stopLoop],
  );

  const setTempoFactor = useCallback(
    (factor: number) => {
      const f = Math.max(0.25, Math.min(2, factor));
      const beat = getBeat();
      factorRef.current = f;
      setTempoFactorState(f);
      const s = statusRef.current;
      if (s === "playing") {
        // Reschedule from the current position so the new tempo applies immediately.
        seek(beat);
      } else if (s === "paused") {
        haltTransport();
        positionRef.current = beat;
        setStatus("stopped");
      }
    },
    [getBeat, haltTransport, seek, setStatus],
  );

  // A new score (different level/transposition) starts from the top.
  useEffect(() => {
    stop();
  }, [score, stop]);

  useEffect(
    () => () => {
      tokenRef.current++;
      stopLoop();
      haltTransport();
    },
    [haltTransport, stopLoop],
  );

  const clock = useMemo<PlaybackClock>(
    () => ({
      getBeat,
      subscribe: (listener) => {
        listenersRef.current.add(listener);
        return () => {
          listenersRef.current.delete(listener);
        };
      },
      secondsAt: (beat: number) => tempoMapRef.current.secondsAt(beat),
    }),
    [getBeat],
  );

  return { status, instrument, tempoFactor, setTempoFactor, play, pause, stop, seek, clock };
}
