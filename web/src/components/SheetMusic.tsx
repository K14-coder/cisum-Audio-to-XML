import { useEffect, useRef, useState } from "react";
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import type { PlaybackClock } from "../playback/usePlayback";

type Props = {
  musicxmlUrl: string;
  clock: PlaybackClock;
};

const xmlCache = new Map<string, Promise<string>>();

function fetchXml(url: string): Promise<string> {
  let pending = xmlCache.get(url);
  if (!pending) {
    pending = fetch(url, { credentials: "same-origin" }).then(async (res) => {
      if (!res.ok) throw new Error(`Couldn't load the sheet music (${res.status}).`);
      return res.text();
    });
    pending.catch(() => xmlCache.delete(url));
    xmlCache.set(url, pending);
  }
  return pending;
}

/** Renders MusicXML with OpenSheetMusicDisplay; the cursor follows the playback clock. */
export function SheetMusic({ musicxmlUrl, clock }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null);
  const cursorState = useRef({ lastBeat: 0, nextBeat: 0 });
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setError("");
    (async () => {
      try {
        const [{ OpenSheetMusicDisplay }, xml] = await Promise.all([
          import("opensheetmusicdisplay"),
          fetchXml(musicxmlUrl),
        ]);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = "";
        const osmd = new OpenSheetMusicDisplay(containerRef.current, {
          autoResize: true,
          backend: "svg",
          drawTitle: true,
          drawComposer: true,
          drawPartNames: false,
          followCursor: true,
        });
        await osmd.load(xml);
        if (cancelled) return;
        osmd.render();
        osmd.cursor.show();
        osmdRef.current = osmd;
        cursorState.current = { lastBeat: 0, nextBeat: nextTimestampBeat(osmd) };
        setState("ready");
        moveCursor(osmd, clock.getBeat());
      } catch (err) {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
      osmdRef.current = null;
    };
    // The clock is stable for a given player, so only a new file triggers a reload.
  }, [musicxmlUrl]);

  useEffect(
    () =>
      clock.subscribe((beat) => {
        const osmd = osmdRef.current;
        if (osmd) moveCursor(osmd, beat);
      }),
    [clock],
  );

  function moveCursor(osmd: OpenSheetMusicDisplay, beat: number) {
    const st = cursorState.current;
    const cursor = osmd.cursor;
    if (!cursor?.Iterator) return;
    if (beat < st.lastBeat - 1e-6) {
      cursor.reset();
      st.nextBeat = nextTimestampBeat(osmd);
    }
    st.lastBeat = beat;
    let guard = 0;
    while (beat + 1e-6 >= st.nextBeat && !cursor.Iterator.EndReached && guard++ < 5000) {
      cursor.next();
      st.nextBeat = nextTimestampBeat(osmd);
    }
  }

  return (
    <div className="sheet-paper">
      {state === "loading" && <div className="sheet-status">Rendering sheet music…</div>}
      {state === "error" && <div className="sheet-status error-text">{error}</div>}
      <div ref={containerRef} className="sheet-container" />
    </div>
  );
}

/** Beat position of the entry after the cursor (Infinity at the end). RealValue is in whole notes. */
function nextTimestampBeat(osmd: OpenSheetMusicDisplay): number {
  const it = osmd.cursor?.Iterator;
  if (!it || it.EndReached) return Infinity;
  const next = it.clone();
  next.moveToNext();
  if (next.EndReached) return Infinity;
  return next.currentTimeStamp.RealValue * 4;
}
