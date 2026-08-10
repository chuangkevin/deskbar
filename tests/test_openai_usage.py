"""OpenAI Codex responses header 解析與抓取工具測試。"""
import json

from tools.openai_usage import fetch_usage, parse_codex_headers


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
