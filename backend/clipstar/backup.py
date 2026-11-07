"""Backups: the database, the encryption key and (optionally) media, in one .tar.gz file.

    python -m clipstar.backup create [--media] [--out DIR]
    python -m clipstar.backup list
    python -m clipstar.backup restore FILE --yes      # stop the API and workers first

A backup contains the encryption key, so it can unlock saved platform logins: keep it somewhere private.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from .config import get_settings
from .errors import PermanentError

NAME_RE = re.compile(r"^clipstar-backup-\d{8}-\d{6}(-media)?\.tar\.gz$")


def _pg_env() -> dict:
    """libpq settings from the database URL, passed as environment (never on the command line, where others could see the password)."""
    u = make_url(get_settings().database_url)
    env = {**os.environ}
    for k, v in (("PGHOST", u.host), ("PGPORT", u.port), ("PGUSER", u.username), ("PGPASSWORD", u.password), ("PGDATABASE", u.database)):
        if v is not None:
            env[k] = str(v)
    return env


def backup_dir(out: Path | None = None) -> Path:
    d = out or get_settings().backup_dir or (get_settings().storage_dir / "backups")
    d = Path(d).resolve()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _revision() -> str | None:
    from sqlalchemy import text

    from .db import get_engine

    try:
        with get_engine().connect() as c:
            return c.execute(text("select version_num from alembic_version")).scalar()
    except Exception:
        return None


def create(media: bool = False, out: Path | None = None) -> Path:
    from .secrets import current_key

    st = get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir(out) / f"clipstar-backup-{stamp}{'-media' if media else ''}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="clipstar-backup-") as tmp:
        t = Path(tmp)
        dump = t / "database.dump"
        try:
            r = subprocess.run([st.pg_dump_bin, "--format=custom", "--no-owner", "--file", str(dump)], env=_pg_env(), capture_output=True, text=True, timeout=3600)
        except FileNotFoundError as e:
            raise PermanentError(str(e), user_message="pg_dump isn't installed on this machine. Install the PostgreSQL client tools (same major version as the server).") from e
        if r.returncode != 0:
            raise PermanentError(r.stderr[-2000:], user_message=f"The database backup failed: {r.stderr.strip()[-300:]}")
        (t / "secret_key").write_text(current_key())
        vapid = st.storage_dir.resolve() / ".vapid_key"  # push signing key: keeps phones subscribed after a restore
        if vapid.exists() and not st.vapid_private_key:
            shutil.copyfile(vapid, t / "vapid_key")
        manifest = {"format": 1, "created_at": datetime.now(timezone.utc).isoformat(), "alembic_revision": _revision(), "media": media}
        (t / "manifest.json").write_text(json.dumps(manifest, indent=2))
        part = dest.with_name("." + dest.name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        try:
            with tarfile.open(part, "w:gz") as tar:
                for name in ("manifest.json", "database.dump", "secret_key", "vapid_key"):
                    if (t / name).exists():
                        tar.add(t / name, arcname=name)
                if media:
                    videos = st.storage_dir.resolve() / "videos"
                    if videos.exists():
                        tar.add(videos, arcname="media/videos", filter=lambda ti: None if Path(ti.name).name.startswith(".tmp-") else ti)
            os.replace(part, dest)
        finally:
            if part.exists():
                part.unlink()
    return dest


def list_backups(out: Path | None = None) -> list[dict]:
    d = backup_dir(out)
    items = []
    for p in sorted(d.iterdir(), reverse=True):
        if NAME_RE.match(p.name):
            stt = p.stat()
            items.append({"name": p.name, "size_bytes": stt.st_size, "created_at": datetime.fromtimestamp(stt.st_mtime, timezone.utc).isoformat(), "media": p.name.endswith("-media.tar.gz")})
    return items


def prune(keep: int, out: Path | None = None) -> int:
    """Keep the newest `keep` backups (with and without media counted separately)."""
    removed = 0
    for media in (False, True):
        olds = [b for b in list_backups(out) if b["media"] == media][keep:]
        for b in olds:
            (backup_dir(out) / b["name"]).unlink(missing_ok=True)
            removed += 1
    return removed


def path_of(name: str, out: Path | None = None) -> Path:
    if not NAME_RE.match(name):
        raise ValueError("Not a backup file name.")
    p = backup_dir(out) / name
    if not p.exists():
        raise FileNotFoundError(name)
    return p


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        n = Path(m.name)
        if n.is_absolute() or ".." in n.parts or m.issym() or m.islnk() or m.isdev():
            raise PermanentError(m.name, user_message=f"Refusing to restore: unsafe path in backup ({m.name}).")
        yield m


def restore(file: Path) -> dict:
    st = get_settings()
    with tempfile.TemporaryDirectory(prefix="clipstar-restore-") as tmp:
        t = Path(tmp)
        with tarfile.open(file, "r:gz") as tar:
            tar.extractall(t, members=list(_safe_members(tar)))
        manifest = json.loads((t / "manifest.json").read_text())
        if manifest.get("format") != 1:
            raise PermanentError("format", user_message="This backup was made by a newer clip_star. Upgrade first.")
        try:
            r = subprocess.run([st.pg_restore_bin, "--clean", "--if-exists", "--no-owner", "--single-transaction", "--dbname", _pg_env()["PGDATABASE"], str(t / "database.dump")], env=_pg_env(), capture_output=True, text=True, timeout=3600)
        except FileNotFoundError as e:
            raise PermanentError(str(e), user_message="pg_restore isn't installed on this machine.") from e
        if r.returncode != 0:
            raise PermanentError(r.stderr[-2000:], user_message=f"Restoring the database failed: {r.stderr.strip()[-300:]}")
        key = (t / "secret_key").read_text().strip()
        note = ""
        if st.secret_key:
            if st.secret_key != key:
                note = "CLIPSTAR_SECRET_KEY differs from the backup's key: set it to the key in this backup, or connected accounts must be reconnected."
        else:
            kp = st.storage_dir.resolve() / ".secret_key"
            kp.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
        if (t / "vapid_key").exists() and not st.vapid_private_key:
            vp = st.storage_dir.resolve() / ".vapid_key"
            fd = os.open(vp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write((t / "vapid_key").read_text())
        if manifest.get("media") and (t / "media" / "videos").exists():
            dest = st.storage_dir.resolve() / "videos"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(t / "media" / "videos", dest)
    return {"restored_from": str(file), "created_at": manifest.get("created_at"), "media": bool(manifest.get("media")), "note": note}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m clipstar.backup", description="Back up or restore clip_star.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="make a backup now")
    c.add_argument("--media", action="store_true", help="also include videos and clips (can be large)")
    c.add_argument("--out", type=Path, help="folder to write to (default: CLIPSTAR_BACKUP_DIR or <storage>/backups)")
    sub.add_parser("list", help="list backups")
    r = sub.add_parser("restore", help="restore a backup (stop the API and workers first)")
    r.add_argument("file", type=Path)
    r.add_argument("--yes", action="store_true", help="confirm: this replaces the current database")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "create":
            p = create(media=a.media, out=a.out)
            print(f"Backup written: {p}\nIt contains the encryption key. Store it somewhere private.")
        elif a.cmd == "list":
            for b in list_backups():
                print(f"{b['created_at']}  {b['size_bytes'] / 1024**2:8.1f} MB  {b['name']}")
        else:
            if not a.yes:
                print("This replaces the current database (and media, if the backup has it). Stop the API and workers, then run again with --yes.")
                return 2
            res = restore(a.file)
            print(f"Restored backup from {res['created_at']}. Now run: alembic upgrade head, then start clip_star.")
            if res["note"]:
                print("Note: " + res["note"])
    except PermanentError as e:
        print(e.user_message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
