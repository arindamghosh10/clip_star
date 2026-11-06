// Mock data for the clip_star UI prototype. Everything here is sample data;
// it will be replaced by API calls once the backend exists.

export type Platform = "instagram" | "facebook" | "tiktok" | "youtube" | "x" | "linkedin" | "threads" | "pinterest";

export const PLATFORMS: Record<Platform, { label: string; short: string; limit: number; note: string }> = {
  youtube: { label: "YouTube Shorts", short: "YT", limit: 10, note: "Daily API quota per app" },
  instagram: { label: "Instagram Reels", short: "IG", limit: 50, note: "50 API posts / account / day" },
  facebook: { label: "Facebook Pages", short: "FB", limit: 25, note: "Pages API" },
  tiktok: { label: "TikTok", short: "TT", limit: 15, note: "Private-only until app audit" },
  x: { label: "X", short: "X", limit: 20, note: "Paid API tier" },
  linkedin: { label: "LinkedIn", short: "IN", limit: 10, note: "Needs API approval" },
  threads: { label: "Threads", short: "TH", limit: 25, note: "Threads API" },
  pinterest: { label: "Pinterest", short: "PIN", limit: 20, note: "Video pins" },
};

export type StageId =
  | "ingest"
  | "understand"
  | "moments"
  | "edit"
  | "package"
  | "publish"
  | "engage"
  | "measure"
  | "learn";

export const STAGES: { id: StageId; name: string; output: string; gated?: boolean }[] = [
  { id: "ingest", name: "Ingest", output: "Master file + preview copy" },
  { id: "understand", name: "Understand", output: "Transcript, speakers, scenes, energy" },
  { id: "moments", name: "Find moments", output: "Ranked candidates with reasons" },
  { id: "edit", name: "Edit", output: "9:16 clips, captions, variants" },
  { id: "package", name: "Package", output: "Title, caption, tags per platform", gated: true },
  { id: "publish", name: "Publish", output: "Scheduled posts on each account" },
  { id: "engage", name: "Engage", output: "Sorted comments, drafted replies", gated: true },
  { id: "measure", name: "Measure", output: "Views, retention, shares, follows" },
  { id: "learn", name: "Learn", output: "Reports, suggestions, re-clips" },
];

// ---------- Videos ----------

export type VideoStatus = "processing" | "review" | "publishing" | "done";

export type Video = {
  id: string;
  title: string;
  file: string;
  duration: string;
  uploaded: string;
  status: VideoStatus;
  stage: StageId;
  progress: number;
  speakers: number;
  scenes: number;
  words: number;
  clips: number;
};

export const VIDEOS: Video[] = [
  { id: "ep113", title: "Ep. 113 · Side hustles that actually pay", file: "ep113_master.mov", duration: "01:04:12", uploaded: "Today 09:41", status: "processing", stage: "moments", progress: 40, speakers: 2, scenes: 47, words: 10840, clips: 0 },
  { id: "ep112", title: "Ep. 112 · The rent trap", file: "ep112_master.mov", duration: "00:58:40", uploaded: "Tue 10:02", status: "review", stage: "package", progress: 100, speakers: 2, scenes: 41, words: 9812, clips: 8 },
  { id: "ep111", title: "Ep. 111 · Credit scores explained", file: "ep111_master.mov", duration: "00:51:03", uploaded: "Last week", status: "publishing", stage: "publish", progress: 100, speakers: 1, scenes: 33, words: 8420, clips: 5 },
  { id: "ep110", title: "Ep. 110 · Emergency funds", file: "ep110_master.mov", duration: "00:47:55", uploaded: "2 weeks ago", status: "done", stage: "learn", progress: 100, speakers: 2, scenes: 38, words: 7905, clips: 4 },
];

// ---------- Clips (moments for ep112) ----------

export type ClipStatus = "pending" | "approved" | "rejected";

export type Clip = {
  id: string;
  videoId: string;
  title: string;
  start: string;
  end: string;
  seconds: number;
  score: number;
  reason: string;
  hook: string;
  status: ClipStatus;
  variants: string[];
  copy: Partial<Record<Platform, string>>;
};

