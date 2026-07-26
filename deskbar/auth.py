import json
import time
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
_cache: dict[str, tuple[str, float]] = {}


class AuthError(Exception):
    pass


def load_accounts(dir: Path) -> list[dict]:
    out = []
    for p in sorted(dir.glob("*.json")):
        try:
            acc = json.loads(p.read_text(encoding="utf-8"))
            if acc.get("email") and acc.get("refresh_token"):
                out.append(acc)
        except (OSError, ValueError):
            continue
    return out


def get_access_token(acc: dict, http_post=requests.post) -> str:
    email = acc["email"]
    tok = _cache.get(email)
    if tok and tok[1] > time.time() + 60:
        return tok[0]
    resp = http_post(TOKEN_URL, data={
        "client_id": acc["client_id"],
        "client_secret": acc["client_secret"],
        "refresh_token": acc["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=15)
    body = resp.json()
    if resp.status_code != 200 or "access_token" not in body:
        raise AuthError(f"{email}: {body.get('error', resp.status_code)}")
    _cache[email] = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
    return _cache[email][0]
