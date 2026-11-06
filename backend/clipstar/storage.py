"""File storage. Local disk by default; paths stored in the DB are relative to the root."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

from .config import get_settings


class LocalStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or get_settings().storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("Path escapes storage root")
        return p

    def video_dir(self, video_id: uuid.UUID) -> str:
        return f"videos/{video_id}"

    def rel(self, video_id: uuid.UUID, name: str) -> str:
        return f"{self.video_dir(video_id)}/{name}"

    def tmp_path_for(self, rel: str) -> Path:
        """A temp file next to the final path; rename it into place when complete (atomic)."""
        final = self.abs(rel)
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=final.suffix, dir=final.parent)
        os.close(fd)
        return Path(tmp)

    def commit_tmp(self, tmp: Path, rel: str) -> int:
        final = self.abs(rel)
        os.replace(tmp, final)
        return final.stat().st_size

    def save_stream(self, src: BinaryIO, rel: str, max_bytes: int, chunk: int = 8 * 1024 * 1024) -> int:
        tmp = self.tmp_path_for(rel)
        size = 0
        try:
            with open(tmp, "wb") as out:
                while True:
                    buf = src.read(chunk)
                    if not buf:
                        break
                    size += len(buf)
                    if size > max_bytes:
                        raise ValueError(f"File is larger than the {max_bytes // 1024**3} GB limit.")
                    out.write(buf)
            return self.commit_tmp(tmp, rel)
        finally:
            if tmp.exists():
                tmp.unlink()

    def write_json(self, rel: str, data) -> int:
        tmp = self.tmp_path_for(rel)
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return self.commit_tmp(tmp, rel)
        finally:
            if tmp.exists():
                tmp.unlink()

    def read_json(self, rel: str):
        return json.loads(self.abs(rel).read_text(encoding="utf-8"))

    def exists(self, rel: str) -> bool:
        return self.abs(rel).exists()

    def delete_video(self, video_id: uuid.UUID) -> None:
        shutil.rmtree(self.abs(self.video_dir(video_id)), ignore_errors=True)

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free


def get_storage() -> LocalStorage:
    return LocalStorage()