export const CLIPS: Clip[] = [
  { id: "c1", videoId: "ep112", title: "Nobody tells you this about rent", start: "00:14:32", end: "00:15:18", seconds: 46, score: 92, reason: "Bold claim in the first line, story payoff, energy peak", hook: "NOBODY TELLS YOU THIS", status: "approved", variants: ["A", "B"], copy: { youtube: "Nobody tells you this about rent", instagram: "I lost $40 a month for 3 years before I noticed…", tiktok: "the rent trap 🏠" } },
  { id: "c2", videoId: "ep112", title: "The $40 mistake", start: "00:21:05", end: "00:21:49", seconds: 44, score: 87, reason: "Number-led hook, clear single idea, quotable ending", hook: "THE $40 MISTAKE", status: "approved", variants: ["A", "B"], copy: { youtube: "The $40 rent mistake most people make", instagram: "Check your lease for this one line 👀", tiktok: "$40/month gone" } },
  { id: "c3", videoId: "ep112", title: "Landlord red flags", start: "00:33:10", end: "00:34:02", seconds: 52, score: 84, reason: "List format, fast pacing, high comment potential", hook: "3 LANDLORD RED FLAGS", status: "approved", variants: ["A"], copy: { youtube: "3 landlord red flags before you sign", instagram: "Red flag #2 is the one everyone misses", tiktok: "landlord red flags 🚩" } },
  { id: "c4", videoId: "ep112", title: "Why your deposit disappears", start: "00:08:40", end: "00:09:22", seconds: 42, score: 81, reason: "Common frustration, clear explanation, ends on a tip", hook: "WHERE YOUR DEPOSIT GOES", status: "pending", variants: ["A", "B"], copy: { youtube: "Why your rental deposit disappears", instagram: "Take these 4 photos on move-in day", tiktok: "deposit gone?" } },
  { id: "c5", videoId: "ep112", title: "Negotiating rent in 2 sentences", start: "00:41:18", end: "00:41:52", seconds: 34, score: 77, reason: "Practical script, short and repeatable", hook: "SAY THIS TO YOUR LANDLORD", status: "pending", variants: ["A"], copy: { youtube: "How to negotiate rent in 2 sentences", instagram: "Copy this exact script", tiktok: "say this to your landlord" } },
  { id: "c6", videoId: "ep112", title: "Renting vs buying, honestly", start: "00:47:02", end: "00:47:58", seconds: 56, score: 74, reason: "Debate topic, strong opinion, may split comments", hook: "RENTING ISN'T WASTED MONEY", status: "approved", variants: ["A", "B"], copy: { youtube: "Is renting really wasted money?", instagram: "Unpopular opinion: renting is fine", tiktok: "renting isn't throwing money away" } },
  { id: "c7", videoId: "ep112", title: "Guest intro", start: "00:00:40", end: "00:01:22", seconds: 42, score: 52, reason: "Slow start, needs context from earlier", hook: "MEET SAM", status: "rejected", variants: ["A"], copy: {} },
  { id: "c8", videoId: "ep112", title: "Sponsor read", start: "00:25:30", end: "00:26:10", seconds: 40, score: 31, reason: "Ad segment, low standalone value", hook: "", status: "rejected", variants: [], copy: {} },
];

// ---------- Accounts ----------

export type Account = {
  id: string;
  handle: string;
  platform: Platform;
  group: string;
  status: "connected" | "reconnect" | "paused";
  today: number;
  next: string;
  timezone: string;
  language: string;
};

const igHandles = ["@moneywithmaya", "@paisa.maya", "@rentfacts.daily", "@maya.budgets", "@savewithmaya", "@maya.invests", "@tenant.tips", "@maya.hindi", "@moneyminutes.uk", "@maya.money.es"];
const fbPages = ["Maya Money", "Maya Money Hindi", "Rent Facts", "Budget Basics", "Save With Maya", "Maya Invests", "Tenant Tips", "Paisa With Maya", "Money Minutes UK", "Maya Money ES"];
const ttHandles = ["@maya.tok", "@paisa.tok", "@rentfacts.daily", "@budget.bites", "@maya.saves", "@invest.tok", "@tenant.talk", "@maya.hi", "@money.uk", "@maya.es"];
const groups = ["Finance EN", "Finance HI", "Renting tips", "Finance EN", "Finance EN", "Investing", "Renting tips", "Finance HI", "Finance UK", "Finance ES"];
const langs = ["English", "Hindi", "English", "English", "English", "English", "English", "Hindi", "English", "Spanish"];
const tz = ["America/New_York", "Asia/Kolkata", "America/Chicago", "America/New_York", "America/Los_Angeles", "America/New_York", "America/Chicago", "Asia/Kolkata", "Europe/London", "Europe/Madrid"];
const nexts = ["Wed 18:00", "Wed 20:15", "Thu 09:30", "Thu 12:00", "Thu 18:00", "Fri 11:00", "Fri 17:45", "Sat 10:30", "Sat 13:00", "Sun 12:00"];

