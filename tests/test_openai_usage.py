"""OpenAI Codex responses header 解析與抓取工具測試。"""
import base64
import json

import tools.openai_usage as openai_usage
from tools.openai_usage import (
    fetch_all_usage,
    fetch_usage,
    list_credentials,
    load_credentials,
    parse_codex_headers,
)


REAL_HEADERS = {
    "x-codex-plan-type": "prolite",
    "x-codex-primary-used-percent": "3",
    "x-codex-primary-window-minutes": "10080",
    "x-codex-primary-reset-at": "1786932438",
    "x-codex-secondary-window-minutes": "0",
}


def _auth_file(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps({"openai": {"access": "access-token", "accountId": "account-id"}}),
        encoding="utf-8",
    )
    return path


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fake_jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_list_credentials_reads_built_in_codex_and_opencode(tmp_path, monkeypatch):
    codex_token = _fake_jwt({
        "https://api.openai.com/profile": {"email": "kevin.systemcom@example.com"},
    })
    opencode_token = _fake_jwt({"email": "interagent.dev01@example.com"})
    codex = _write_json(tmp_path / "codex.json", {
        "tokens": {"access_token": codex_token, "account_id": "codex-account"},
    })
    opencode = _write_json(tmp_path / "opencode.json", {
        "openai": {"access": opencode_token, "accountId": "opencode-account"},
    })
    monkeypatch.setattr(openai_usage, "CODEX_AUTH_PATH", codex)
    monkeypatch.setattr(openai_usage, "OPENCODE_AUTH_PATH", opencode)

    credentials = list_credentials(config_path=tmp_path / "missing-config.json")

    assert [item["account_id"] for item in credentials] == [
        "codex-account",
        "opencode-account",
    ]
    assert [item["name"] for item in credentials] == [
        "kevin.systemcom",
        "interagent.dev01",
    ]
    assert [item["source"] for item in credentials] == [str(codex), str(opencode)]


def test_list_credentials_dedupes_by_account_id(tmp_path, monkeypatch):
    codex_token = _fake_jwt({"email": "first@example.com"})
    opencode_token = _fake_jwt({"email": "second@example.com"})
    codex = _write_json(tmp_path / "codex.json", {
        "tokens": {"access_token": codex_token, "account_id": "same-account"},
    })
    opencode = _write_json(tmp_path / "opencode.json", {
        "openai": {"access": opencode_token, "accountId": "same-account"},
    })
    monkeypatch.setattr(openai_usage, "CODEX_AUTH_PATH", codex)
    monkeypatch.setattr(openai_usage, "OPENCODE_AUTH_PATH", opencode)

    credentials = list_credentials(config_path=tmp_path / "missing-config.json")

    assert len(credentials) == 1
    assert credentials[0]["account_id"] == "same-account"
    assert credentials[0]["name"] == "first"


