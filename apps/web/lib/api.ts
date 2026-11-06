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
    package?: { engine: string; clips: number; notes: string[] };
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

export type PlatformId = "youtube" | "instagram" | "facebook" | "tiktok" | "x" | "linkedin" | "threads" | "pinterest";
export type PlatformCopy = { title: string; caption: string; hashtags: string[] };
export type Preflight = { ok: boolean; problems: string[]; chars: number; limit: number };

// Mirrors backend/clipstar/pipeline/package.py PLATFORM_RULES (shown in the editor; the server re-checks).
export const PLATFORM_RULES: Record<PlatformId, { label: string; needsTitle: boolean; titleMax: number; captionMax: number; hashtagsMax: number; maxDuration: number }> = {
  youtube: { label: "YouTube Shorts", needsTitle: true, titleMax: 100, captionMax: 5000, hashtagsMax: 3, maxDuration: 180 },
  instagram: { label: "Instagram Reels", needsTitle: false, titleMax: 0, captionMax: 2200, hashtagsMax: 5, maxDuration: 180 },
  tiktok: { label: "TikTok", needsTitle: false, titleMax: 0, captionMax: 2200, hashtagsMax: 5, maxDuration: 600 },
  facebook: { label: "Facebook", needsTitle: false, titleMax: 0, captionMax: 2000, hashtagsMax: 3, maxDuration: 180 },
  x: { label: "X", needsTitle: false, titleMax: 0, captionMax: 280, hashtagsMax: 2, maxDuration: 140 },
  linkedin: { label: "LinkedIn", needsTitle: false, titleMax: 0, captionMax: 3000, hashtagsMax: 3, maxDuration: 600 },
  threads: { label: "Threads", needsTitle: false, titleMax: 0, captionMax: 500, hashtagsMax: 1, maxDuration: 300 },
  pinterest: { label: "Pinterest", needsTitle: true, titleMax: 100, captionMax: 500, hashtagsMax: 5, maxDuration: 300 },
};

export function composeCopy(c: PlatformCopy) {
  const tags = c.hashtags.map((h) => `#${h}`).join(" ");
  return tags ? `${c.caption.trim()}\n\n${tags}`.trim() : c.caption.trim();
}

export type WorkspaceSettings = {
  niche?: string;
  voice?: string;
  audience?: string;
  banned_topics?: string[];
  hashtags?: string[];
  cta?: string;
  clip_min_s?: number;
  clip_max_s?: number;
  clip_target_s?: number;
  max_clips?: number;
  variants?: 1 | 2;
  caption_style?: "bold-pop" | "clean";
  platforms?: PlatformId[];
  auto_approve_score?: number | null;
  spacing_minutes?: number;
  duplicate_warning_accounts?: number;
  quiet_hours?: boolean;
  auto_reply_categories?: ("praise" | "lead")[];
  auto_hide_spam?: boolean;
  replies_per_hour?: number;
  lead_reply?: string;
  comment_sync_minutes?: number;
};
export type ApiWorkspace = { id: string; name: string; settings: WorkspaceSettings };
export type ApiEngine = { id: string; stage: StageId; name: string; kind: "free" | "connector"; description: string; ok: boolean; message: string; selected: boolean; estimate: string | null };

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
  copy: Partial<Record<PlatformId, PlatformCopy>>;
  variants: ClipVariant[];
  engine: string;
  meta: {
    features?: Record<string, number>;
    heuristic?: number;
    renders?: Record<string, ClipRender>;
    render_errors?: Record<string, string>;
    words?: { start: number; end: number; word: string }[];
    preflight?: Partial<Record<PlatformId, Preflight>>;
    copy_edited?: boolean;
    copy_engine?: string;
    auto_approved?: boolean;
  };
  created_at: string;
};

