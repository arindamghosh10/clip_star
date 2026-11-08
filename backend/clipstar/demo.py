"""Fill clip_star with a realistic demo, using the real pipeline and practice accounts.

    python -m clipstar.demo                       # creates the "Maya Money (demo)" workspace
    python -m clipstar.demo --email you@x.com --password '…'   # owner login if this is a fresh install

What it makes:
- a generated podcast episode of about 5½ minutes (with a captions file, so no speech model is needed),
  processed through every stage: moments, 9:16 clips with captions, post text for each platform;
- 9 practice accounts across Instagram, TikTok, YouTube, Facebook, X, LinkedIn and Threads;
- two weeks of posting history with stats, follower growth, comments sorted with drafted replies,
  upcoming posts, a batch waiting for approval, and a weekly report with insights.
Practice accounts post nothing and their numbers are simulated; every screen labels them.
"""

from __future__ import annotations

import argparse
import random
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from .db import session_scope

NAME = "Maya Money (demo)"

SCRIPT = [
    "Hey everyone, welcome back to Money Minutes.",
    "Before we start, this episode is sponsored by our friends at Nestwise.",
    "Use the link in the description to get your first month free.",
    "Okay. Today is all about renting without getting ripped off.",
    "Nobody tells you this, but your lease is a negotiation.",
    "Most people sign the first version they are handed.",
    "Landlords expect you to push back on at least two things.",
    "Here are 3 clauses I always ask to remove.",
    "Number one is the automatic renewal clause.",
    "It quietly locks you in for another full year at a higher rent.",
    "Ask for a month to month option after the first year instead.",
    "Number two is the vague cleaning fee.",
    "If it doesn't say an exact amount, it can be anything they want.",
    "Ask them to write a fixed number into the lease, or remove it.",
    "Number three is the admin fee that renews every year.",
    "I paid forty dollars a month for three years before I noticed.",
    "That is one thousand four hundred and forty dollars for nothing.",
    "Why do landlords get away with this?",
    "Because almost nobody reads page seven of a lease.",
    "So read page seven. Seriously, read every page.",
    "Now let's talk about your deposit, because this one hurts.",
    "Take a video of every room the day you move in.",
    "Open every cupboard, film the floors, film the walls.",
    "Email the video to your landlord so there is a date on it.",
    "When you move out, they can't blame you for old damage.",
    "I got my full deposit back twice just because of that video.",
    "What about rent increases? Can they just raise it?",
    "In most places there are rules about notice and how much.",
    "Look up the rules for your city before you agree to anything.",
    "And always ask what the increase is based on.",
    "Here is the biggest mistake people make with rent.",
    "They spend more than thirty percent of their income on it.",
    "Rent above thirty percent leaves nothing for savings.",
    "Try to keep rent under thirty percent, even if the place is smaller.",
    "A smaller place close to work beats a big place far away.",
    "You save on travel, and you get hours of your week back.",
    "Let's do a quick money check together.",
    "If you earn three thousand a month, aim for rent under nine hundred.",
    "Can't find anything that cheap? Get a roommate for a year.",
    "One year of sharing can fund your whole emergency savings.",
    "Five things to check before you sign any lease.",
    "Check who pays for repairs, and how fast they must fix things.",
    "Check if you can sublet if your job moves you.",
    "Check the exact fees for ending the lease early.",
    "Check if pets, guests or home offices are restricted.",
    "And check the move out cleaning rules in writing.",
    "If you remember one thing today, remember this.",
    "A lease is a draft until you sign it.",
    "Ask for changes, politely, and get them in writing.",
    "That is it for today's episode.",
    "If this helped, follow for part two on buying your first home.",
    "Thanks for watching, and see you next week.",
]

ACCOUNTS = [
    ("instagram", "@moneywithmaya", "Finance EN", "America/New_York"),
    ("instagram", "@maya.saves", "Finance EN", "America/Chicago"),
    ("tiktok", "@maya.money", "Finance EN", "America/New_York"),
    ("tiktok", "@mayasaves.daily", "Finance EN", "America/Los_Angeles"),
    ("youtube", "Maya Money", "Finance EN", "America/New_York"),
    ("facebook", "Maya Money", "Finance EN", "America/New_York"),
    ("x", "@mayamoneytalk", "Finance EN", "America/New_York"),
    ("linkedin", "Maya Patel", "Professional", "America/New_York"),
    ("threads", "@moneywithmaya", "Finance EN", "America/New_York"),
]