def test_list_credentials_skips_bad_json_entry(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    token = _fake_jwt({"email": "valid@example.com"})
    valid = _write_json(tmp_path / "valid-opencode.json", {
        "openai": {"access": token, "accountId": "valid-account"},
    })
    config = _write_json(tmp_path / "openai_accounts.json", [
        {"auth": str(bad), "format": "codex"},
        {"auth": str(valid), "format": "opencode"},
    ])

    credentials = list_credentials(config_path=config)

    assert len(credentials) == 1
    assert credentials[0]["account_id"] == "valid-account"
    assert credentials[0]["name"] == "valid"


def test_list_credentials_reads_config_list_without_home_access(tmp_path):
    token = _fake_jwt({"email": "configured@example.com"})
    auth_dir = tmp_path / "fake-opencode"
    auth_dir.mkdir()
    auth = _write_json(auth_dir / "auth.json", {
        "openai": {"access": token, "accountId": "configured-account"},
    })
    config = _write_json(tmp_path / "openai_accounts.json", [{"auth": str(auth)}])

    credentials = list_credentials(config_path=config)

    assert len(credentials) == 1
    assert credentials[0]["account_id"] == "configured-account"
    assert credentials[0]["name"] == "configured"
    assert credentials[0]["source"] == str(auth)


def test_fetch_all_usage_skips_failed_account(tmp_path):
    failed_token = _fake_jwt({"email": "failed@example.com"})
    good_token = _fake_jwt({"email": "good@example.com"})
    failed = _write_json(tmp_path / "failed.json", {
        "tokens": {"access_token": failed_token, "account_id": "failed-account"},
    })
    good = _write_json(tmp_path / "good.json", {
        "tokens": {"access_token": good_token, "account_id": "good-account"},
    })
    config = _write_json(tmp_path / "openai_accounts.json", [
        {"auth": str(failed), "format": "codex"},
        {"auth": str(good), "format": "codex"},
    ])

    class Response:
        def __init__(self, status_code, headers):
            self.status_code = status_code
            self.headers = headers

        def iter_content(self, chunk_size=8192):
            yield b"data: ok"

        def close(self):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            account_id = kwargs["headers"]["chatgpt-account-id"]
            if account_id == "good-account":
                return Response(200, {
                    "x-codex-primary-used-percent": "18",
                    "x-codex-primary-reset-at": "1789435507",
                })
            return Response(500, {})

    results = fetch_all_usage(config_path=config, http=HTTP())

    assert len(results) == 1
    assert results[0]["account_id"] == "good-account"
    assert results[0]["name"] == "good"
    assert results[0]["used_pct"] == 18.0


def test_load_credentials_uses_codex_when_only_codex_exists(tmp_path):
    codex = _write_json(tmp_path / "codex.json", {
        "tokens": {"access_token": "codex-token", "account_id": "codex-account"},
    })

    assert load_credentials(codex, tmp_path / "missing.json") == ("codex-token", "codex-account")


def test_load_credentials_uses_opencode_when_only_opencode_exists(tmp_path):
    opencode = _write_json(tmp_path / "opencode.json", {
        "openai": {"access": "opencode-token", "accountId": "opencode-account"},
    })

    assert load_credentials(tmp_path / "missing.json", opencode) == ("opencode-token", "opencode-account")


def test_load_credentials_prefers_codex_over_opencode(tmp_path):
    codex = _write_json(tmp_path / "codex.json", {
        "tokens": {"access_token": "codex-token", "account_id": "codex-account"},
    })
    opencode = _write_json(tmp_path / "opencode.json", {
        "openai": {"access": "opencode-token", "accountId": "opencode-account"},
    })

    assert load_credentials(codex, opencode) == ("codex-token", "codex-account")


def test_load_credentials_bad_codex_falls_back_to_opencode(tmp_path):
    codex = tmp_path / "codex.json"
    codex.write_text("{not json", encoding="utf-8")
    opencode = _write_json(tmp_path / "opencode.json", {
        "openai": {"access": "opencode-token", "accountId": "opencode-account"},
    })

    assert load_credentials(codex, opencode) == ("opencode-token", "opencode-account")


def test_load_credentials_missing_files_returns_none_pair(tmp_path):
    assert load_credentials(tmp_path / "missing-codex.json", tmp_path / "missing-opencode.json") == (None, None)


def test_load_credentials_uses_jwt_account_id_when_missing_from_file(tmp_path):
    token = _fake_jwt({
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc-test"},
    })
    codex = _write_json(tmp_path / "codex.json", {
        "tokens": {"access_token": token},
    })

    assert load_credentials(codex, tmp_path / "missing.json") == (token, "acc-test")


def test_parse_codex_headers_real_headers():
    res = parse_codex_headers(REAL_HEADERS)

    assert res == {
        "used_pct": 3.0,
        "resets_at_epoch": 1786932438,
        "plan": "prolite",
    }


def test_parse_codex_headers_case_insensitive():
    res = parse_codex_headers({
        "X-Codex-Plan-Type": "prolite",
        "X-CODEX-PRIMARY-USED-PERCENT": "3",
        "x-Codex-Primary-Reset-At": "1786932438",
    })

    assert res["used_pct"] == 3.0
    assert res["resets_at_epoch"] == 1786932438
    assert res["plan"] == "prolite"


def test_parse_codex_headers_missing_and_bad_values_are_none():
    res = parse_codex_headers({
        "x-codex-primary-used-percent": "not-a-number",
        "x-codex-primary-reset-at": "not-an-epoch",
    })

    assert res["used_pct"] is None
    assert res["resets_at_epoch"] is None
    assert res["plan"] is None


def test_parse_codex_headers_empty_dict_all_none():
    assert parse_codex_headers({}) == {
        "used_pct": None,
        "resets_at_epoch": None,
        "plan": None,
    }


def test_fetch_usage_http_exception_returns_none(tmp_path):
    class RaisingHTTP:
        def post(self, *args, **kwargs):
            raise RuntimeError("boom")

    assert fetch_usage(auth_path=_auth_file(tmp_path), http=RaisingHTTP()) is None


def test_fetch_usage_non_200_returns_none(tmp_path):
    class Response:
        status_code = 429
        headers = {}

        def iter_content(self, chunk_size=8192):
            yield b"error"

        def close(self):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            return Response()

    assert fetch_usage(auth_path=_auth_file(tmp_path), http=HTTP()) is None


def test_fetch_usage_429_uses_valid_usage_headers(tmp_path):
    class Response:
        status_code = 429
        headers = {
            "x-codex-primary-used-percent": "100",
            "x-codex-primary-reset-at": "1789435507",
        }

        def iter_content(self, chunk_size=8192):
            yield b'{"error":{"type":"usage_limit_reached"}}'

        def close(self):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            return Response()

    res = fetch_usage(auth_path=_auth_file(tmp_path), http=HTTP())

    assert res is not None
    assert res["used_pct"] == 100.0
    assert res["resets_at_epoch"] == 1789435507


def test_fetch_usage_200_keeps_header_parse_behavior(tmp_path):
    class Response:
        status_code = 200
        headers = dict(REAL_HEADERS)

        def iter_content(self, chunk_size=8192):
            yield b"data: ok"

        def close(self):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            return Response()

    res = fetch_usage(auth_path=_auth_file(tmp_path), http=HTTP())

    assert res is not None
    assert res["used_pct"] == 3.0
    assert res["resets_at_epoch"] == 1786932438
    assert res["plan"] == "prolite"


def test_fetch_usage_missing_auth_file_returns_none(tmp_path):
    assert fetch_usage(auth_path=tmp_path / "missing-auth.json", http=object()) is None
