import { PIANO_SAMPLES_URL, SAMPLE_LOAD_TIMEOUT_MS } from "../config";

type ToneModule = typeof import("tone");

export type Instrument = {
  kind: "piano" | "synth";
  play: (midi: number[], durationSec: number, time: number, velocity: number) => void;
  releaseAll: () => void;
};

/** Salamander sample files, one every minor third from A0 to C8 (tonejs naming: "Ds1" = D#1). */
function sampleMap(): Record<string, string> {
  const urls: Record<string, string> = { A0: "A0.mp3" };
  for (let octave = 1; octave <= 7; octave++) {
    urls[`C${octave}`] = `C${octave}.mp3`;
    urls[`D#${octave}`] = `Ds${octave}.mp3`;
    urls[`F#${octave}`] = `Fs${octave}.mp3`;
    urls[`A${octave}`] = `A${octave}.mp3`;
  }
  urls.C8 = "C8.mp3";
  return urls;
}

let instrumentPromise: Promise<Instrument> | null = null;

function makeSynth(Tone: ToneModule): Instrument {
  const synth = new Tone.PolySynth(Tone.Synth, {
    oscillator: { type: "triangle" },
    envelope: { attack: 0.005, decay: 0.4, sustain: 0.25, release: 0.9 },
  }).toDestination();
  synth.volume.value = -10;
  return {
    kind: "synth",
    play: (midi, dur, time, velocity) => {
      const notes = midi.map((m) => Tone.Frequency(m, "midi").toNote());
      synth.triggerAttackRelease(notes, Math.max(0.05, dur), time, velocity);
    },
    releaseAll: () => {
      synth.releaseAll();
    },
  };
}

function loadSampler(Tone: ToneModule): Promise<Instrument> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("Piano samples took too long to load."));
      }
    }, SAMPLE_LOAD_TIMEOUT_MS);
    try {
      const sampler = new Tone.Sampler({
        urls: sampleMap(),
        baseUrl: PIANO_SAMPLES_URL,
        release: 1.2,
        onload: () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          resolve({
            kind: "piano",
            play: (midi, dur, time, velocity) => {
              const notes = midi.map((m) => Tone.Frequency(m, "midi").toNote());
              sampler.triggerAttackRelease(notes, Math.max(0.05, dur), time, velocity);
            },
            releaseAll: () => {
              sampler.releaseAll();
            },
          });
        },
        onerror: (error: Error) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          reject(error);
        },
      }).toDestination();
    } catch (err) {
      settled = true;
      window.clearTimeout(timer);
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}

/** Loads the sampled piano once; falls back to a synthesizer if the samples can't be fetched in time. */
export function loadInstrument(Tone: ToneModule): Promise<Instrument> {
  if (!instrumentPromise) {
    instrumentPromise = loadSampler(Tone).catch((err: unknown) => {
      console.warn("Falling back to synthesizer playback:", err);
      return makeSynth(Tone);
    });
  }
  return instrumentPromise;
}
