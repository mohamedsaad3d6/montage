"""API keys, read only from the user's own keys file (outside the engine). Values are never printed or logged.
Known keys and each site's rules: see NOTES.md. Since 19 Oct 2026 the only footage source with a key is Pixabay (the
Pexels, DVIDS and Smithsonian slots were removed with their sources; a value left in the keys file is simply not read)."""
import json

from .paths import KEYS


def get(name):
    """the key's value, or None when the file or the key is missing/empty"""
    try:
        v = json.loads(KEYS.read_text()).get(name)
    except (OSError, ValueError):
        return None
    return v.strip() if isinstance(v, str) and v.strip() else None


def status(names=("pixabay_api_key",)):
    """{name: 'present' | 'missing'} for logs (never the value)"""
    return {n: ("present" if get(n) else "missing") for n in names}


# the keys the engine knows (web panel phase 8: added or removed from the panel; the value is never shown back)
KNOWN = {"pixabay_api_key": ("Pixabay", "stock video and photos (free key: pixabay.com/api/docs)"),
         "magnific_api_key": ("Magnific", "stock videos for the channels that turn it on (paid plan; magnific.com → Organization → API keys)")}


def _all():
    try:
        return json.loads(KEYS.read_text())
    except (OSError, ValueError):
        return {}


def set_key(name, value):
    """store one key in the user's keys file (only this user can read it); the value is never printed"""
    import os
    if name not in KNOWN:
        raise ValueError(f"unknown key {name!r}; known: {', '.join(KNOWN)}")
    value = (value or "").strip()
    if not value or len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError("a key is one word with no spaces")
    d = _all()
    d[name] = value
    KEYS.parent.mkdir(parents=True, exist_ok=True)
    tmp = KEYS.with_name(KEYS.name + ".part")
    tmp.write_text(json.dumps(d, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(KEYS)


def remove_key(name):
    import os
    d = _all()
    if name in d:
        d.pop(name)
        tmp = KEYS.with_name(KEYS.name + ".part")
        tmp.write_text(json.dumps(d, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(KEYS)
