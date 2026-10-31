import { useEffect, useMemo, useState } from "react";
import { ApiError, api, errorMessage } from "../api/client";
import type { Analysis, KeySegment, Meter } from "../api/types";
import { CHORD_SYMBOL_RE, TONICS, barOf, formatBarBeat } from "../music/format";
import { Modal } from "./Modal";

type Props = {
  songId: string;
  onClose: () => void;
  onSaved: (analysis: Analysis) => void;
};

type EditableChord = {
  id: number;
  start: number;
  end: number;
  symbol: string;
  confidence: number;
  edited: boolean;
};

type EditableKey = { start: number; tonic: string; mode: "major" | "minor" };

let nextId = 1;

/** Edit detected chords (and the key) in the song's original key. Saving regenerates every level. */
export function ChordEditor({ songId, onClose, onSaved }: Props) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [chords, setChords] = useState<EditableChord[]>([]);
  const [keys, setKeys] = useState<EditableKey[]>([]);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getAnalysis(songId)
      .then((a) => {
        if (cancelled) return;
        setAnalysis(a);
        setChords(
          [...a.chords]
            .sort((x, y) => x.start - y.start)
            .map((c) => ({
              id: nextId++,
              start: c.start,
              end: c.end,
              symbol: c.symbol,
              confidence: c.confidence,
              edited: Boolean(c.edited),
            })),
        );
        setKeys(a.key.map((k: KeySegment) => ({ start: k.start, tonic: k.tonic, mode: k.mode })));
      })
      .catch((err) => !cancelled && setLoadError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [songId]);

  const meter: Meter = analysis?.meter ?? { beats_per_bar: 4, beat_unit: 4 };
  const keysChanged = useMemo(() => {
    if (!analysis) return false;
    if (analysis.key.length !== keys.length) return true;
    return analysis.key.some((k, i) => k.tonic !== keys[i].tonic || k.mode !== keys[i].mode);
  }, [analysis, keys]);

  const updateChord = (id: number, symbol: string) => {
    setChords((list) => list.map((c) => (c.id === id ? { ...c, symbol, edited: true } : c)));
    setDirty(true);
  };

  const split = (index: number) => {
    setChords((list) => {
      const c = list[index];
      const length = c.end - c.start;
      if (length <= 0.5) return list;
      const at = length >= 2 ? c.start + Math.floor(length / 2) : c.start + length / 2;
      const first = { ...c, end: at, edited: true };
      const second = { ...c, id: nextId++, start: at, edited: true };
      return [...list.slice(0, index), first, second, ...list.slice(index + 1)];
    });
    setDirty(true);
  };

  const mergeWithNext = (index: number) => {
    setChords((list) => {
      if (index >= list.length - 1) return list;
      const merged = { ...list[index], end: list[index + 1].end, edited: true };
      return [...list.slice(0, index), merged, ...list.slice(index + 2)];
    });
    setDirty(true);
  };

  const updateKey = (index: number, patch: Partial<EditableKey>) => {
    setKeys((list) => list.map((k, i) => (i === index ? { ...k, ...patch } : k)));
  };

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      const body: Parameters<typeof api.editAnalysis>[1] = {};
      if (dirty) body.chords = chords.map((c) => ({ start: c.start, end: c.end, symbol: c.symbol.trim() }));
      if (keysChanged) body.key = keys;
      if (!body.chords && !body.key) {
        onClose();
        return;
      }
      const updated = await api.editAnalysis(songId, body);
      onSaved(updated);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const invalidCount = chords.filter((c) => !CHORD_SYMBOL_RE.test(c.symbol.trim())).length;

  return (
    <Modal
      title="Edit chords"
      onClose={onClose}
      wide
      footer={
        <>
          {invalidCount > 0 && (
            <span className="warning-text">
              {invalidCount} symbol{invalidCount === 1 ? " looks" : "s look"} unusual — the server will check.
            </span>
          )}
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="button primary"
            onClick={save}
            disabled={saving || !analysis || (!dirty && !keysChanged)}
          >
            {saving ? "Saving…" : "Save & regenerate"}
          </button>
        </>
      }
    >
      {loadError && <p className="error-text">{loadError}</p>}
      {!analysis && !loadError && <p>Loading the analysis…</p>}
      {analysis && (
        <>
          <p className="hint">
            Chords are shown in the song's original key, whatever transposition you're viewing. Low-confidence chords are
            highlighted. Use symbols like <code>G</code>, <code>Em7</code>, <code>D/F#</code>, <code>Bbmaj7</code>,{" "}
            <code>Csus4</code>, or <code>N</code> for no chord.
          </p>
          {saveError && (
            <p className="error-text" role="alert">
              {saveError}
            </p>
          )}

          <fieldset className="key-editor">
            <legend>Key</legend>
            {keys.map((k, i) => (
              <div key={i} className="key-row">
                <span className="key-at">{keys.length > 1 ? `From bar ${barOf(k.start, meter)}` : "Whole song"}</span>
                <select
                  value={k.tonic}
                  onChange={(e) => updateKey(i, { tonic: e.target.value })}
                  aria-label="Key tonic"
                >
                  {!TONICS.includes(k.tonic) && <option value={k.tonic}>{k.tonic}</option>}
                  {TONICS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <select
                  value={k.mode}
                  onChange={(e) => updateKey(i, { mode: e.target.value as "major" | "minor" })}
                  aria-label="Key mode"
                >
                  <option value="major">major</option>
                  <option value="minor">minor</option>
                </select>
              </div>
            ))}
          </fieldset>

          <ol className="chord-list">
            {chords.map((c, i) => {
              const newBar = i === 0 || barOf(chords[i - 1].start, meter) !== barOf(c.start, meter);
              const valid = CHORD_SYMBOL_RE.test(c.symbol.trim());
              const mentioned = saveError && c.symbol.trim() && saveError.includes(`'${c.symbol.trim()}'`);
              const length = Math.round((c.end - c.start) * 100) / 100;
              return (
                <li
                  key={c.id}
                  className={`chord-row${newBar ? " new-bar" : ""}${c.confidence < 0.5 && !c.edited ? " low" : ""}${
                    !valid || mentioned ? " invalid" : ""
                  }`}
                >
                  <span className="chord-pos">{formatBarBeat(c.start, meter)}</span>
                  <input
                    className="chord-input"
                    value={c.symbol}
                    onChange={(e) => updateChord(c.id, e.target.value)}
                    aria-label={`Chord at ${formatBarBeat(c.start, meter)}`}
                    spellCheck={false}
                    autoCapitalize="off"
                  />
                  <span className="chord-len">
                    {length} beat{length === 1 ? "" : "s"}
                  </span>
                  <span className="chord-conf" title="Detection confidence">
                    {c.edited ? "edited" : `${Math.round(c.confidence * 100)}%`}
                  </span>
                  <span className="chord-actions">
                    <button
                      type="button"
                      className="button small"
                      onClick={() => split(i)}
                      disabled={c.end - c.start <= 0.5}
                      title="Split this chord in two"
                    >
                      Split
                    </button>
                    <button
                      type="button"
                      className="button small"
                      onClick={() => mergeWithNext(i)}
                      disabled={i >= chords.length - 1}
                      title="Merge with the next chord"
                    >
                      Merge ↓
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </Modal>
  );
}
