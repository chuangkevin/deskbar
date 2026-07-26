import json
import pytest
from deskbar import auth

ACC = {"email": "a@x.com", "refresh_token": "rt", "client_id": "cid", "client_secret": "cs"}


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload

    def json(self):
        return self._p


def test_get_access_token_success_and_cache():
    calls = []

    def post(url, data=None, timeout=None):
        calls.append(data)
        return FakeResp(200, {"access_token": "tok1", "expires_in": 3600})

    auth._cache.clear()
    assert auth.get_access_token(ACC, http_post=post) == "tok1"
    assert auth.get_access_token(ACC, http_post=post) == "tok1"  # 第二次走快取
    assert len(calls) == 1
    assert calls[0]["grant_type"] == "refresh_token"


def test_invalid_grant_raises():
    def post(url, data=None, timeout=None):
        return FakeResp(400, {"error": "invalid_grant"})

    auth._cache.clear()
    with pytest.raises(auth.AuthError):
        auth.get_access_token(ACC, http_post=post)


def test_load_accounts_reads_json_files(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(ACC), encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
    accs = auth.load_accounts(tmp_path)
    assert len(accs) == 1 and accs[0]["email"] == "a@x.com"


def test_load_accounts_skips_broken(tmp_path):
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert auth.load_accounts(tmp_path) == []