function build(platform: Platform, names: string[], prefix: string): Account[] {
  return names.map((handle, i) => ({
    id: `${prefix}${i + 1}`,
    handle,
    platform,
    group: groups[i],
    status: platform === "facebook" && i === 0 ? "reconnect" : platform === "tiktok" && i === 2 ? "paused" : "connected",
    today: (i * 7 + prefix.length) % 3,
    next: platform === "tiktok" && i === 2 ? "—" : nexts[(i + prefix.length) % nexts.length],
    timezone: tz[i],
    language: langs[i],
  }));
}

export const ACCOUNTS: Account[] = [
  ...build("instagram", igHandles, "ig"),
  ...build("facebook", fbPages, "fb"),
  ...build("tiktok", ttHandles, "tt"),
  { id: "yt1", handle: "Maya Money", platform: "youtube", group: "Finance EN", status: "connected", today: 1, next: "Wed 19:30", timezone: "America/New_York", language: "English" },
  { id: "yt2", handle: "Maya Money Hindi", platform: "youtube", group: "Finance HI", status: "connected", today: 0, next: "Thu 19:30", timezone: "Asia/Kolkata", language: "Hindi" },
  { id: "yt3", handle: "Rent Facts", platform: "youtube", group: "Renting tips", status: "connected", today: 0, next: "Sun 18:30", timezone: "America/Chicago", language: "English" },
  { id: "x1", handle: "@mayamoney", platform: "x", group: "Finance EN", status: "connected", today: 2, next: "Sat 13:00", timezone: "America/New_York", language: "English" },
  { id: "x2", handle: "@rentfacts", platform: "x", group: "Renting tips", status: "connected", today: 0, next: "Mon 12:00", timezone: "America/Chicago", language: "English" },
];

export const GROUPS = Array.from(new Set(ACCOUNTS.map((a) => a.group)));

// ---------- Batches & rules ----------

export type BatchStatus = "awaiting" | "running" | "disabled" | "finished";

export type Batch = {
  id: string;
  name: string;
  clips: number;
  accounts: number;
  posts: number;
  posted: number;
  window: string;
  status: BatchStatus;
  variations: string;
};

export const BATCHES: Batch[] = [
  { id: "B-0412", name: "Ep. 112 · The rent trap", clips: 6, accounts: 30, posts: 120, posted: 0, window: "Wed–Tue", status: "awaiting", variations: "Text + Packaging" },
  { id: "B-0409", name: "Ep. 111 · Credit scores", clips: 5, accounts: 22, posts: 88, posted: 64, window: "Last Thu–Wed", status: "running", variations: "Text" },
  { id: "B-0405", name: "Old episodes re-clip", clips: 9, accounts: 14, posts: 41, posted: 0, window: "Fri–Mon", status: "disabled", variations: "Edit" },
  { id: "B-0398", name: "Ep. 110 · Emergency funds", clips: 4, accounts: 18, posts: 72, posted: 72, window: "2 weeks ago", status: "finished", variations: "Off" },
];

export type Rule = {
  id: string;
  name: string;
  when: string;
  groups: string[];
  pace: string;
  hours: string;
  spacing: string;
  variations: string;
  approval: string;
  enabled: boolean;
};

export const RULES: Rule[] = [
  { id: "r1", name: "Top clips to English accounts", when: "Clip score ≥ 80", groups: ["Finance EN", "Renting tips"], pace: "2 per account / day", hours: "09:00–21:00 local", spacing: "≥ 45 min between accounts", variations: "Text + Packaging", approval: "One approval per batch", enabled: true },
  { id: "r2", name: "Hindi dubbed versions", when: "Clip score ≥ 85 and dubbing finished", groups: ["Finance HI"], pace: "1 per account / day", hours: "10:00–22:00 local", spacing: "≥ 60 min between accounts", variations: "Text (Hindi)", approval: "One approval per batch", enabled: true },
  { id: "r3", name: "Weekend re-clips", when: "Re-clip from archive", groups: ["Investing", "Finance UK"], pace: "1 per account / day", hours: "Sat–Sun, 11:00–19:00", spacing: "≥ 90 min between accounts", variations: "Edit", approval: "One approval per batch", enabled: false },
];