SETTINGS = {
    "niche": "Personal finance for renters",
    "voice": "Friendly, direct, short sentences, no jargon",
    "audience": "Renters aged 20-35",
    "banned_topics": ["crypto"],
    "hashtags": ["moneytips", "renting"],
    "cta": "Follow for part 2.",
    "clip_min_s": 15,
    "clip_max_s": 55,
    "clip_target_s": 35,
    "max_clips": 8,
    "variants": 2,
    "auto_zoom": True,
    "emojis": True,
    "quiet_hours": True,
    "spacing_minutes": 30,
    "setup_done": True,
}


def _srt() -> tuple[str, float]:
    out, t = [], 1.0
    for i, line in enumerate(SCRIPT):
        d = 2.2 + len(line.split()) * 0.38
        a, b = t, t + d
        f = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)) % 1000:03d}"
        out.append(f"{i + 1}\n{f(a)} --> {f(b)}\n{line}\n")
        t = b + 0.35
    return "\n".join(out), t + 2.0


def _make_video(path: Path, seconds: float) -> None:
    font_b = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    vf = (
        f"drawtext=fontfile={font_b}:text='MONEY MINUTES':fontcolor=white@0.85:fontsize=64:x=(w-text_w)/2:y=h*0.38,"
        f"drawtext=fontfile={font}:text='Ep. 114 · Renting without getting ripped off':fontcolor=white@0.8:fontsize=30:x=(w-text_w)/2:y=h*0.52"
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"gradients=s=1280x720:c0=0x1d2b53:c1=0x7e2553:c2=0xff6f3c:c3=0x0b6e4f:nb_colors=4:speed=0.004:rate=25:duration={seconds:.1f}",
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{seconds:.1f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", str(path)],
        check=True,
    )


def _owner(s, email: str | None, password: str | None):
    from . import auth
    from .models import Role, User

    users = list(s.scalars(select(User).where(User.password_hash.is_not(None))))
    if users:
        return [u for u in users if u.is_admin] or users[:1], None
    email = auth.normalize_email(email or "demo@clipstar.app")
    password = password or secrets.token_urlsafe(9)
    u = User(email=email, name="Demo owner", role=Role.owner, is_admin=True, password_hash=auth.hash_password(password), prefs={"email": True})
    s.add(u)
    s.flush()
    return [u], (email, password)


def _drain(until, label: str, timeout_s: float = 3600) -> None:
    """Run queued jobs in this process (a running worker helps too) until `until()` is true."""
    from .pipeline import register_all
    from .worker import Worker

    register_all()
    w = Worker(f"demo-{uuid.uuid4().hex[:6]}")
    start = time.monotonic()
    last = 0.0
    while not until():
        if not w.run_once():
            time.sleep(0.5)
        if time.monotonic() - last > 15:
            last = time.monotonic()
            print(f"  … {label} ({int(time.monotonic() - start)} s)", flush=True)
        if time.monotonic() - start > timeout_s:
            raise SystemExit(f"Gave up waiting: {label}. Is ffmpeg installed and the database reachable?")


def seed(email: str | None = None, password: str | None = None) -> dict:
    from .learn.report import build_report
    from .models import (
        Account, AccountMetric, Asset, Batch, BatchStatus, Clip, ClipStatus, Membership, Post, PostMetric, PostStatus, Role, Video, VideoStatus, Workspace,
    )
    from .pipeline.package import compose
    from .pipeline.stages import start_pipeline
    from .platforms.simulated import Simulated
    from .storage import get_storage

    rnd = random.Random(114)
    now = datetime.now(timezone.utc)
    st = get_storage()

    # 1. workspace, owner, accounts
    with session_scope() as s:
        owners, login = _owner(s, email, password)
        ws = s.scalar(select(Workspace).where(Workspace.name == NAME))
        if ws is not None:
            raise SystemExit(f'A workspace called "{NAME}" already exists. Delete it in Settings → This workspace to seed again.')
        first = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
        ws = Workspace(name=NAME, settings=dict(SETTINGS))
        s.add(ws)
        s.flush()
        for u in owners:
            s.add(Membership(user_id=u.id, workspace_id=ws.id, role=Role.owner, prefs={"email": True}))
            if u.workspace_id is None:
                u.workspace_id = ws.id
        if first is not None and first.id != ws.id and not s.scalar(select(Video.id).where(Video.workspace_id == first.id).limit(1)) and first.name == "My workspace":
            pass  # leave an empty default workspace alone
        accounts = []
        for platform, handle, group, tz in ACCOUNTS:
            a = Account(workspace_id=ws.id, platform=platform, handle=handle, group_name=group, timezone=tz, connection="simulated", posting_start="08:00", posting_end="22:00", daily_cap=4, language="English")
            s.add(a)
            accounts.append(a)
        s.flush()
        ws_id, account_ids = ws.id, [a.id for a in accounts]

        # 2. the episode, through the real pipeline
        srt, seconds = _srt()
        v = Video(workspace_id=ws_id, title="Ep. 114 · Renting without getting ripped off", source_filename="money-minutes-ep114.mp4")
        s.add(v)
        s.flush()
        vid = v.id
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ep.mp4"
            print("Making the demo episode…", flush=True)
            _make_video(src, seconds)
            master = st.rel(vid, "master.mp4")
            st.abs(master).parent.mkdir(parents=True, exist_ok=True)
            st.abs(master).write_bytes(src.read_bytes())
        cap = st.rel(vid, "captions.srt")
        st.abs(cap).write_text(srt, encoding="utf-8")
        s.add(Asset(video_id=vid, kind="master", path=master, size_bytes=st.abs(master).stat().st_size, meta={"filename": v.source_filename}))
        s.add(Asset(video_id=vid, kind="captions", path=cap, size_bytes=len(srt), meta={"filename": "ep114.srt"}))
        v.size_bytes = st.abs(master).stat().st_size
        start_pipeline(s, v)

    def ready():
        with session_scope() as s2:
            v2 = s2.get(Video, vid)
            if v2.status == VideoStatus.failed:
                raise SystemExit(f"Processing failed: {v2.error}")
            return v2.status == VideoStatus.ready

    print("Processing it (moments, 9:16 clips with captions, post text)…", flush=True)
    _drain(ready, "processing the episode")

    # 3. two weeks of history on practice accounts
    sim = Simulated()
    with session_scope() as s:
        clips = list(s.scalars(select(Clip).where(Clip.video_id == vid).order_by(Clip.score.desc())))
        if len(clips) < 3:
            raise SystemExit("The pipeline found too few clips for a demo.")
        posted, upcoming, waiting = clips[: max(3, len(clips) - 2)], clips[:2], clips[-2:]
        for c in clips[:-1]:
            c.status = ClipStatus.approved
        accs = [s.get(Account, a) for a in account_ids]
        hist = Batch(workspace_id=ws_id, name="Ep. 114 · first wave", status=BatchStatus.finished, variations="ab", approved_at=now - timedelta(days=13))
        s.add(hist)
        s.flush()
        for k, c in enumerate(posted):
            for j, a in enumerate(accs):
                when = now - timedelta(days=12 - k * 2 + rnd.random(), hours=rnd.randint(0, 6))
                variant = "AB"[j % 2] if len(c.variants or []) > 1 else "A"
                cp = (c.copy or {}).get(a.platform.value) or {}
                p = Post(batch_id=hist.id, account_id=a.id, clip_id=c.id, variant=variant, caption=compose(cp, a.platform.value) if cp else c.title,
                         scheduled_at=when, published_at=when, status=PostStatus.published, remote_id=f"sim-{uuid.uuid4().hex[:10]}", attempts=1, metrics_step=4)
                s.add(p)
                s.flush()
                v_ = next((x for x in c.variants or [] if x.get("id") == variant), {})
                hints = {"hook_text": v_.get("hook") or c.hook, "duration_s": c.end_s - c.start_s, "variant": variant}
                m = sim.post_metrics(None, None, a.remote_id or str(a.id), p.remote_id, when, hints)
                boost = {"tiktok": 1.8, "instagram": 1.4, "youtube": 1.2, "facebook": 0.7, "x": 0.5, "linkedin": 0.4, "threads": 0.45}.get(a.platform.value, 1)
                m = {key: (int(val * boost) if isinstance(val, int) else val) for key, val in m.items()}
                hours = (now - when).total_seconds() / 3600
                for h, frac in ((1, 0.08), (24, 0.55), (72, 0.85), (168, 1.0)):
                    if h <= hours:
                        s.add(PostMetric(post_id=p.id, hours=h, **{key: (int(val * frac) if isinstance(val, int) else val) for key, val in m.items() if key in ("views", "likes", "comments", "shares", "saves", "watch_pct", "avg_watch_s", "follows")}))
                p.metrics = {**m, "hours": round(hours, 1), "updated_at": now.isoformat()}
        for a in accs:
            base = sim.account_followers(None, None, str(a.id))
            for d in range(14, -1, -1):
                s.add(AccountMetric(account_id=a.id, followers=int(base * (1 + 0.012 * (14 - d))), at=now - timedelta(days=d)))
            a.metrics_at = now

        # 4. what's next: scheduled posts this week, and a rule-made batch waiting for approval
        nxt = Batch(workspace_id=ws_id, name="Ep. 114 · second wave", status=BatchStatus.running, variations="ab", approved_at=now)
        wait = Batch(workspace_id=ws_id, name="Auto-post rule · Ep. 114 leftovers", status=BatchStatus.awaiting, origin=f"rule:demo:{vid}", variations="off")
        s.add_all([nxt, wait])
        s.flush()
        for k, c in enumerate(upcoming):
            for j, a in enumerate(accs[:6]):
                when = now + timedelta(days=1 + k * 2, hours=2 + j * 0.6)
                cp = (c.copy or {}).get(a.platform.value) or {}
                s.add(Post(batch_id=nxt.id, account_id=a.id, clip_id=c.id, variant="AB"[j % 2] if len(c.variants or []) > 1 else "A", caption=compose(cp, a.platform.value) if cp else c.title, scheduled_at=when, status=PostStatus.scheduled))
        for k, c in enumerate(waiting[:1]):
            for j, a in enumerate(accs[:4]):
                when = now + timedelta(days=4, hours=j)
                cp = (c.copy or {}).get(a.platform.value) or {}
                s.add(Post(batch_id=wait.id, account_id=a.id, clip_id=c.id, variant="A", caption=compose(cp, a.platform.value) if cp else c.title, scheduled_at=when, status=PostStatus.held))

    # 5. comments on recent posts, sorted with drafted replies
    from .engage import service as eng

    print("Collecting practice comments…", flush=True)
    eng.dispatch_sync(force_workspace=ws_id)
    from .models import Job, JobStatus

    def no_jobs():
        with session_scope() as s2:
            return not s2.scalar(select(Job.id).where(Job.status.in_([JobStatus.queued, JobStatus.running]), Job.kind.like("comments.%")).limit(1))

    _drain(no_jobs, "sorting comments", timeout_s=600)

    # 6. weekly report (also trains the learned scoring on the history)
    with session_scope() as s:
        w = s.get(Workspace, ws_id, with_for_update=True)
        build_report(s, w)
    print(f'Done: "{NAME}" is ready.', flush=True)
    return {"workspace_id": str(ws_id), "login": login}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m clipstar.demo", description="Fill clip_star with a realistic demo (practice accounts, nothing is posted).")
    ap.add_argument("--email", help="owner email, only used on a fresh install")
    ap.add_argument("--password", help="owner password, only used on a fresh install (default: generated and printed)")
    a = ap.parse_args(argv)
    res = seed(a.email, a.password)
    if res["login"]:
        print(f"Sign in with: {res['login'][0]}  /  {res['login'][1]}")
    else:
        print("Sign in with your existing owner account and pick the demo workspace from the menu at the bottom of the sidebar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
