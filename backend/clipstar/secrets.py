"""Encryption for app secrets and account tokens (Fernet: AES-128-CBC + HMAC).

The key comes from CLIPSTAR_SECRET_KEY, or is created once in <storage_dir>/.secret_key (mode 600).
Back that file up: without it, saved account connections can't be read and must be reconnected.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings
from .errors import PermanentError


def current_key() -> str:
    """The encryption key in use (created on first use). Needed in backups: without it, saved logins can't be read."""
    st = get_settings()
    key = st.secret_key
    if not key:
        path = st.storage_dir.resolve() / ".secret_key"
        if path.exists():
            key = path.read_text().strip()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key().decode()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
    return key


@lru_cache
def _fernet() -> Fernet:
    key = current_key()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise PermanentError("bad secret key", user_message="CLIPSTAR_SECRET_KEY is not a valid key. Generate one with: python -m clipstar.secrets") from e


def encrypt(data: dict | str) -> str:
    raw = data if isinstance(data, str) else json.dumps(data)
    return _fernet().encrypt(raw.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise PermanentError("cannot decrypt", user_message="A saved secret can't be read (the encryption key changed). Reconnect the account or re-enter the app keys.") from e


def decrypt_json(token: str) -> dict:
    return json.loads(decrypt(token))


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