// ---------- Calendar ----------

export type CalEvent = { day: number; time: string; clip: string; platform: Platform; count: number; batch: string };

export const DAYS = ["Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue"];

export const CALENDAR: CalEvent[] = [
  { day: 0, time: "18:00", clip: "Rent trap", platform: "instagram", count: 4, batch: "B-0412" },
  { day: 0, time: "19:30", clip: "Rent trap", platform: "youtube", count: 3, batch: "B-0412" },
  { day: 1, time: "10:00", clip: "Rent trap", platform: "facebook", count: 5, batch: "B-0412" },
  { day: 1, time: "12:15", clip: "Rent trap", platform: "tiktok", count: 5, batch: "B-0412" },
  { day: 1, time: "18:00", clip: "Rent trap", platform: "instagram", count: 6, batch: "B-0412" },
  { day: 2, time: "11:00", clip: "$40 mistake", platform: "tiktok", count: 5, batch: "B-0412" },
  { day: 2, time: "17:45", clip: "$40 mistake", platform: "instagram", count: 5, batch: "B-0412" },
  { day: 2, time: "20:00", clip: "Old re-clip", platform: "facebook", count: 3, batch: "B-0405" },
  { day: 3, time: "10:30", clip: "$40 mistake", platform: "facebook", count: 10, batch: "B-0412" },
  { day: 3, time: "13:00", clip: "Rent trap", platform: "x", count: 2, batch: "B-0412" },
  { day: 3, time: "15:00", clip: "Old re-clip", platform: "instagram", count: 4, batch: "B-0405" },
  { day: 4, time: "12:00", clip: "Red flags", platform: "instagram", count: 10, batch: "B-0412" },
  { day: 4, time: "18:30", clip: "$40 mistake", platform: "youtube", count: 3, batch: "B-0412" },
  { day: 5, time: "09:30", clip: "Red flags", platform: "tiktok", count: 10, batch: "B-0412" },
  { day: 5, time: "12:00", clip: "$40 mistake", platform: "x", count: 2, batch: "B-0412" },
  { day: 6, time: "11:00", clip: "Red flags", platform: "facebook", count: 5, batch: "B-0412" },
  { day: 6, time: "19:00", clip: "Renting vs buying", platform: "instagram", count: 8, batch: "B-0412" },
];

// ---------- Variation matrix ----------

export type VariationKind = "original" | "text" | "packaging" | "edit" | "off";

export const VARIATION_MATRIX: { clip: string; cells: Partial<Record<Platform, { kind: VariationKind; label: string }>> }[] = [
  { clip: "Rent trap", cells: { instagram: { kind: "text", label: "A · text" }, facebook: { kind: "text", label: "A · text" }, tiktok: { kind: "edit", label: "B · 30s cut" }, youtube: { kind: "packaging", label: "C · new hook" }, x: { kind: "original", label: "original" } } },
  { clip: "The $40 mistake", cells: { instagram: { kind: "packaging", label: "B · cover" }, facebook: { kind: "text", label: "A · text" }, tiktok: { kind: "edit", label: "C · new start" }, youtube: { kind: "text", label: "A · text" }, x: { kind: "original", label: "original" } } },
  { clip: "Landlord red flags", cells: { instagram: { kind: "text", label: "A · text" }, facebook: { kind: "original", label: "original" }, tiktok: { kind: "packaging", label: "B · captions" }, youtube: { kind: "off", label: "off" }, x: { kind: "off", label: "off" } } },
  { clip: "Renting vs buying", cells: { instagram: { kind: "text", label: "A · text" }, facebook: { kind: "text", label: "A · text" }, tiktok: { kind: "edit", label: "B · 40s cut" }, youtube: { kind: "packaging", label: "B · new hook" }, x: { kind: "off", label: "off" } } },
];

// ---------- Comments ----------

export type CommentCategory = "question" | "praise" | "lead" | "spam";

export type Comment = {
  id: string;
  author: string;
  platform: Platform;
  account: string;
  clip: string;
  text: string;
  category: CommentCategory;
  draft?: string;
  status: "open" | "sent" | "skipped" | "hidden";
  time: string;
};

