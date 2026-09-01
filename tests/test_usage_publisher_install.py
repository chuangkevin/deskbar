import importlib.util
import plistlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
USAGE_PUSHER_PATH = REPO_ROOT / "tools" / "usage_push_demo.py"
USAGE_PUSHER_PLIST = REPO_ROOT / "deploy" / "com.deskbar.usagepush.plist"
STABLE_USAGE_URL = "https://desk.sisihome.org/api/usage"
STALE_USAGE_IP = "100.98.35.59"


def _load_usage_push_demo():
    spec = importlib.util.spec_from_file_location(
        "usage_push_demo_install_contract", USAGE_PUSHER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_usagepush_plist() -> dict:
    with USAGE_PUSHER_PLIST.open("rb") as handle:
        return plistlib.load(handle)


def _plist_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _plist_strings(key)
            yield from _plist_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _plist_strings(item)


def test_usage_parser_defaults_to_stable_usage_url_without_requests(monkeypatch):
    demo = _load_usage_push_demo()

    def fail_request(*_args, **_kwargs):
        pytest.fail("argument parsing must not perform HTTP requests")

    monkeypatch.setattr(demo.requests, "get", fail_request)
    monkeypatch.setattr(demo.requests, "post", fail_request)

    args = demo.build_arg_parser().parse_args([])

    assert demo.DEFAULT_DESKBAR_USAGE_URL == STABLE_USAGE_URL
    assert args.url == STABLE_USAGE_URL
    assert demo.prefs_url_from_usage_url(args.url) == (
        "https://desk.sisihome.org/api/prefs"
    )


def test_usage_parser_preserves_explicit_url_override_exactly(monkeypatch):
    demo = _load_usage_push_demo()

    def fail_request(*_args, **_kwargs):
        pytest.fail("argument parsing must not perform HTTP requests")

    monkeypatch.setattr(demo.requests, "get", fail_request)
    monkeypatch.setattr(demo.requests, "post", fail_request)
    custom_url = "http://deskbar.test:18080/custom/api/usage?keep=exact#fragment"

    args = demo.build_arg_parser().parse_args(["--url", custom_url])

    assert args.url == custom_url


def test_tracked_usagepush_plist_invokes_current_runtime_command():
    plist = _load_usagepush_plist()

    assert plist["Label"] == "com.deskbar.usagepush"
    assert plist["ProgramArguments"] == [
        "/Users/kevin/.deskbar-agent/venv/bin/python",
        "/Users/kevin/.deskbar-agent/usage_push_demo.py",
        "--url",
        STABLE_USAGE_URL,
        "--loop",
    ]
    assert plist["EnvironmentVariables"] == {"PYTHONUNBUFFERED": "1"}
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["StandardOutPath"] == (
        "/Users/kevin/Library/Logs/deskbar-usagepush.log"
    )
    assert plist["StandardErrorPath"] == (
        "/Users/kevin/Library/Logs/deskbar-usagepush.log"
    )


def test_active_usage_publisher_source_has_no_stale_ip():
    demo = _load_usage_push_demo()
    parser_args = demo.build_arg_parser().parse_args([])
    plist = _load_usagepush_plist()
    program_arguments = plist["ProgramArguments"]

    assert parser_args.url == demo.DEFAULT_DESKBAR_USAGE_URL
    assert STALE_USAGE_IP not in parser_args.url
    assert STALE_USAGE_IP not in demo.DEFAULT_DESKBAR_USAGE_URL
    assert program_arguments[program_arguments.index("--url") + 1] == STABLE_USAGE_URL
    assert all(
        STALE_USAGE_IP not in value
        for value in _plist_strings(plist)
    )
