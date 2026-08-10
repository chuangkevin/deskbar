"""OpenAI Codex responses header 解析與抓取工具測試。"""
import base64
import json

from tools.openai_usage import fetch_usage, load_credentials, parse_codex_headers


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
        status_code = 500
        headers = dict(REAL_HEADERS)

        def iter_content(self, chunk_size=8192):
            yield b"error"

        def close(self):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            return Response()

    assert fetch_usage(auth_path=_auth_file(tmp_path), http=HTTP()) is None


def test_fetch_usage_missing_auth_file_returns_none(tmp_path):
    assert fetch_usage(auth_path=tmp_path / "missing-auth.json", http=object()) is None
