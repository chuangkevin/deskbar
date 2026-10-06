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


def test_newapi_usage_filters_channel_and_maps_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    config = _write_json(tmp_path / "accounts.json", [{"format": "newapi-usage-api"}])
    calls = []

    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return {"data": self.data}

    class HTTP:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/api/channel/?p=1&page_size=100"):
                return Response({"items": [
                    {"id": 13, "type": 57, "status": 1},
                    {"id": 14, "type": 57, "status": 2},
                    {"id": 15, "type": 99, "status": 1},
                ]})
            return Response({"account_id": "acc-13", "email": "interagent.dev01@example.com",
                             "plan_type": "pro", "rate_limit": {
                                 "primary_window": {"limit_window_seconds": 604800, "used_percent": 40, "reset_at": 1791580397},
                                 "secondary_window": {"limit_window_seconds": 18000, "used_percent": 12, "reset_at": 1790000000},
                             }})

    results = fetch_all_usage(config_path=config, http=HTTP())
    assert len(results) == 1
    assert results[0] == {"account_id": "acc-13", "name": "interagent.dev01", "used_pct": 40,
                          "resets_at_epoch": 1791580397, "plan": "pro"}
    assert all(call[1]["headers"] == {"Authorization": "Bearer test-token", "New-Api-User": "1"} for call in calls)


def test_newapi_usage_null_secondary_has_no_five_hour(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    config = _write_json(tmp_path / "accounts.json", [{"format": "newapi-usage-api"}])
    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return {"data": self.data}
    class HTTP:
        def get(self, url, **kwargs):
            if "/usage" not in url:
                return Response({"items": [{"id": 1, "type": 57, "status": 1}]})
            return Response({"account_id": "acc", "email": "user@example.com", "rate_limit": {
                "primary_window": {"limit_window_seconds": 604800, "used_percent": 75, "reset_at": 123},
                "secondary_window": None,
            }})
    result = fetch_all_usage(config_path=config, http=HTTP())[0]
    assert result["used_pct"] == 75
    assert result["resets_at_epoch"] == 123
    assert result["plan"] is None
    assert not any("five_hour" in key for key in result)


def test_newapi_usage_failure_does_not_block_other_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    config = _write_json(tmp_path / "accounts.json", [{"format": "newapi-usage-api"}])
    class Response:
        def __init__(self, status_code, data): self.status_code, self.data = status_code, data
        def json(self): return {"data": self.data}
    class HTTP:
        def get(self, url, **kwargs):
            if "/usage" not in url:
                return Response(200, {"items": [{"id": 1, "type": 57, "status": 1}, {"id": 2, "type": 57, "status": 1}]})
            if "/1/" in url: return Response(500, {})
            return Response(200, {"account_id": "good", "email": "good@example.com", "rate_limit": {
                "primary_window": {"limit_window_seconds": 604800, "used_percent": 75, "reset_at": 123}}})
    result = fetch_all_usage(config_path=config, http=HTTP())
    assert [row["account_id"] for row in result] == ["good"]


def test_newapi_usage_missing_token_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("DESKBAR_NEWAPI_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(openai_usage, "NEWAPI_ADMIN_TOKEN_PATH", tmp_path / "missing.token")
    config = _write_json(tmp_path / "accounts.json", [{"format": "newapi-usage-api"}])
    assert fetch_all_usage(config_path=config, http=object()) == []


def test_newapi_usage_end_to_end_oa_accounts(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from tools.usage_push_demo import oa_payload_fields

    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    config = _write_json(tmp_path / "accounts.json", [{"format": "newapi-usage-api"}])
    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return {"data": self.data}
    class HTTP:
        def get(self, url, **kwargs):
            if "/usage" not in url:
                return Response({"items": [{"id": 8, "type": 57, "status": 1}]})
            return Response({"account_id": "acc-8", "email": "user@example.com", "plan_type": "pro",
                             "rate_limit": {"primary_window": {"limit_window_seconds": 604800,
                                "used_percent": 40, "reset_at": 1791580397}, "secondary_window": None}})

    accounts = oa_payload_fields(fetch_all_usage(config_path=config, http=HTTP()), datetime.now(timezone.utc))["oa_accounts"]
    assert len(accounts) == 1
    assert accounts[0]["account_id"] == "acc-8"
    assert accounts[0]["weekly_pct"] == 40
    assert isinstance(accounts[0]["weekly_resets_at"], str)
    assert accounts[0]["weekly_resets_at"]


def test_fetch_all_usage_dedupes_account_preferring_successful_newapi(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "same-account"},
                       "https://api.openai.com/profile": {"email": "local@example.com"}})
    local_auth = _write_json(tmp_path / "codex.json", {"tokens": {"access_token": token,
                                                                    "account_id": "same-account"}})
    config = _write_json(tmp_path / "accounts.json", [
        {"auth": str(local_auth), "format": "codex"}, {"format": "newapi-usage-api"}])
    class Response:
        def __init__(self, status_code, data=None, headers=None):
            self.status_code, self.data, self.headers = status_code, data or {}, headers or {}
        def json(self): return {"data": self.data}
        def iter_content(self, chunk_size=8192): return iter(())
        def close(self): pass
    class HTTP:
        def post(self, *args, **kwargs): return Response(401)
        def get(self, url, **kwargs):
            if "/usage" not in url:
                return Response(200, {"items": [{"id": 9, "type": 57, "status": 1}]})
            return Response(200, {"account_id": "same-account", "email": "api@example.com",
                "plan_type": "pro", "rate_limit": {"primary_window": {
                    "limit_window_seconds": 604800, "used_percent": 40, "reset_at": 321}}})
    result = fetch_all_usage(config_path=config, http=HTTP())
    assert len(result) == 1
    assert result[0]["account_id"] == "same-account"
    assert result[0]["used_pct"] == 40
    assert result[0]["resets_at_epoch"] == 321


def test_fetch_all_usage_dedupes_local_and_newapi_preferring_first_success(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_NEWAPI_ADMIN_TOKEN", "test-token")
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "same-account"},
                       "https://api.openai.com/profile": {"email": "local@example.com"}})
    auth = _write_json(tmp_path / "codex.json", {"tokens": {"access_token": token,
                                                                "account_id": "same-account"}})
    config = _write_json(tmp_path / "accounts.json", [
        {"auth": str(auth), "format": "codex"}, {"format": "newapi-usage-api"}])
    class Response:
        def __init__(self, status_code, data=None, headers=None):
            self.status_code, self.data, self.headers = status_code, data or {}, headers or {}
        def json(self): return {"data": self.data}
        def iter_content(self, chunk_size=8192): return iter(())
        def close(self): pass
    class HTTP:
        def post(self, *args, **kwargs):
            return Response(200, headers={"x-codex-primary-used-percent": "76",
                                          "x-codex-primary-reset-at": "456"})
        def get(self, url, **kwargs):
            if "/usage" not in url:
                return Response(200, {"items": [{"id": 9, "type": 57, "status": 1}]})
            return Response(200, {"account_id": "same-account", "email": "api@example.com",
                "plan_type": "pro", "rate_limit": {"primary_window": {
                    "limit_window_seconds": 604800, "used_percent": 40, "reset_at": 321}}})
    result = fetch_all_usage(config_path=config, http=HTTP())
    assert len(result) == 1
    assert result[0]["name"] == "local"
    assert result[0]["used_pct"] == 76.0
    assert result[0]["resets_at_epoch"] == 456
