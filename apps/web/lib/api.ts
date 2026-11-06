// Typed client for the clip_star API.

export type StageId = "ingest" | "understand" | "moments" | "edit" | "package" | "publish" | "engage" | "measure" | "learn";
export type VideoStatus = "queued" | "processing" | "ready" | "failed" | "cancelled";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type ApiAsset = { kind: string; size_bytes: number; meta: Record<string, unknown> };

export type ApiVideo = {
  id: string;
  title: string;
  source_filename: string;
  status: VideoStatus;
  stage: StageId;
  progress: number;
  duration_s: number | null;
  size_bytes: number;
  meta: {
    probe?: { width: number; height: number; fps: number; has_audio: boolean };
    moments?: { engine: string; count: number; notes: string[] };
    edit?: { rendered: number; failed: number; skipped: number };
    understand?: { transcript_engine: string; language: string | null; words: number; segments: number; words_estimated: boolean; scenes: number; energy_peaks: number; notes: string[] };
  };
  error: string | null;
  created_at: string;
  updated_at: string;
  clips: number;
  active_job_id: string | null;
  assets?: ApiAsset[];
};

export type ApiJob = {
  id: string;
  kind: string;
  video_id: string | null;
  payload: { stage?: StageId } & Record<string, unknown>;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  progress: number;
  run_after: string;
  last_error: string | null;
  error_kind: "retryable" | "permanent" | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  result?: Record<string, unknown>;
  events?: { id: number; at: string; type: string; message: string; data: Record<string, unknown> }[];
};

export type ClipVariant = { id: string; caption_style: string; hook: string };
export type ClipRender = { key: string; duration_s: number; size_bytes: number; layout: { mode: "crop" | "fit" | "scale"; face_ratio: number } };

export type ApiClip = {
  id: string;
  video_id: string;
  title: string;
  start_s: number;
  end_s: number;
  score: number;
  reason: string;
  hook: string;
  status: "pending" | "approved" | "rejected";
  copy: Record<string, string>;
  variants: ClipVariant[];
  engine: string;
  meta: {
    features?: Record<string, number>;
    heuristic?: number;
    renders?: Record<string, ClipRender>;
    render_errors?: Record<string, string>;
  };
  created_at: string;
};

export type ApiHealth = {
  ok: boolean;
  database: boolean;
  storage_writable: boolean;
  storage_free_gb: number;
  ffmpeg: boolean;
  ffprobe: boolean;
  workers_online: number;
  queued_jobs: number;
  failed_jobs: number;
};

export type Transcript = {
  engine: string;
  language: string | null;
  duration: number;
  words_estimated: boolean;
  segments: { start: number; end: number; text: string; speaker: string | null }[];
};

export type Analysis = { scenes: { cuts: number[] }; energy: { window_s: number; values: number[]; peaks: number[] } };

// Where the API lives. "" = same origin (Docker setup: a reverse proxy sends /api to the backend).
// In local development set NEXT_PUBLIC_API_BASE=http://localhost:8000 (see apps/web/.env.development).
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { ...init, headers: { Accept: "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError(0, "Can't reach the clip_star server. Is the backend running?");
  }
  if (res.status === 204) return undefined as T;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
          : res.status === 502 || res.status === 504 || res.status === 500
            ? "The clip_star server isn't responding. Is the backend running?"
            : `Request failed (${res.status}).`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<ApiHealth>("/api/health"),
  videos: () => request<ApiVideo[]>("/api/videos"),
  video: (id: string) => request<ApiVideo>(`/api/videos/${id}`),
  transcript: (id: string) => request<Transcript>(`/api/videos/${id}/transcript`),
  analysis: (id: string) => request<Analysis>(`/api/videos/${id}/analysis`),
  retryVideo: (id: string) => request<ApiVideo>(`/api/videos/${id}/retry`, json("POST")),
  cancelVideo: (id: string) => request<ApiVideo>(`/api/videos/${id}/cancel`, json("POST")),
  deleteVideo: (id: string) => request<void>(`/api/videos/${id}`, json("DELETE")),
  jobs: (params: { status?: JobStatus; video_id?: string } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<ApiJob[]>(`/api/jobs${q.size ? `?${q}` : ""}`);
  },
  clips: (params: { video_id?: string; status?: ApiClip["status"] } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<ApiClip[]>(`/api/clips${q.size ? `?${q}` : ""}`);
  },
  updateClip: (id: string, body: Partial<Pick<ApiClip, "status" | "title" | "hook">>) => request<ApiClip>(`/api/clips/${id}`, json("PATCH", body)),
  rerenderClip: (id: string) => request<{ job_id: string }>(`/api/clips/${id}/render`, json("POST")),
  job: (id: string) => request<ApiJob>(`/api/jobs/${id}`),
  retryJob: (id: string) => request<ApiJob>(`/api/jobs/${id}/retry`, json("POST")),
  cancelJob: (id: string) => request<ApiJob>(`/api/jobs/${id}/cancel`, json("POST")),
};

/** Upload with progress (fetch can't report upload progress). */
export function uploadVideo(
  file: File,
  opts: { title?: string; captions?: File | null; onProgress?: (pct: number) => void },
): { promise: Promise<ApiVideo>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<ApiVideo>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.captions) form.append("captions", opts.captions);
    if (opts.title) form.append("title", opts.title);
    xhr.open("POST", `${API_BASE}/api/videos`);
    xhr.upload.onprogress = (e) => e.lengthComputable && opts.onProgress?.(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let body: { detail?: unknown } | ApiVideo | null = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status === 201) resolve(body as ApiVideo);
      else {
        const d = (body as { detail?: unknown } | null)?.detail;
        reject(new ApiError(xhr.status, typeof d === "string" ? d : `Upload failed (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed: can't reach the clip_star server."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

export const clipMediaUrl = (id: string, variant: string, key?: string) => `${API_BASE}/api/clips/${id}/media/${variant}${key ? `?v=${key}` : ""}`;
export const clipCoverUrl = (id: string, variant: string, key?: string) => `${API_BASE}/api/clips/${id}/cover/${variant}${key ? `?v=${key}` : ""}`;

export const isUuid = (s: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);

export function fmtDuration(s: number | null | undefined) {
  if (s == null) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
}

export function fmtBytes(b: number) {
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(1)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(0)} MB`;
  return `${Math.max(1, Math.round(b / 1024))} KB`;
}

export function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