export type ApiAccount = {
  id: string;
  platform: PlatformId;
  handle: string;
  group_name: string;
  status: "connected" | "reconnect" | "paused" | "disconnected";
  timezone: string;
  language: string;
  daily_cap: number;
  posting_start: string;
  posting_end: string;
  connection: "oauth" | "simulated";
  remote_id: string | null;
  token_expires_at: string | null;
  options: { board_id?: string; boards?: { id: string; name: string }[]; privacy?: string; simulate?: string; username?: string };
  last_error: string | null;
  created_at: string;
};
export type AccountStats = Record<string, { posted_24h: number; waiting: number; problems: number; published: number; next_at: string | null }>;
export type ApiPlatformApp = { platform: PlatformId; label: string; configured: boolean; client_id: string | null; client_id_label: string; redirect_uri: string; scopes: string[]; docs_url: string };
export type PostStatus = "held" | "scheduled" | "publishing" | "published" | "failed" | "unknown" | "cancelled";
export type ApiPost = {
  id: string;
  batch_id: string;
  account_id: string;
  clip_id: string;
  variant: string;
  caption: string;
  scheduled_at: string;
  status: PostStatus;
  remote_id: string | null;
  remote_url: string | null;
  attempts: number;
  last_error: string | null;
  published_at: string | null;
  metrics: PostMetrics;
};
export type PostMetrics = { views?: number; likes?: number; comments?: number; shares?: number; saves?: number; watch_pct?: number; avg_watch_s?: number; follows?: number; hours?: number; updated_at?: string; _error?: string };
export type PeriodTotals = { posts: number; measured: number; practice_posts: number; views: number; likes: number; comments: number; shares: number; saves: number; follows: number; watch_pct: number | null; follower_gain?: number | null };
export type TopPost = { post_id: string; clip_id: string; clip_title: string; video_id: string; variant: string; account_id: string; account: string; platform: PlatformId; practice: boolean; published_at: string | null; remote_url: string | null; views: number | null; likes: number | null; comments: number | null; shares: number | null; watch_pct: number | null; follows: number | null; rel: number | null };
export type AnalyticsOverview = {
  days: number;
  start: string;
  end: string;
  totals: PeriodTotals;
  previous: PeriodTotals;
  series: { date: string; views: number; posts: number }[];
  by_platform: { platform: PlatformId; posts: number; views: number }[];
  by_account: { account_id: string; handle: string; platform: PlatformId; practice: boolean; posts: number; views: number }[];
  top_posts: TopPost[];
  scheduled: number;
  practice_only: boolean;
};
export type Insight = { kind: "do" | "avoid"; dimension: string; title: string; body: string; n: number; lift: number };
export type LearnedModel = { active: boolean; reason?: string; n: number; clips: number; trained_at: string; corr?: number; baseline_corr?: number; weights?: Record<string, number> };
export type LearnView = {
  n: number;
  practice: number;
  min_n: number;
  insights: Insight[];
  ideas: { topic: string; questions: number; body: string }[];
  reclip: { video_id: string; title: string; reason: string }[];
  model: LearnedModel | null;
};
export type ReportSummary = { id: string; period_start: string; period_end: string; summary: string; created_at: string };
export type ApiReport = ReportSummary & { data: { overview: AnalyticsOverview; insights: Insight[]; ideas: LearnView["ideas"]; reclip: LearnView["reclip"]; model: LearnedModel; n: number } };
export type AccountMetricsView = { supported: boolean; note: string | null; followers: { at: string; followers: number | null }[]; updated_at: string | null; overview: AnalyticsOverview };
export type ApiBatch = {
  id: string;
  name: string;
  origin: string;
  warnings: string[];
  status: "awaiting" | "running" | "disabled" | "finished" | "cancelled";
  variations: string;
  approved_at: string | null;
  created_at: string;
  posts: number;
  posted: number;
  accounts: number;
  clips: number;
};
export type BatchBody = { name: string; clip_ids: string[]; account_ids: string[]; groups: string[]; start_at: string; spacing_minutes?: number; variations: "off" | "ab" };
export type BatchPreview = { posts: { account_id: string; handle: string; platform: PlatformId; timezone: string; clip_id: string; clip: string; variant: string; at: string }[]; warnings: string[]; skipped: string[] };
export type ApiRule = { id: string; name: string; enabled: boolean; config: { min_score?: number; groups?: string[]; platforms?: PlatformId[]; start_delay_minutes?: number; variations?: "off" | "ab"; spacing_minutes?: number }; created_at: string };

