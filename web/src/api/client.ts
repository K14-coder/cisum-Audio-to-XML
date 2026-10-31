import type {
  Analysis,
  AnalysisEdit,
  Arrangement,
  AuthResponse,
  Level,
  Report,
  ReportCreate,
  ReportStatus,
  RightsNotice,
  Share,
  SharedArrangement,
  Song,
  SongEvent,
  TransposeRequest,
  UploadTicket,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** Turns FastAPI's `detail` (a string or a list of validation errors) into one readable message. */
export function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && "msg" in d) {
          const item = d as { msg: unknown; loc?: unknown };
          const loc = Array.isArray(item.loc) ? item.loc.filter((l) => l !== "body").join(".") : "";
          return loc ? `${loc}: ${String(item.msg)}` : String(item.msg);
        }
        return JSON.stringify(d);
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

let unauthorizedHandler: (() => void) | null = null;

/** Called when an authenticated request comes back 401 (session expired or logged out elsewhere). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

type RequestOptions = {
  body?: unknown;
  /** Don't trigger the global 401 handler (login form, /me probe, public pages). */
  quiet401?: boolean;
  signal?: AbortSignal;
};

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = undefined;
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "detail" in data) {
      detail = (data as { detail: unknown }).detail;
    }
  } catch {
    // Not JSON (e.g. a proxy error page).
  }
  const fallback =
    res.status === 413
      ? "That file is too large."
      : res.status >= 500
        ? "The server had a problem. Please try again."
        : res.statusText || `Request failed (${res.status})`;
  return new ApiError(res.status, formatDetail(detail, fallback), detail);
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET" && method !== "HEAD") headers["X-Cisum-CSRF"] = "1";
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body, credentials: "same-origin", signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.", null);
  }
  if (!res.ok) {
    const error = await parseError(res);
    if (res.status === 401 && !opts.quiet401) unauthorizedHandler?.();
    throw error;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const enc = encodeURIComponent;

// ---------------------------------------------------------------- auth

export const api = {
  register: (email: string, password: string) =>
    request<AuthResponse>("POST", "/api/auth/register", { body: { email, password }, quiet401: true }),
  login: (email: string, password: string) =>
    request<AuthResponse>("POST", "/api/auth/login", { body: { email, password }, quiet401: true }),
  logout: () => request<void>("POST", "/api/auth/logout", { quiet401: true }),
  me: () => request<User>("GET", "/api/auth/me", { quiet401: true }),

  // -------------------------------------------------------------- legal
  rightsNotice: () => request<RightsNotice>("GET", "/api/legal/rights-notice", { quiet401: true }),

  // -------------------------------------------------------------- uploads
  createUpload: (body: {
    filename: string;
    content_type: string;
    size_bytes: number;
    rights_confirmed: true;
    rights_notice_version: string;
  }) => request<UploadTicket>("POST", "/api/uploads", { body }),
  completeUpload: (uploadId: string, body: { title: string; artist?: string }) =>
    request<Song>("POST", `/api/uploads/${enc(uploadId)}/complete`, { body }),

  // -------------------------------------------------------------- songs
  listSongs: () => request<{ songs: Song[] }>("GET", "/api/songs"),
  getSong: (id: string) => request<Song>("GET", `/api/songs/${enc(id)}`),
  updateSong: (id: string, body: { title?: string; artist?: string | null }) =>
    request<Song>("PATCH", `/api/songs/${enc(id)}`, { body }),
  deleteSong: (id: string) => request<void>("DELETE", `/api/songs/${enc(id)}`),
  getAnalysis: (id: string) => request<Analysis>("GET", `/api/songs/${enc(id)}/analysis`),
  editAnalysis: (id: string, body: AnalysisEdit) =>
    request<Analysis>("PATCH", `/api/songs/${enc(id)}/analysis`, { body }),
  getArrangement: (id: string, level: Level, transpose: TransposeRequest, signal?: AbortSignal) =>
    request<Arrangement>(
      "GET",
      `/api/songs/${enc(id)}/arrangement?level=${enc(level)}&transpose=${enc(String(transpose))}`,
      { signal },
    ),

  // -------------------------------------------------------------- shares
  createShare: (songId: string, level: Level, transpose: number) =>
    request<Share>("POST", `/api/songs/${enc(songId)}/shares`, { body: { level, transpose } }),
  listShares: (songId: string) => request<{ shares: Share[] }>("GET", `/api/songs/${enc(songId)}/shares`),
  revokeShare: (slug: string) => request<void>("DELETE", `/api/shares/${enc(slug)}`),

  // -------------------------------------------------------------- public
  getSharedArrangement: (slug: string) =>
    request<SharedArrangement>("GET", `/api/public/shares/${enc(slug)}`, { quiet401: true }),
  reportShare: (slug: string, body: ReportCreate) =>
    request<{ id: string; message: string }>("POST", `/api/public/shares/${enc(slug)}/reports`, {
      body,
      quiet401: true,
    }),

  // -------------------------------------------------------------- admin
  listReports: (status: ReportStatus | "all") =>
    request<{ reports: Report[] }>("GET", `/api/admin/reports?status=${enc(status)}`),
  resolveReport: (id: string, action: "uphold" | "reject", note?: string) =>
    request<Report>("POST", `/api/admin/reports/${enc(id)}/resolve`, {
      body: note ? { action, note } : { action },
    }),
};

// ---------------------------------------------------------------- file upload with progress

/** Sends the file bytes to the upload ticket's URL, reporting progress (0..1). */
export function uploadBytes(
  ticket: UploadTicket,
  file: Blob,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const { url, method, headers } = ticket.upload;
    const relative = url.startsWith("/") && !url.startsWith("//");
    xhr.open(method, url);
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    if (relative) {
      xhr.setRequestHeader("X-Cisum-CSRF", "1");
      xhr.withCredentials = true;
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve();
        return;
      }
      let detail: unknown = undefined;
      try {
        const data: unknown = JSON.parse(xhr.responseText);
        if (data && typeof data === "object" && "detail" in data) detail = (data as { detail: unknown }).detail;
      } catch {
        // S3 returns XML errors; ignore the body.
      }
      const fallback = xhr.status === 413 ? "That file is too large." : `Upload failed (${xhr.status}).`;
      reject(new ApiError(xhr.status, formatDetail(detail, fallback), detail));
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection.", null));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled.", null));
    xhr.send(file);
  });
}

// ---------------------------------------------------------------- progress stream

/**
 * Reads the song's server-sent events with fetch (so the session cookie is sent).
 * Resolves when the stream ends normally; rejects on network/HTTP errors so the caller can fall back to polling.
 */
export async function streamSongEvents(
  songId: string,
  onEvent: (event: SongEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/songs/${enc(songId)}/events`, {
    headers: { Accept: "text/event-stream" },
    credentials: "same-origin",
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) unauthorizedHandler?.();
    throw await parseError(res);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];

  const dispatch = () => {
    if (dataLines.length && (eventName === "status" || eventName === "message")) {
      try {
        onEvent(JSON.parse(dataLines.join("\n")) as SongEvent);
      } catch {
        // Ignore malformed messages.
      }
    }
    eventName = "message";
    dataLines = [];
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      let line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line === "") dispatch();
      else if (line.startsWith(":")) continue;
      else if (line.startsWith("event:")) eventName = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  dispatch();
}
