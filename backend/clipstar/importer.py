"""Add a video from a link: a direct file link, a Dropbox share link, or a Google Drive share link.

Links to YouTube, TikTok, Instagram and similar sites are refused: downloading from them breaks their terms.
For those, upload the original file (or put it in Drive/Dropbox and share that link).
Only public internet addresses are fetched (no internal network), redirects are checked hop by hop, and
the size limit for uploads applies.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx

from .config import get_settings
from .errors import PermanentError, RetryableError

KIND = "video.import"
SOCIAL = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "x.com", "twitter.com", "vimeo.com", "twitch.tv", "linkedin.com", "pinterest.com", "threads.net", "snapchat.com")
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/webm": ".webm", "video/x-m4v": ".m4v", "video/x-msvideo": ".avi"}

_transport: httpx.BaseTransport | None = None  # tests use a fake server


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def normalize(url: str) -> tuple[str, str]:
    """(download URL, where it's from). Raises ValueError with a plain explanation."""
    url = url.strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Paste a full link starting with https://.")
    host = u.hostname.lower()
    if any(host == d or host.endswith("." + d) for d in SOCIAL):
        raise ValueError("clip_star doesn't download from YouTube or social sites (it's against their terms). Upload your original file, or share it from Google Drive or Dropbox.")
    if host.endswith("dropbox.com"):
        q = parse_qs(u.query)
        q.pop("dl", None)
        q["dl"] = ["1"]  # the file itself, not the preview page
        return urlunparse(u._replace(query=urlencode({k: v[0] for k, v in q.items()}))), "dropbox"
    if host in ("drive.google.com", "docs.google.com"):
        m = re.search(r"/file/d/([\w-]{10,})", u.path) or None
        fid = m.group(1) if m else (parse_qs(u.query).get("id") or [None])[0]
        if not fid:
            raise ValueError("That Google Drive link doesn't point to a file. Use the file's “Share → Copy link”.")
        return f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t", "google-drive"
    return url, "link"


def _check_host(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise PermanentError(url, user_message="The link redirected somewhere that isn't a web address.")
    if get_settings().import_allow_private:
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise RetryableError(str(e), user_message=f"Couldn't look up {u.hostname}.") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise PermanentError(u.hostname, user_message="That link points to a private or internal address, which clip_star doesn't fetch.")


def _filename(resp: httpx.Response, url: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return Path(unquote(m.group(1))).name
    name = Path(unquote(urlparse(url).path)).name
    return name or "video"


def download(url: str, dest: Path, on_progress=None, check=None) -> tuple[str, int]:
    """Stream the file at `url` into `dest`. Returns (original file name, size)."""
    st = get_settings()
    allowed = st.allowed_video_extensions
    headers = {"User-Agent": "clip_star-import/1"}
    with httpx.Client(timeout=httpx.Timeout(60, read=120), follow_redirects=False, transport=_transport) as c:
        for _ in range(6):  # follow redirects ourselves so every hop is checked
            _check_host(url)
            with c.stream("GET", url, headers=headers) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = str(httpx.URL(url).join(r.headers["location"]))
                    continue
                if r.status_code in (401, 403):
                    raise PermanentError(f"HTTP {r.status_code}", user_message="The link isn't public. Set sharing to “Anyone with the link” and try again.")
                if r.status_code == 404:
                    raise PermanentError("HTTP 404", user_message="Nothing was found at that link. Check it's the right one and still shared.")
                if r.status_code == 429 or r.status_code >= 500:
                    raise RetryableError(f"HTTP {r.status_code}", user_message=f"The file host answered {r.status_code}; will retry.")
                if r.status_code != 200:
                    raise PermanentError(f"HTTP {r.status_code}", user_message=f"The file host answered {r.status_code}.")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype.startswith("text/html"):
                    raise PermanentError("html", user_message="That link opens a web page, not the video file. Share the file itself (“Anyone with the link”), or use a direct download link.")
                name = _filename(r, url)
                ext = Path(name).suffix.lower()
                if ext not in allowed:
                    ext = VIDEO_TYPES.get(ctype, "")
                    if not ext:
                        raise PermanentError(ctype, user_message=f"That link isn't a video file ({ctype or 'unknown type'}). Use one of: {', '.join(allowed)}.")
                    name = f"{Path(name).stem or 'video'}{ext}"
                total = int(r.headers.get("content-length") or 0)
                if total > st.max_upload_bytes:
                    raise PermanentError("too big", user_message=f"The file is larger than the {st.max_upload_bytes // 1024**3} GB limit.")
                size = 0
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(4 * 1024 * 1024):
                        size += len(chunk)
                        if size > st.max_upload_bytes:
                            raise PermanentError("too big", user_message=f"The file is larger than the {st.max_upload_bytes // 1024**3} GB limit.")
                        f.write(chunk)
                        if check:
                            check()
                        if on_progress and total:
                            on_progress(min(99.0, 100 * size / total))
                if size == 0:
                    raise PermanentError("empty", user_message="The file at that link is empty.")
                return name, size
        raise PermanentError("redirects", user_message="The link redirected too many times.")


# ---------- job ----------


def run_import(ctx) -> dict:
    from .db import session_scope
    from .models import Video
    from .storage import get_storage

    vid = uuid.UUID(ctx.payload["video_id"])
    from .models import VideoStatus

    with session_scope() as s:
        v = s.get(Video, vid, with_for_update=True)
        if v is None:
            return {"skipped": "deleted"}
        v.status = VideoStatus.processing
    st = get_storage()
    tmp_rel = st.rel(vid, "download.part")
    tmp = st.abs(tmp_rel)
    try:
        name, size = download(ctx.payload["url"], tmp, lambda p: ctx.progress(p, "Downloading"), ctx.check)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    ext = Path(name).suffix.lower()
    master_rel = st.rel(vid, f"master{ext}")
    tmp.replace(st.abs(master_rel))
    with session_scope() as s:
        v = s.get(Video, vid)
        if v is None:
            st.delete_video(vid)
            return {"skipped": "deleted"}
    return {"master": master_rel, "size": size, "filename": name}


def _done(s, job, result: dict) -> None:
    from .models import Asset, Video, VideoStatus
    from .pipeline.stages import start_pipeline

    v = s.get(Video, job.video_id, with_for_update=True)
    if v is None or "master" not in result:
        return
    if v.status == VideoStatus.cancelled:
        return
    s.add(Asset(video_id=v.id, kind="master", path=result["master"], size_bytes=result["size"], meta={"filename": result["filename"], "imported_from": job.payload.get("source")}))
    v.size_bytes = result["size"]
    v.source_filename = result["filename"][:300]
    if v.meta and v.meta.get("title_from_link"):
        v.title = Path(result["filename"]).stem[:300] or v.title
    start_pipeline(s, v)


def _failed(s, job) -> None:
    from .models import Video, VideoStatus

    v = s.get(Video, job.video_id, with_for_update=True)
    if v is not None and v.status != VideoStatus.cancelled:
        v.status = VideoStatus.failed
        v.error = job.last_error or "The download failed."


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(KIND, Handler(run=run_import, on_success=_done, on_failure=_failed))