export type CommentCategory = "question" | "lead" | "praise" | "critical" | "spam" | "other";
export type ApiComment = {
  id: string;
  account_id: string;
  handle: string;
  platform: PlatformId;
  practice: boolean;
  post_id: string | null;
  clip_title: string | null;
  author: string;
  message: string;
  commented_at: string | null;
  category: CommentCategory;
  category_by: string;
  state: "open" | "done";
  draft: string;
  draft_by: string;
  reply_text: string;
  reply_status: "none" | "queued" | "sending" | "sent" | "failed" | "unknown";
  reply_auto: boolean;
  replied_at: string | null;
  hidden: boolean;
  error: string | null;
  max_chars: number;
};
export type CommentSummary = {
  open: Partial<Record<CommentCategory, number>>;
  needs_attention: number;
  accounts: { id: string; handle: string; platform: PlatformId; supported: boolean; note: string | null; synced_at: string | null }[];
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
  clip: (id: string) => request<ApiClip>(`/api/clips/${id}`),
  updateClip: (
    id: string,
    body: Partial<Pick<ApiClip, "status" | "title" | "hook" | "start_s" | "end_s" | "variants">> & { copy?: Partial<Record<PlatformId, Partial<PlatformCopy>>> },
  ) => request<ApiClip>(`/api/clips/${id}`, json("PATCH", body)),
  replaceInTranscript: (videoId: string, find: string, replace: string) =>
    request<{ replaced: number; clips_changed: number }>(`/api/videos/${videoId}/transcript/replace`, json("POST", { find, replace })),
  accounts: () => request<ApiAccount[]>("/api/accounts"),
  accountStats: () => request<AccountStats>("/api/accounts/stats"),
  createAccount: (body: Partial<ApiAccount> & { platform: PlatformId; handle: string }) => request<ApiAccount>("/api/accounts", json("POST", body)),
  updateAccount: (id: string, body: Partial<Omit<ApiAccount, "options">> & { options?: Partial<Pick<ApiAccount["options"], "board_id" | "privacy" | "simulate">> }) =>
    request<ApiAccount>(`/api/accounts/${id}`, json("PATCH", body)),
  deleteAccount: (id: string) => request<void>(`/api/accounts/${id}`, json("DELETE")),
  platforms: () => request<ApiPlatformApp[]>("/api/platforms"),
  savePlatformApp: (platform: PlatformId, client_id: string, client_secret: string) => request<{ ok: boolean }>(`/api/platforms/${platform}/app`, json("PUT", { client_id, client_secret })),
  deletePlatformApp: (platform: PlatformId) => request<void>(`/api/platforms/${platform}/app`, json("DELETE")),
  startConnect: (platform: PlatformId, group_name: string) => request<{ authorize_url: string }>(`/api/connect/${platform}/start`, json("POST", { group_name })),
  batches: () => request<ApiBatch[]>("/api/batches"),
  previewBatch: (body: BatchBody) => request<BatchPreview>("/api/batches/preview", json("POST", body)),
  createBatch: (body: BatchBody) => request<ApiBatch>("/api/batches", json("POST", body)),
  batchAction: (id: string, action: "approve" | "disable" | "enable" | "cancel") => request<ApiBatch>(`/api/batches/${id}/${action}`, json("POST")),
  posts: (params: { account_id?: string; platform?: string; group?: string; clip_id?: string; batch_id?: string; status?: string; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== "all").map(([k, v]) => [k, String(v)]));
    return request<ApiPost[]>(`/api/posts${q.size ? `?${q}` : ""}`);
  },
  postAction: (id: string, action: "retry" | "cancel" | "mark-published") => request<ApiPost>(`/api/posts/${id}/${action}`, json("POST")),
  rules: () => request<ApiRule[]>("/api/rules"),
  createRule: (body: Omit<ApiRule, "id" | "created_at">) => request<ApiRule>("/api/rules", json("POST", body)),
  updateRule: (id: string, body: Partial<Omit<ApiRule, "id" | "created_at">>) => request<ApiRule>(`/api/rules/${id}`, json("PATCH", body)),
  deleteRule: (id: string) => request<void>(`/api/rules/${id}`, json("DELETE")),
  comments: (params: { state?: "open" | "done" | "all"; category?: string; account_id?: string } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<ApiComment[]>(`/api/comments${q.size ? `?${q}` : ""}`);
  },
  commentSummary: () => request<CommentSummary>("/api/comments/summary"),
  updateComment: (id: string, body: { category?: CommentCategory; draft?: string }) => request<ApiComment>(`/api/comments/${id}`, json("PATCH", body)),
  sendReply: (id: string, text: string, confirm_resend = false) => request<ApiComment>(`/api/comments/${id}/send`, json("POST", { text, confirm_resend })),
  commentAction: (id: string, action: "skip" | "reopen" | "hide" | "unhide" | "mark-sent") => request<ApiComment>(`/api/comments/${id}/${action}`, json("POST")),
  syncComments: () => request<{ queued: number }>("/api/comments/sync", json("POST")),
  workspace: () => request<ApiWorkspace>("/api/workspace"),
  analytics: (days = 7, account_id?: string) => request<AnalyticsOverview>(`/api/analytics/overview?days=${days}${account_id ? `&account_id=${account_id}` : ""}`),
  learn: () => request<LearnView>("/api/analytics/learn"),
  train: () => request<LearnedModel>("/api/learn/train", json("POST")),
  reports: () => request<ReportSummary[]>("/api/reports"),
  report: (id: string) => request<ApiReport>(`/api/reports/${id}`),
  makeReport: () => request<ApiReport>("/api/reports", json("POST")),
  accountMetrics: (id: string, days = 30) => request<AccountMetricsView>(`/api/accounts/${id}/metrics?days=${days}`),
  reclip: (video_id: string) => request<{ ok: boolean; kept_existing: boolean }>(`/api/videos/${video_id}/reclip`, json("POST")),
  updateWorkspace: (body: { name?: string; settings?: WorkspaceSettings }) => request<ApiWorkspace>("/api/workspace", json("PATCH", body)),
  engines: () => request<ApiEngine[]>("/api/engines"),
  selectEngine: (stage: StageId, engine_id: string) => request<ApiEngine[]>(`/api/engines/${stage}`, json("PUT", { engine_id })),
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

export const proxyUrl = (videoId: string) => `${API_BASE}/api/videos/${videoId}/proxy`;

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

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(1)}k`;
  return Math.round(n).toLocaleString("en-US");
}

export function fmtDelta(cur: number, prev: number): string | undefined {
  if (!prev) return undefined;
  const d = ((cur - prev) / prev) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(0)}% vs previous period`;
}
