"""Per-profile Fernet encryption for sensitive cache values"""

from pathlib import Path

_cache: dict = {}


def _keypath(profile: str) -> Path:
    return Path.home() / ".brickbreaker" / f"{profile}.key"


def _get_fernet(profile: str):
    if profile in _cache:
        return _cache[profile]
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    p = _keypath(profile)
    if p.exists():
        key = p.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(key)
        try:
            p.chmod(0o600)
        except Exception:
            pass
    f = Fernet(key)
    _cache[profile] = f
    return f


def encrypt(profile: str, value: str) -> str:
    """Encrypt a string value. Returns 'enc:<token>' or plaintext if crypto unavailable."""
    if not value:
        return value
    f = _get_fernet(profile)
    if f is None:
        return value
    return "enc:" + f.encrypt(value.encode()).decode()


def decrypt(profile: str, value: str) -> str:
    """Decrypt a value. Handles both encrypted ('enc:...') and legacy plaintext."""
    if not value or not value.startswith("enc:"):
        return value
    f = _get_fernet(profile)
    if f is None:
        return value
    try:
        return f.decrypt(value[4:].encode()).decode()
    except Exception:
        return value