export const COMMENTS: Comment[] = [
  { id: "m1", author: "@priya.k", platform: "instagram", account: "@moneywithmaya", clip: "Rent trap", text: "Does this work if you rent in the UK?", category: "question", draft: "Yes, mostly! UK rules differ on deposits, so I'm doing a full UK video next week.", status: "open", time: "12m" },
  { id: "m2", author: "@jordan_saves", platform: "tiktok", account: "@maya.tok", clip: "$40 mistake", text: "How do I find that clause in my lease?", category: "question", draft: "Look for 'administrative fees' or 'service charges', usually near the payment section.", status: "open", time: "25m" },
  { id: "m3", author: "Daniel R.", platform: "facebook", account: "Maya Money", clip: "Landlord red flags", text: "Red flag #2 happened to me last year 😩", category: "praise", draft: "Ugh, so sorry! Glad you know what to look for now.", status: "open", time: "41m" },
  { id: "m4", author: "@smallbiz.hq", platform: "instagram", account: "@moneywithmaya", clip: "Rent trap", text: "Would love to have you on our podcast, how do we reach you?", category: "lead", draft: "Thanks! Please email the address in my bio and we'll set it up.", status: "open", time: "1h" },
  { id: "m5", author: "@crypto_gainz_99", platform: "tiktok", account: "@maya.tok", clip: "Rent trap", text: "DM me to 10x your money 🚀🚀", category: "spam", status: "open", time: "1h" },
  { id: "m6", author: "@ananya.m", platform: "youtube", account: "Maya Money", clip: "Renting vs buying", text: "Finally someone says renting isn't wasted money!", category: "praise", draft: "Right?! It depends on your city and plans, not a rule.", status: "open", time: "2h" },
  { id: "m7", author: "@tom.h", platform: "instagram", account: "@moneyminutes.uk", clip: "Rent trap", text: "Is the deposit protection scheme the same thing?", category: "question", draft: "Related! The deposit schemes protect it, but fees can still be taken out. More in the UK video.", status: "open", time: "3h" },
  { id: "m8", author: "@lena.budget", platform: "x", account: "@mayamoney", clip: "$40 mistake", text: "Thank you, just saved $480 a year", category: "praise", draft: "That's amazing! 🎉", status: "sent", time: "5h" },
];

// ---------- Analytics ----------

export const PERFORMANCE = [
  { clip: "Rent trap · B", platform: "youtube" as Platform, views: 48200, watched: 61, shares: 912, follows: 312 },
  { clip: "Rent trap · A", platform: "instagram" as Platform, views: 22900, watched: 52, shares: 640, follows: 188 },
  { clip: "Landlord red flags", platform: "tiktok" as Platform, views: 19700, watched: 44, shares: 301, follows: 97 },
  { clip: "The $40 mistake · A", platform: "instagram" as Platform, views: 17400, watched: 58, shares: 455, follows: 141 },
  { clip: "Renting vs buying", platform: "facebook" as Platform, views: 9100, watched: 39, shares: 120, follows: 33 },
  { clip: "Credit score myths", platform: "tiktok" as Platform, views: 31200, watched: 49, shares: 710, follows: 205 },
];

export const DAILY_VIEWS = [8200, 9100, 7600, 11800, 15400, 13900, 12100, 16800, 21300, 19700, 18200, 24600, 29900, 27400];

export const INSIGHTS = [
  { kind: "do", title: "Hooks with a number", body: "\"The $40 mistake\" style hooks got 2.3× the watch time of question hooks this month." },
  { kind: "do", title: "40–50 second clips", body: "Clips between 40 and 50 seconds had the highest completion rate across all platforms." },
  { kind: "avoid", title: "Guest intros", body: "Clips that open on a guest introduction lose 60% of viewers in the first 3 seconds." },
  { kind: "idea", title: "Next video: UK renting", body: "40 comments this week asked about renting in the UK. Strong topic for Ep. 114." },
  { kind: "idea", title: "Re-clip Ep. 98, 101, 104", body: "These older episodes have moments that match your best-performing pattern." },
];

// ---------- Engines / connectors ----------

export type EngineOption = { id: string; name: string; kind: "free" | "connector"; note: string; cost?: string };

export const ENGINES: Record<StageId, EngineOption[]> = {
  ingest: [
    { id: "upload", name: "Direct upload + FFmpeg", kind: "free", note: "Local or MinIO storage" },
    { id: "gdrive", name: "Google Drive", kind: "connector", note: "Import from your Drive" },
    { id: "dropbox", name: "Dropbox", kind: "connector", note: "Import from Dropbox" },
  ],
  understand: [
    { id: "whisperx", name: "WhisperX", kind: "free", note: "Word timing + speakers", cost: "$0.18 GPU" },
    { id: "deepgram", name: "Deepgram", kind: "connector", note: "Hosted, fast", cost: "$0.26" },
    { id: "assemblyai", name: "AssemblyAI", kind: "connector", note: "Hosted", cost: "$0.22" },
  ],
  moments: [
    { id: "local-llm", name: "Local model + rules", kind: "free", note: "Ollama", cost: "$0.00" },
    { id: "claude", name: "Claude", kind: "connector", note: "Your Anthropic key", cost: "$0.40" },
    { id: "openai", name: "OpenAI", kind: "connector", note: "Your OpenAI key", cost: "$0.35" },
    { id: "klap", name: "Klap (stages 3–4)", kind: "connector", note: "Clipping vendor", cost: "per minute" },
    { id: "opus", name: "OpusClip (stages 3–4)", kind: "connector", note: "Clipping vendor", cost: "per minute" },
    { id: "reap", name: "Reap (stages 3–4)", kind: "connector", note: "Clipping vendor", cost: "per minute" },
  ],
  edit: [
    { id: "ffmpeg", name: "FFmpeg renderer", kind: "free", note: "Reframe, captions, brand kit", cost: "$0.22 GPU" },
    { id: "submagic", name: "Submagic captions", kind: "connector", note: "Caption styles" },
    { id: "elevenlabs", name: "ElevenLabs dubbing", kind: "connector", note: "Other languages" },
  ],
  package: [
    { id: "local-llm", name: "Local model", kind: "free", note: "Voice examples + templates", cost: "$0.00" },
    { id: "claude", name: "Claude", kind: "connector", note: "Your Anthropic key", cost: "$0.10" },
  ],
  publish: [
    { id: "builtin", name: "Built-in publishers", kind: "free", note: "Official APIs", cost: "$0.00" },
    { id: "ayrshare", name: "Ayrshare", kind: "connector", note: "Posting API" },
    { id: "postiz", name: "Postiz", kind: "connector", note: "Open-source scheduler" },
  ],
  engage: [
    { id: "local-llm", name: "Local model", kind: "free", note: "Sorting + drafts", cost: "$0.00" },
    { id: "claude", name: "Claude", kind: "connector", note: "Better drafts", cost: "$0.05" },
  ],
  measure: [{ id: "platform-apis", name: "Platform analytics APIs", kind: "free", note: "Through account logins", cost: "$0.00" }],
  learn: [
    { id: "builtin-stats", name: "Built-in stats + local model", kind: "free", note: "Weekly report", cost: "$0.00" },
    { id: "claude", name: "Claude", kind: "connector", note: "Deeper reports", cost: "$0.05" },
  ],
};

export const DEFAULT_ENGINES: Record<StageId, string> = {
  ingest: "upload",
  understand: "whisperx",
  moments: "claude",
  edit: "ffmpeg",
  package: "claude",
  publish: "builtin",
  engage: "claude",
  measure: "platform-apis",
  learn: "builtin-stats",
};

export type Connection = { id: string; name: string; usedFor: string; status: "connected" | "reconnect" | "off" };

export const CONNECTIONS: Connection[] = [
  { id: "anthropic", name: "Anthropic (Claude) API key", usedFor: "Moments, copy, replies", status: "connected" },
  { id: "runpod", name: "RunPod account", usedFor: "GPU for free engines", status: "connected" },
  { id: "openai", name: "OpenAI API key", usedFor: "Alternative AI model", status: "off" },
  { id: "deepgram", name: "Deepgram API key", usedFor: "Hosted transcription", status: "off" },
  { id: "klap", name: "Klap account", usedFor: "Clipping (optional)", status: "off" },
  { id: "elevenlabs", name: "ElevenLabs API key", usedFor: "Dubbing", status: "connected" },
  { id: "gdrive", name: "Google Drive", usedFor: "Import source videos", status: "reconnect" },
];
