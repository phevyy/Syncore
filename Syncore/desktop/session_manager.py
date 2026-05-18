"""
Session Manager - Otomatik Giriş için Şifreli Oturum Dosyası
=============================================================
v1: username + password (Argon2 vault için)
v2: username + secret_b64 (SHA-256 vault için, mobile-first)
"""

import os
import base64
import hashlib
import getpass
import platform
from pathlib import Path
from typing import Optional, Dict

from cryptography.fernet import Fernet, InvalidToken

_SESSION_FILE = Path.home() / ".password_vault" / ".session"


def _machine_key() -> bytes:
    seed = f"{platform.node()}|{getpass.getuser()}|pvault-2fa"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def save_session(username: str, password: str) -> bool:
    """v1: kullanıcı adı + şifre (Argon2 vault)."""
    try:
        _SESSION_FILE.parent.mkdir(exist_ok=True)
        f = Fernet(_machine_key())
        payload = f"v1\x00{username}\x00{password}".encode("utf-8")
        _SESSION_FILE.write_bytes(f.encrypt(payload))
        return True
    except Exception:
        return False


def save_session_v2(username: str, secret_b64: str) -> bool:
    """v2: kullanıcı adı + SHA-256(password) base64 (SHA-256 vault, mobile-first)."""
    try:
        _SESSION_FILE.parent.mkdir(exist_ok=True)
        f = Fernet(_machine_key())
        payload = f"v2\x00{username}\x00{secret_b64}".encode("utf-8")
        _SESSION_FILE.write_bytes(f.encrypt(payload))
        return True
    except Exception:
        return False


def load_session() -> Optional[Dict]:
    """
    Kayıtlı oturumu yükler.
    Returns: {'format': 'v1'|'v2', 'username': str, 'password': str|None, 'secret_b64': str|None}
    """
    if not _SESSION_FILE.exists():
        return None
    try:
        f = Fernet(_machine_key())
        raw = f.decrypt(_SESSION_FILE.read_bytes()).decode("utf-8")
        parts = raw.split("\x00", 2)

        if len(parts) == 3 and parts[0] in ('v1', 'v2'):
            fmt, username, value = parts
            if not username or not value:
                return None
            if fmt == 'v2':
                return {'format': 'v2', 'username': username,
                        'password': None, 'secret_b64': value}
            else:
                return {'format': 'v1', 'username': username,
                        'password': value, 'secret_b64': None}

        # Eski format (v1 etiketi olmadan): username\x00password
        if len(parts) >= 2:
            username, password = parts[0], parts[1]
            if username and password:
                return {'format': 'v1', 'username': username,
                        'password': password, 'secret_b64': None}
    except (InvalidToken, ValueError, Exception):
        pass
    return None


def clear_session() -> None:
    try:
        _SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass
