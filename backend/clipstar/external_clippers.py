"""External clipping services (your own account and API key): Klap and Vizard.

They take the long video and return finished clips (their own framing and captions). clip_star hands
them a signed, expiring link to the video, waits, downloads the clips and adds them to Clips for review
like any other, with post text written by the free template engine (change it in the clip editor).
Approving, scheduling, publishing and stats then work as usual.

Request shapes follow the vendors' public docs; response field names vary between their pages, so
several spellings are accepted. These connectors need a real key to be fully verified.
- Klap: POST https://api.klap.app/v2/tasks/video-to-shorts {source_video_url, …} (Bearer key);
  GET /tasks/{id} until ready; GET /projects/{folder_id}; export each project and fetch its file.
- Vizard: POST https://elb-api.vizard.ai/hvizard-server-front/open-api/v1/project/create
  {videoUrl, videoType: 1, …} (header VIZARDAI_API_KEY) -> projectId; GET …/project/query/{projectId}.
Other clipping services (OpusClip, Submagic, Reap, Lumiclip, ScaleReach) had no public clipping API
we could confirm, so they aren't connected.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from . import budget
from .config import get_settings
from .errors import PermanentError, RetryableError

KIND = "video.external_clips"
POLL_S = 20.0
VENDORS = {"klap": "Klap", "vizard": "Vizard"}

_transport: httpx.BaseTransport | None = None


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def configured(vendor: str) -> bool:
    st = get_settings()
    return bool({"klap": st.klap_api_key, "vizard": st.vizard_api_key}.get(vendor))


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _check(r: httpx.Response, name: str) -> dict:
    if r.status_code in (401, 403):
        raise PermanentError(r.text[:300], user_message=f"{name} rejected the API key.")
    if r.status_code == 402:
        raise PermanentError(r.text[:300], user_message=f"{name} says the account is out of credit.")
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(r.text[:300], user_message=f"{name} is busy ({r.status_code}); will retry.")
    if r.status_code >= 400:
        raise PermanentError(r.text[:300], user_message=f"{name} refused the request ({r.status_code}): {r.text[:160]}")
    try:
        return r.json()
    except ValueError as e:
        raise PermanentError(r.text[:300], user_message=f"{name} sent an answer clip_star couldn't read.") from e


def _wait(fn, check, deadline_s: float, name: str):
    deadline = time.monotonic() + deadline_s
    while True:
        if check:
            check()
        done = fn()
        if done is not None:
            return done
        if time.monotonic() > deadline:
            raise RetryableError("timeout", user_message=f"{name} is taking a long time; will check again.")
        time.sleep(POLL_S)


def klap_clips(c: httpx.Client, video_url: str, max_clips: int, check=None) -> list[dict]:
    st = get_settings()
    base = "https://api.klap.app/v2"
    h = {"Authorization": f"Bearer {st.klap_api_key}"}
    task = _check(c.post(f"{base}/tasks/video-to-shorts", headers=h, json={"source_video_url": video_url, "language": "en", "max_clip_count": max_clips, "max_duration": 60}), "Klap")
    tid = _pick(task, "id", "task_id")

    def poll():
        t = _check(c.get(f"{base}/tasks/{tid}", headers=h), "Klap")
        status = str(_pick(t, "status", default="")).lower()
        if status in ("error", "failed"):
            raise PermanentError(str(t), user_message=f"Klap couldn't process the video: {_pick(t, 'error', 'message', default='failed')}")
        return t if status in ("ready", "done", "completed", "success") else None

    t = _wait(poll, check, 6 * 3600, "Klap")
    folder = _pick(t, "output_id", "folder_id", "project_id")
    projects = _check(c.get(f"{base}/projects/{folder}", headers=h), "Klap")
    if isinstance(projects, dict):
        projects = _pick(projects, "projects", "items", "data", default=[])
    out = []
    for p in projects[:max_clips]:
        pid = _pick(p, "id", "project_id")
        exp = _check(c.post(f"{base}/projects/{folder}/{pid}/exports", headers=h, json={}), "Klap")
        eid = _pick(exp, "id", "export_id")

        def poll_export():
            e = _check(c.get(f"{base}/projects/{folder}/{pid}/exports/{eid}", headers=h), "Klap")
            status = str(_pick(e, "status", default="")).lower()
            if status in ("error", "failed"):
                return {}
            return e if _pick(e, "src_url", "url", "download_url") else None

        e = _wait(poll_export, check, 3600, "Klap")
        link = _pick(e, "src_url", "url", "download_url")
        if link:
            out.append({"url": link, "title": _pick(p, "name", "title", default="Klap clip"), "score": _pick(p, "virality_score", "score"), "reason": _pick(p, "virality_score_explanation", "description", default="Picked by Klap")})
    return out


def vizard_clips(c: httpx.Client, video_url: str, max_clips: int, check=None) -> list[dict]:
    st = get_settings()
    base = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"
    h = {"VIZARDAI_API_KEY": st.vizard_api_key or "", "Content-Type": "application/json"}
    created = _check(c.post(f"{base}/project/create", headers=h, json={"videoUrl": video_url, "videoType": 1, "lang": "en", "maxClipNumber": max_clips, "subtitleSwitch": 1, "headlineSwitch": 1}), "Vizard")
    if str(created.get("code")) != "2000":
        raise PermanentError(str(created), user_message=f"Vizard refused the video: {_pick(created, 'errMsg', 'message', default=created.get('code'))}")
    pid = created.get("projectId")

    def poll():
        q = _check(c.get(f"{base}/project/query/{pid}", headers=h), "Vizard")
        code = str(q.get("code"))
        if code == "2000" and q.get("videos"):
            return q
        if code not in ("1000", "2000"):  # 1000 = still processing
            raise PermanentError(str(q), user_message=f"Vizard couldn't process the video: {_pick(q, 'errMsg', 'message', default=code)}")
        return None

    q = _wait(poll, check, 6 * 3600, "Vizard")
    return [
        {"url": _pick(v, "videoUrl", "url"), "title": _pick(v, "title", default="Vizard clip"), "score": _pick(v, "viralScore", "score"), "reason": _pick(v, "viralReason", default="Picked by Vizard")}
        for v in (q.get("videos") or [])[:max_clips]
        if _pick(v, "videoUrl", "url")
    ]


def run_external(ctx) -> dict:
    """Send the video to the vendor, download its clips, and add them as pending clips."""
    from sqlalchemy import select

    from .db import session_scope
    from .media import probe, run_ffmpeg
    from .models import Asset, Video
    from .publishing.service import public_media_url
    from .storage import get_storage

    vendor = ctx.payload["vendor"]
    name = VENDORS[vendor]
    vid = uuid.UUID(ctx.payload["video_id"])
    st = get_storage()
    with session_scope() as s:
        v = s.get(Video, vid)
        master = s.scalar(select(Asset).where(Asset.video_id == vid, Asset.kind == "master"))
        if v is None or master is None:
            raise PermanentError("no video", user_message="The original video file is missing.")
        rel = master.path
        from .models import Workspace

        ws = s.get(Workspace, v.workspace_id)
        max_clips = int(((ws.settings if ws else None) or {}).get("max_clips", 8))
    link = public_media_url(rel, ttl_s=24 * 3600)
    if not link:
        raise PermanentError("no public url", user_message=f"{name} downloads the video itself, so this server must be reachable from the internet. Set CLIPSTAR_PUBLIC_MEDIA_URL.")
    from .engines.llm import EngineDeclined

    try:
        budget.check(vendor)
    except EngineDeclined as e:
        raise PermanentError(str(e), user_message=f"{name} skipped: {e}.") from e
    ctx.progress(5, f"Sent to {name}; waiting for its clips")
    with httpx.Client(timeout=120, transport=_transport, follow_redirects=True) as c:
        try:
            clips = (klap_clips if vendor == "klap" else vizard_clips)(c, link, max_clips, ctx.check)
            budget.charge(vendor, 0, 0, 0.0)  # vendors bill per minute/credit on their side; recorded for the activity count
            saved = []
            for k, cl in enumerate(clips):
                ctx.progress(60 + 35 * k / max(1, len(clips)), f"Downloading clip {k + 1} of {len(clips)} from {name}")
                cid = uuid.uuid4()
                vrel = st.rel(vid, f"clips/{cid}/A.mp4")
                tmp = st.tmp_path_for(vrel)
                try:
                    with c.stream("GET", cl["url"]) as r:
                        if r.status_code != 200:
                            continue
                        with tmp.open("wb") as f:
                            for chunk in r.iter_bytes(4 * 1024 * 1024):
                                f.write(chunk)
                    st.commit_tmp(tmp, vrel)
                finally:
                    if tmp.exists():
                        tmp.unlink()
                info = probe(st.abs(vrel))
                crel = st.rel(vid, f"clips/{cid}/A.jpg")
                run_ffmpeg(["-ss", f"{min(1.0, info.duration_s / 2):.2f}", "-i", str(st.abs(vrel)), "-frames:v", "1", "-q:v", "3", "-y", str(st.abs(crel))], timeout_s=60)
                saved.append({**cl, "id": str(cid), "path": vrel, "cover": crel, "duration_s": info.duration_s, "size_bytes": info.size_bytes})
        except httpx.HTTPError as e:
            raise RetryableError(str(e), user_message=f"Couldn't reach {name}; will retry.") from e
    return {"clips": saved, "vendor": vendor}


def _done(s, job, result: dict) -> None:
    from types import SimpleNamespace

    from .engines.registry import get_engine
    from .models import Clip, ClipStatus, Stage, Video, Workspace
    from .pipeline.package import ClipContext, PackageSettings, finalize_copy

    v = s.get(Video, job.video_id)
    if v is None:
        return
    ws = s.get(Workspace, v.workspace_id)
    pst = PackageSettings.from_workspace(ws.settings if ws else {})
    eng = get_engine(Stage.package, "templates")
    ctx = SimpleNamespace(check=lambda: None, progress=lambda *a, **k: None)
    for cl in result.get("clips", []):
        dur = float(cl["duration_s"])
        cc = ClipContext(title=cl["title"], hook="", text=cl["title"], duration=dur)
        raw, _ = eng.write(ctx, cc, pst)
        copy, pre, _ = finalize_copy(raw, cc, pst)
        score = cl.get("score")
        try:
            score = int(round(float(score) * (10 if float(score) <= 10 else 1)))
        except (TypeError, ValueError):
            score = 60
        s.add(
            Clip(
                id=uuid.UUID(cl["id"]), video_id=v.id, title=str(cl["title"])[:300], start_s=0.0, end_s=round(dur, 3), score=max(0, min(100, score)), status=ClipStatus.pending,
                reason=str(cl.get("reason") or "")[:500], hook="", engine=result["vendor"], copy=copy,
                variants=[{"id": "A", "caption_style": "vendor", "hook": ""}],
                meta={"external": result["vendor"], "renders": {"A": {"key": f"{result['vendor']}:{cl['id']}", "path": cl["path"], "cover": cl["cover"], "duration_s": round(dur, 2), "size_bytes": cl["size_bytes"]}}, "preflight": pre, "copy_engine": "templates"},
            )
        )


def _failed(s, job) -> None:
    from .notify import notify
    from .models import Video

    v = s.get(Video, job.video_id)
    if v is not None:
        notify(s, v.workspace_id, "video_failed", f"{VENDORS.get(job.payload.get('vendor'), 'The clipping service')} couldn't clip “{v.title}”", job.last_error or "", f"/videos/{v.id}", "error", dedupe=f"external_failed:{job.id}")


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(KIND, Handler(run=run_external, on_success=_done, on_failure=_failed))
