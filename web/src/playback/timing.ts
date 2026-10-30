export type TempoPoint = { beat: number; bpm: number };

type Segment = { beat: number; bpm: number; seconds: number };

/** Converts between beats and seconds for a piecewise-constant tempo map. */
export class TempoMap {
  private readonly segments: Segment[];

  constructor(tempo: TempoPoint[], fallbackBpm: number) {
    const valid = tempo
      .filter((p) => Number.isFinite(p.beat) && Number.isFinite(p.bpm) && p.bpm > 0)
      .sort((a, b) => a.beat - b.beat);
    const bpm0 = fallbackBpm > 0 ? fallbackBpm : 120;
    if (valid.length === 0) valid.push({ beat: 0, bpm: bpm0 });
    if (valid[0].beat > 0) valid.unshift({ beat: 0, bpm: valid[0].bpm });

    const segments: Segment[] = [];
    let seconds = 0;
    for (let i = 0; i < valid.length; i++) {
      if (i > 0) {
        const prev = valid[i - 1];
        seconds += ((valid[i].beat - prev.beat) * 60) / prev.bpm;
      }
      segments.push({ beat: valid[i].beat, bpm: valid[i].bpm, seconds });
    }
    this.segments = segments;
  }

  /** Seconds from beat 0 to `beat` (negative beats extrapolate with the first tempo). */
  secondsAt(beat: number): number {
    const seg = this.segmentForBeat(beat);
    return seg.seconds + ((beat - seg.beat) * 60) / seg.bpm;
  }

  beatAt(seconds: number): number {
    const segs = this.segments;
    let seg = segs[0];
    for (let i = segs.length - 1; i >= 0; i--) {
      if (seconds >= segs[i].seconds) {
        seg = segs[i];
        break;
      }
    }
    return seg.beat + ((seconds - seg.seconds) * seg.bpm) / 60;
  }

  private segmentForBeat(beat: number): Segment {
    const segs = this.segments;
    // Binary search for the last segment starting at or before `beat`.
    let lo = 0;
    let hi = segs.length - 1;
    if (beat <= segs[0].beat) return segs[0];
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (segs[mid].beat <= beat) lo = mid;
      else hi = mid - 1;
    }
    return segs[lo];
  }
}
