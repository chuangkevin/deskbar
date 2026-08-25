"""deskbar.claudeusage：純資料層測試。usage 資料改由 Mac agent 推送
（見 deskbar.webserver 的 POST /api/usage），這支模組不再做任何網路呼叫，
只剩 UsageInfo 資料形狀與 fmt_countdown 倒數格式化純函數。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from deskbar import claudeusage

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


# ---------------------------------------------------------------- UsageInfo


def test_usage_info_holds_all_fields():
    info = claudeusage.UsageInfo(
        session_pct=42.0, session_resets_at=NOW + timedelta(hours=2),
        weekly_pct=61.5, weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=12.0, fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=NOW,
    )
    assert info.session_pct == 42.0
    assert info.weekly_pct == 61.5
    assert info.fable_pct == 12.0
    assert info.fetched_at == NOW


def test_usage_info_fields_may_be_none():
    info = claudeusage.UsageInfo(None, None, None, None, None, None, fetched_at=NOW)
    assert info.session_pct is None
    assert info.session_resets_at is None
    assert info.weekly_pct is None
    assert info.weekly_resets_at is None
    assert info.fable_pct is None
    assert info.fable_resets_at is None


def test_usage_info_is_frozen():
    info = claudeusage.UsageInfo(None, None, None, None, None, None, fetched_at=NOW)
    try:
        info.session_pct = 1.0
        assert False, "UsageInfo 應該是 frozen dataclass，不該能就地修改"
    except AttributeError:
        pass


# ---------------------------------------------------------------- fmt_countdown


def test_fmt_countdown_days():
    assert claudeusage.fmt_countdown(NOW + timedelta(days=1, hours=4), NOW) == "1d 4h"


def test_fmt_countdown_hours_minutes():
    assert claudeusage.fmt_countdown(NOW + timedelta(hours=2, minutes=3), NOW) == "2h 03m"


def test_fmt_countdown_imminent():
    assert claudeusage.fmt_countdown(NOW + timedelta(seconds=30), NOW) == "即將重置"
    assert claudeusage.fmt_countdown(NOW - timedelta(seconds=5), NOW) == "即將重置"


def test_fmt_countdown_none():
    assert claudeusage.fmt_countdown(None, NOW) == "—"


# ---------------------------------------------------------------- per-source cache freshness (usage_push_demo)


def _load_usage_push_demo():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "tools" / "usage_push_demo.py"
    spec = importlib.util.spec_from_file_location("usage_push_demo_freshness", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ag_oa_fetched_at_survives_claude_failure_cache_replay(tmp_path):
    """AG/OA 成功刷新寫入的分來源時間戳，在 Claude 失敗後的 cache-replay 仍在。"""
    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    stale_claude = "2026-08-04T01:00:00+00:00"
    demo.save_cache(
        {
            "session_pct": 42.0,
            "weekly_pct": 10.0,
            "fetched_at": stale_claude,
            "claude_fetched_at": stale_claude,
            "ag_5h_pct": 10.0,
            "ag_weekly_pct": 20.0,
            "oa_weekly_pct": 3.0,
        },
        path,
    )

    ag_fields = {
        "ag_5h_pct": 35.0,
        "ag_5h_resets_at": "2026-08-04T18:00:00+00:00",
        "ag_weekly_pct": 12.0,
        "ag_weekly_resets_at": "2026-08-11T00:00:00+00:00",
        "ag_fetched_at": "2026-08-04T10:00:00+00:00",
    }
    oa_fields = {
        "oa_weekly_pct": 5.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_fetched_at": "2026-08-04T10:05:00+00:00",
    }
    demo.merge_source_fields_into_cache(ag_fields, path)
    demo.merge_source_fields_into_cache(oa_fields, path)

    # 模擬 Claude 403/429：不跑 one_cycle，只暖機 + 合併後補送用的 cache 內容
    cached = demo.load_cache(path)
    assert cached["fetched_at"] == stale_claude
    assert cached["claude_fetched_at"] == stale_claude
    assert cached["ag_fetched_at"] == "2026-08-04T10:00:00+00:00"
    assert cached["oa_fetched_at"] == "2026-08-04T10:05:00+00:00"

    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": None,
                "ag_5h_resets_at": None,
                "ag_weekly_pct": None,
                "ag_weekly_resets_at": None,
            }
        )
    with demo._OA_LOCK:
        demo._OA_LATEST.clear()
        demo._OA_LATEST.update(
            {"oa_weekly_pct": None, "oa_weekly_resets_at": None}
        )

    demo.warm_ag_from_cache(cached)
    demo.warm_openai_from_cache(cached)
    replay = dict(cached)
    replay.update(demo.get_antigravity_fields())
    replay.update(demo.get_openai_fields())

    assert replay["ag_fetched_at"] == "2026-08-04T10:00:00+00:00"
    assert replay["oa_fetched_at"] == "2026-08-04T10:05:00+00:00"
    assert replay["fetched_at"] == stale_claude


def test_merge_source_fields_into_cache_noop_without_existing_cache(tmp_path):
    demo = _load_usage_push_demo()
    path = tmp_path / "missing.json"
    assert demo.merge_source_fields_into_cache(
        {"ag_fetched_at": "2026-08-04T10:00:00+00:00"}, path
    ) is None
    assert not path.exists()


def test_concurrent_cache_merges_preserve_both_source_fields(tmp_path):
    """多執行緒並行寫入不同來源欄位時，最終 JSON 必須合法且兩邊欄位／時間戳都在。"""
    import json
    import threading

    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    demo.save_cache(
        {
            "session_pct": 1.0,
            "fetched_at": "2026-08-25T01:00:00+00:00",
            "claude_fetched_at": "2026-08-25T01:00:00+00:00",
            demo.USAGE_SOURCES_CACHE_KEY: ["antigravity", "openai"],
        },
        path,
    )

    ag_stamp = "2026-08-25T10:00:00+00:00"
    oa_stamp = "2026-08-25T10:05:00+00:00"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def write_ag() -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(40):
                demo.merge_source_fields_into_cache(
                    {
                        "ag_5h_pct": 35.0,
                        "ag_weekly_pct": 12.0,
                        "ag_fetched_at": ag_stamp,
                    },
                    path,
                )
        except BaseException as error:  # noqa: BLE001 — collect for join assert
            errors.append(error)

    def write_oa() -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(40):
                demo.merge_source_fields_into_cache(
                    {
                        "oa_weekly_pct": 5.0,
                        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
                        "oa_fetched_at": oa_stamp,
                    },
                    path,
                )
        except BaseException as error:  # noqa: BLE001 — collect for join assert
            errors.append(error)

    threads = [
        threading.Thread(target=write_ag),
        threading.Thread(target=write_oa),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert not errors, f"concurrent cache writers raised: {errors!r}"
    raw = path.read_text(encoding="utf-8")
    cached = json.loads(raw)
    assert isinstance(cached, dict)
    assert cached["ag_5h_pct"] == 35.0
    assert cached["ag_fetched_at"] == ag_stamp
    assert cached["oa_weekly_pct"] == 5.0
    assert cached["oa_fetched_at"] == oa_stamp
    assert cached[demo.USAGE_SOURCES_CACHE_KEY] == ["antigravity", "openai"]
    assert cached["fetched_at"] == "2026-08-25T01:00:00+00:00"
    # 不得留下固定 usage_cache.tmp；唯一暫存檔應已 replace／清掉
    assert not (tmp_path / "usage_cache.tmp").exists()


def test_openai_worker_cache_write_failure_logged_without_notify(
    tmp_path, monkeypatch, capsys
):
    """快取寫入例外不得殺 worker，也不得觸發立即補送；記憶體仍可更新。"""
    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    demo.save_cache(
        {
            "oa_weekly_pct": 1.0,
            "oa_fetched_at": "2026-08-25T01:00:00+00:00",
        },
        path,
    )
    demo._SOURCE_REFRESH_EVENT.clear()
    real_merge = demo.merge_source_fields_into_cache

    def boom_merge(fields, p=None):
        raise FileNotFoundError(
            f"[Errno 2] No such file or directory: '{path}.tmp' -> '{path}'"
        )

    monkeypatch.setattr(demo, "merge_source_fields_into_cache", boom_merge)
    monkeypatch.setattr(
        demo,
        "fetch_openai_usage",
        lambda: {"used_pct": 9.0, "resets_at_epoch": 1780000000},
    )
    # 放寬 min_interval，讓 refresh 一定排得上
    with demo._OA_FETCHING_LOCK:
        demo._OA_FETCHING = False
        demo._OA_LAST_REFRESH_MONO = None

    thread = demo.refresh_openai_async(min_interval=0.0)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()

    out = capsys.readouterr().out
    assert "快取寫入失敗" in out
    assert not demo._SOURCE_REFRESH_EVENT.is_set()
    mem = demo.get_openai_fields()
    assert mem["oa_weekly_pct"] == 9.0
    # 磁碟仍為舊值（merge 被打爆）
    monkeypatch.setattr(demo, "merge_source_fields_into_cache", real_merge)
    cached = demo.load_cache(path)
    assert cached["oa_fetched_at"] == "2026-08-25T01:00:00+00:00"


def test_prefs_url_from_usage_url():
    demo = _load_usage_push_demo()
    assert demo.prefs_url_from_usage_url(
        "http://deskbar.local:8080/api/usage"
    ) == "http://deskbar.local:8080/api/prefs"
    assert demo.prefs_url_from_usage_url(
        "https://example/api/usage/"
    ) == "https://example/api/prefs"


def test_normalize_and_resolve_usage_sources():
    demo = _load_usage_push_demo()
    assert demo.normalize_remote_usage_sources(
        ["openai", "antigravity"]
    ) == ("antigravity", "openai")
    assert demo.normalize_remote_usage_sources(["claude", "nope"]) is None
    assert demo.normalize_remote_usage_sources("openai") is None

    claude, ag, oa = demo.resolve_enabled_sources(
        ("antigravity", "openai"), want_antigravity=True, want_openai=True
    )
    assert (claude, ag) == (False, True)
    # oa 還取決於 fetch_openai_usage 是否可 import；只斷言 claude 關、ag 開
    assert claude is False and ag is True

    claude_on, _, _ = demo.resolve_enabled_sources(("claude", "openai"))
    assert claude_on is True


def test_disabled_claude_compose_publishes_ag_oa_timestamps_without_anthropic_gate():
    """Claude 停用：舊 fetched_at 不擋推送；AG/OA 帶自己的時間戳。"""
    demo = _load_usage_push_demo()
    stale_claude = "2026-08-04T01:00:00+00:00"
    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": 35.0,
                "ag_5h_resets_at": "2026-08-04T18:00:00+00:00",
                "ag_weekly_pct": 12.0,
                "ag_weekly_resets_at": "2026-08-11T00:00:00+00:00",
                "ag_fetched_at": "2026-08-04T10:00:00+00:00",
            }
        )
    with demo._OA_LOCK:
        demo._OA_LATEST.clear()
        demo._OA_LATEST.update(
            {
                "oa_weekly_pct": 5.0,
                "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
                "oa_fetched_at": "2026-08-04T10:05:00+00:00",
            }
        )

    payload = demo.compose_publish_payload(
        {
            "session_pct": 99.0,
            "weekly_pct": 99.0,
            "fetched_at": stale_claude,
            "claude_fetched_at": stale_claude,
        },
        enable_claude=False,
        enable_antigravity=True,
        enable_openai=True,
    )
    assert payload is not None
    assert "fetched_at" not in payload
    assert "claude_fetched_at" not in payload
    assert payload["session_pct"] is None
    assert payload["ag_fetched_at"] == "2026-08-04T10:00:00+00:00"
    assert payload["oa_fetched_at"] == "2026-08-04T10:05:00+00:00"
    assert payload["ag_5h_pct"] == 35.0
    assert payload["oa_weekly_pct"] == 5.0

    # 沒有 Claude 快取也能推
    no_cache = demo.compose_publish_payload(
        None,
        enable_claude=False,
        enable_antigravity=True,
        enable_openai=True,
    )
    assert no_cache is not None
    assert no_cache["ag_fetched_at"] == "2026-08-04T10:00:00+00:00"
    assert no_cache["oa_fetched_at"] == "2026-08-04T10:05:00+00:00"


def test_disabled_claude_run_loop_skips_anthropic_fetch_and_backoff(monkeypatch):
    """usage_sources 無 claude 時：不打 Anthropic、不走 429 backoff，仍推 AG/OA。"""
    demo = _load_usage_push_demo()
    pushes = []
    anthropic_calls = {"one_cycle": 0, "fetch_usage": 0}

    monkeypatch.setattr(
        demo,
        "fetch_usage_sources",
        lambda *a, **k: ("antigravity", "openai"),
    )
    monkeypatch.setattr(demo, "load_cache", lambda path=None: None)
    monkeypatch.setattr(demo, "save_cache", lambda payload, path=None: dict(payload))
    monkeypatch.setattr(
        demo,
        "persist_usage_sources",
        lambda sources, path=None: {demo.USAGE_SOURCES_CACHE_KEY: list(sources)},
    )
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "refresh_openai_async", lambda min_interval=300.0: None)
    monkeypatch.setattr(demo, "_oa_activity_mtime_changed", lambda paths=None: False)

    def boom_one_cycle(*a, **k):
        anthropic_calls["one_cycle"] += 1
        raise AssertionError("disabled Claude must not call one_cycle")

    def boom_fetch_usage(*a, **k):
        anthropic_calls["fetch_usage"] += 1
        raise AssertionError("disabled Claude must not call fetch_usage")

    monkeypatch.setattr(demo, "one_cycle", boom_one_cycle)
    monkeypatch.setattr(demo, "fetch_usage", boom_fetch_usage)
    monkeypatch.setattr(
        demo, "push", lambda payload, url, token: pushes.append(dict(payload))
    )

    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": 21.0,
                "ag_5h_resets_at": None,
                "ag_weekly_pct": 8.0,
                "ag_weekly_resets_at": None,
                "ag_fetched_at": "2026-08-25T03:00:00+00:00",
            }
        )
    with demo._OA_LOCK:
        demo._OA_LATEST.clear()
        demo._OA_LATEST.update(
            {
                "oa_weekly_pct": 4.0,
                "oa_weekly_resets_at": None,
                "oa_fetched_at": "2026-08-25T03:01:00+00:00",
            }
        )

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo.time, "sleep", fake_sleep)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=60.0,
            ag_interval=300.0,
            oa_interval=3600.0,
            prefs_interval=3600.0,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert anthropic_calls == {"one_cycle": 0, "fetch_usage": 0}
    assert pushes, "Claude 停用時仍應推送 AG/OA"
    assert pushes[0]["ag_fetched_at"] == "2026-08-25T03:00:00+00:00"
    assert pushes[0]["oa_fetched_at"] == "2026-08-25T03:01:00+00:00"
    assert "fetched_at" not in pushes[0]
    assert pushes[0]["session_pct"] is None


def test_enabled_claude_still_uses_one_cycle(monkeypatch):
    """prefs 含 claude 時維持原本 one_cycle 抓取路徑。"""
    demo = _load_usage_push_demo()
    calls = {"one_cycle": 0}

    monkeypatch.setattr(
        demo, "fetch_usage_sources", lambda *a, **k: ("claude", "antigravity")
    )
    monkeypatch.setattr(demo, "load_cache", lambda path=None: None)
    monkeypatch.setattr(demo, "save_cache", lambda payload, path=None: dict(payload))
    monkeypatch.setattr(
        demo, "persist_usage_sources", lambda sources, path=None: {demo.USAGE_SOURCES_CACHE_KEY: list(sources)}
    )
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "push", lambda *a, **k: None)

    def fake_one_cycle(*a, **k):
        calls["one_cycle"] += 1
        return {
            "session_pct": 1.0,
            "weekly_pct": 2.0,
            "fetched_at": "2026-08-25T04:00:00+00:00",
            "claude_fetched_at": "2026-08-25T04:00:00+00:00",
        }

    monkeypatch.setattr(demo, "one_cycle", fake_one_cycle)

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 1:
            raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo.time, "sleep", fake_sleep)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=60.0,
            prefs_interval=3600.0,
            enable_openai=False,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert calls["one_cycle"] >= 1


def test_offline_startup_uses_cached_usage_sources(tmp_path, monkeypatch):
    """prefs 失敗時沿用本機已確認的 usage_sources，不得復活 Claude。"""
    demo = _load_usage_push_demo()
    cache_path = tmp_path / "usage_cache.json"
    monkeypatch.setattr(demo, "CACHE_PATH", cache_path)
    demo.save_cache(
        {
            "ag_5h_pct": 10.0,
            "ag_weekly_pct": 20.0,
            "oa_weekly_pct": 3.0,
            "ag_fetched_at": "2026-08-25T01:00:00+00:00",
            "oa_fetched_at": "2026-08-25T01:01:00+00:00",
            demo.USAGE_SOURCES_CACHE_KEY: ["antigravity", "openai"],
        },
        cache_path,
    )

    anthropic_calls = {"one_cycle": 0}
    monkeypatch.setattr(demo, "fetch_usage_sources", lambda *a, **k: None)
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "refresh_openai_async", lambda min_interval=300.0: None)
    monkeypatch.setattr(demo, "_oa_activity_mtime_changed", lambda paths=None: False)

    def boom_one_cycle(*a, **k):
        anthropic_calls["one_cycle"] += 1
        raise AssertionError("must not call one_cycle when cached sources omit claude")

    monkeypatch.setattr(demo, "one_cycle", boom_one_cycle)
    monkeypatch.setattr(demo, "push", lambda *a, **k: None)

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 1:
            raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo.time, "sleep", fake_sleep)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=60.0,
            prefs_interval=3600.0,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert anthropic_calls["one_cycle"] == 0
    assert demo.bootstrap_usage_sources(demo.load_cache(cache_path)) == (
        "antigravity",
        "openai",
    )


def test_offline_first_run_safe_default_excludes_claude(tmp_path, monkeypatch):
    """無 prefs、無快取：安全預設只有 antigravity + openai。"""
    demo = _load_usage_push_demo()
    cache_path = tmp_path / "usage_cache.json"
    monkeypatch.setattr(demo, "CACHE_PATH", cache_path)
    assert demo.SAFE_BOOTSTRAP_USAGE_SOURCES == ("antigravity", "openai")
    assert demo.DEFAULT_USAGE_SOURCES == demo.SAFE_BOOTSTRAP_USAGE_SOURCES
    assert "claude" not in demo.DEFAULT_USAGE_SOURCES

    anthropic_calls = {"one_cycle": 0}
    monkeypatch.setattr(demo, "fetch_usage_sources", lambda *a, **k: None)
    monkeypatch.setattr(demo, "load_cache", lambda path=None: None)
    monkeypatch.setattr(demo, "save_cache", lambda payload, path=None: dict(payload))
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "refresh_openai_async", lambda min_interval=300.0: None)
    monkeypatch.setattr(demo, "_oa_activity_mtime_changed", lambda paths=None: False)

    def boom_one_cycle(*a, **k):
        anthropic_calls["one_cycle"] += 1
        raise AssertionError("first-run offline must not enable Claude")

    monkeypatch.setattr(demo, "one_cycle", boom_one_cycle)
    monkeypatch.setattr(demo, "push", lambda *a, **k: None)

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 1:
            raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo.time, "sleep", fake_sleep)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=60.0,
            prefs_interval=3600.0,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert anthropic_calls["one_cycle"] == 0
    assert demo.bootstrap_usage_sources(None) == ("antigravity", "openai")


def test_prefs_success_persists_sources_and_remote_can_reenable_claude(
    tmp_path, monkeypatch
):
    """成功 prefs 寫入快取且不覆寫百分比；網路恢復後可再啟用 Claude。"""
    demo = _load_usage_push_demo()
    cache_path = tmp_path / "usage_cache.json"
    monkeypatch.setattr(demo, "CACHE_PATH", cache_path)
    prior = {
        "ag_5h_pct": 42.0,
        "ag_weekly_pct": 11.0,
        "oa_weekly_pct": 7.0,
        "ag_fetched_at": "2026-08-25T02:00:00+00:00",
        "oa_fetched_at": "2026-08-25T02:01:00+00:00",
        demo.USAGE_SOURCES_CACHE_KEY: ["antigravity", "openai"],
    }
    demo.save_cache(prior, cache_path)

    prefs_calls = {"n": 0}
    one_cycle_calls = {"n": 0}

    def fake_prefs(*_a, **_k):
        prefs_calls["n"] += 1
        if prefs_calls["n"] == 1:
            return None  # offline bootstrap → cached antigravity+openai
        return ("claude", "antigravity", "openai")

    def fake_one_cycle(*_a, **_k):
        one_cycle_calls["n"] += 1
        return {
            "session_pct": 1.0,
            "weekly_pct": 2.0,
            "fetched_at": "2026-08-25T05:00:00+00:00",
            "claude_fetched_at": "2026-08-25T05:00:00+00:00",
            "ag_5h_pct": 42.0,
            "ag_weekly_pct": 11.0,
            "oa_weekly_pct": 7.0,
            demo.USAGE_SOURCES_CACHE_KEY: [
                "claude",
                "antigravity",
                "openai",
            ],
        }

    monkeypatch.setattr(demo, "fetch_usage_sources", fake_prefs)
    monkeypatch.setattr(demo, "one_cycle", fake_one_cycle)
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "refresh_openai_async", lambda min_interval=300.0: None)
    monkeypatch.setattr(demo, "_oa_activity_mtime_changed", lambda paths=None: False)
    monkeypatch.setattr(demo, "push", lambda *a, **k: None)

    # 先驗證 persist 不踩百分比
    written = demo.persist_usage_sources(("antigravity", "openai"), cache_path)
    assert written["ag_5h_pct"] == 42.0
    assert written["oa_weekly_pct"] == 7.0
    assert written["ag_fetched_at"] == "2026-08-25T02:00:00+00:00"
    assert written[demo.USAGE_SOURCES_CACHE_KEY] == ["antigravity", "openai"]

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        # prefs_interval=0 → 第一輪 loop 就會重讀 prefs 並啟用 Claude
        if ticks["n"] >= 2:
            raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo.time, "sleep", fake_sleep)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=60.0,
            prefs_interval=0.0,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert prefs_calls["n"] >= 2
    assert one_cycle_calls["n"] >= 1
    final = demo.load_cache(cache_path)
    assert final[demo.USAGE_SOURCES_CACHE_KEY] == [
        "claude",
        "antigravity",
        "openai",
    ]
    # 百分比不該被 prefs metadata 寫入清掉
    assert final["ag_5h_pct"] == 42.0
    assert final["oa_weekly_pct"] == 7.0


def test_openai_worker_success_wakes_loop_before_push_interval(
    tmp_path, monkeypatch
):
    """延遲完成的 OpenAI worker 必須在 push_interval 到期前觸發補送新 oa_fetched_at。"""
    demo = _load_usage_push_demo()
    demo._SOURCE_REFRESH_EVENT.clear()
    cache_path = tmp_path / "usage_cache.json"
    monkeypatch.setattr(demo, "CACHE_PATH", cache_path)
    demo.save_cache(
        {
            "oa_weekly_pct": 4.0,
            "oa_weekly_resets_at": None,
            "oa_fetched_at": "2026-08-25T03:01:00+00:00",
            demo.USAGE_SOURCES_CACHE_KEY: ["openai"],
        },
        cache_path,
    )

    pushes = []
    mono = {"t": 1000.0}
    push_interval = 60.0
    fresh_oa = "2026-08-25T12:09:00+00:00"

    monkeypatch.setattr(
        demo, "fetch_usage_sources", lambda *a, **k: ("openai",)
    )
    monkeypatch.setattr(demo, "refresh_antigravity_async", lambda: None)
    monkeypatch.setattr(demo, "refresh_openai_async", lambda min_interval=300.0: None)
    monkeypatch.setattr(demo, "_oa_activity_mtime_changed", lambda paths=None: False)
    monkeypatch.setattr(demo.time, "monotonic", lambda: mono["t"])
    monkeypatch.setattr(
        demo, "push", lambda payload, url, token: pushes.append(dict(payload))
    )

    with demo._OA_LOCK:
        demo._OA_LATEST.clear()
        demo._OA_LATEST.update(
            {
                "oa_weekly_pct": 4.0,
                "oa_weekly_resets_at": None,
                "oa_fetched_at": "2026-08-25T03:01:00+00:00",
            }
        )

    idle = {"n": 0}

    def fake_idle(_timeout):
        idle["n"] += 1
        if idle["n"] == 1:
            # 模擬：首輪已推過舊值並進入等待後，worker 才寫入並通知。
            assert pushes, "首輪應先推送舊快取"
            with demo._OA_LOCK:
                demo._OA_LATEST.update(
                    {
                        "oa_weekly_pct": 9.0,
                        "oa_weekly_resets_at": None,
                        "oa_fetched_at": fresh_oa,
                    }
                )
            demo.merge_source_fields_into_cache(
                {
                    "oa_weekly_pct": 9.0,
                    "oa_weekly_resets_at": None,
                    "oa_fetched_at": fresh_oa,
                },
                cache_path,
            )
            demo._notify_source_refresh_ready()
            mono["t"] += 9.0  # 遠小於 push_interval
            return
        raise RuntimeError("stop-loop")

    monkeypatch.setattr(demo, "_loop_idle_wait", fake_idle)

    try:
        demo.run_loop(
            "http://deskbar.test/api/usage",
            None,
            fetch_interval=300.0,
            push_interval=push_interval,
            ag_interval=300.0,
            oa_interval=3600.0,
            prefs_interval=3600.0,
            enable_antigravity=False,
        )
    except RuntimeError as error:
        assert str(error) == "stop-loop"

    assert len(pushes) >= 2, "worker 完成後應立刻再推一次"
    assert pushes[0]["oa_fetched_at"] == "2026-08-25T03:01:00+00:00"
    assert pushes[1]["oa_fetched_at"] == fresh_oa
    # 兩次推送間隔（單調時鐘）必須小於完整 push_interval
    assert mono["t"] - 1000.0 < push_interval


# ---------------------------------------------------------------- Antigravity invalid empty result


def test_is_unusable_antigravity_fields_shape():
    demo = _load_usage_push_demo()
    assert demo.is_unusable_antigravity_fields(
        {
            "ag_5h_pct": 0.0,
            "ag_5h_resets_at": None,
            "ag_weekly_pct": 0.0,
            "ag_weekly_resets_at": None,
        }
    )
    assert demo.is_unusable_antigravity_fields(
        {
            "ag_5h_pct": None,
            "ag_5h_resets_at": None,
            "ag_weekly_pct": None,
            "ag_weekly_resets_at": None,
        }
    )
    # 真實 0% 帶重置時間 → 可用
    assert not demo.is_unusable_antigravity_fields(
        {
            "ag_5h_pct": 0.0,
            "ag_5h_resets_at": "2026-08-25T18:00:00+00:00",
            "ag_weekly_pct": 0.0,
            "ag_weekly_resets_at": None,
        }
    )
    assert not demo.is_unusable_antigravity_fields(
        {
            "ag_5h_pct": 100.0,
            "ag_5h_resets_at": None,
            "ag_weekly_pct": 49.89,
            "ag_weekly_resets_at": None,
        }
    )


def test_ag_worker_rejects_all_zero_no_reset_preserves_cache(tmp_path, monkeypatch, capsys):
    """全 0% 且無重置時間不得覆寫記憶體／磁碟快取，也不更新 ag_fetched_at。"""
    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    prior_fetched = "2026-08-25T02:00:00+00:00"
    prior = {
        "session_pct": 1.0,
        "fetched_at": "2026-08-25T01:00:00+00:00",
        "ag_5h_pct": 100.0,
        "ag_5h_resets_at": "2026-08-25T07:00:00+00:00",
        "ag_weekly_pct": 49.89,
        "ag_weekly_resets_at": "2026-08-31T00:00:00+00:00",
        "ag_fetched_at": prior_fetched,
    }
    demo.save_cache(prior, path)
    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, p=path: real_merge(fields, p),
    )

    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": 100.0,
                "ag_5h_resets_at": "2026-08-25T07:00:00+00:00",
                "ag_weekly_pct": 49.89,
                "ag_weekly_resets_at": "2026-08-31T00:00:00+00:00",
                "ag_fetched_at": prior_fetched,
            }
        )

    # remaining=100 → used%=0；無 refresh_min → resets None（實機空結果形狀）
    monkeypatch.setattr(demo, "fetch_usage_text", lambda: "panel text")
    monkeypatch.setattr(
        demo,
        "parse_usage_panel",
        lambda text: {
            "gemini_5h_remaining": 100.0,
            "gemini_5h_refresh_min": None,
            "gemini_weekly_remaining": 100.0,
            "gemini_weekly_refresh_min": None,
        },
    )

    thread = demo.refresh_antigravity_async()
    assert thread is not None
    thread.join(timeout=5)

    mem = demo.get_antigravity_fields()
    assert mem["ag_5h_pct"] == 100.0
    assert mem["ag_weekly_pct"] == 49.89
    assert mem["ag_fetched_at"] == prior_fetched

    cached = demo.load_cache(path)
    assert cached["ag_5h_pct"] == 100.0
    assert cached["ag_weekly_pct"] == 49.89
    assert cached["ag_fetched_at"] == prior_fetched

    out = capsys.readouterr().out
    assert "抓取結果無效" in out
    assert "保留上一次用量資料" in out


def test_ag_worker_accepts_zero_pct_with_reset(tmp_path, monkeypatch):
    """真實 0% 若帶重置時間，應寫入記憶體與磁碟並刷新 ag_fetched_at。"""
    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    demo.save_cache(
        {
            "session_pct": 1.0,
            "fetched_at": "2026-08-25T01:00:00+00:00",
            "ag_5h_pct": 12.0,
            "ag_5h_resets_at": "2026-08-25T06:00:00+00:00",
            "ag_weekly_pct": 8.0,
            "ag_weekly_resets_at": "2026-08-30T00:00:00+00:00",
            "ag_fetched_at": "2026-08-25T02:00:00+00:00",
        },
        path,
    )
    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, p=path: real_merge(fields, p),
    )

    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": 12.0,
                "ag_5h_resets_at": "2026-08-25T06:00:00+00:00",
                "ag_weekly_pct": 8.0,
                "ag_weekly_resets_at": "2026-08-30T00:00:00+00:00",
                "ag_fetched_at": "2026-08-25T02:00:00+00:00",
            }
        )

    monkeypatch.setattr(demo, "fetch_usage_text", lambda: "panel text")
    monkeypatch.setattr(
        demo,
        "parse_usage_panel",
        lambda text: {
            "gemini_5h_remaining": 100.0,
            "gemini_5h_refresh_min": 90,
            "gemini_weekly_remaining": 100.0,
            "gemini_weekly_refresh_min": 1000,
        },
    )

    thread = demo.refresh_antigravity_async()
    assert thread is not None
    thread.join(timeout=5)

    mem = demo.get_antigravity_fields()
    assert mem["ag_5h_pct"] == 0.0
    assert mem["ag_weekly_pct"] == 0.0
    assert mem["ag_5h_resets_at"] is not None
    assert mem["ag_weekly_resets_at"] is not None
    assert mem["ag_fetched_at"] != "2026-08-25T02:00:00+00:00"

    cached = demo.load_cache(path)
    assert cached["ag_5h_pct"] == 0.0
    assert cached["ag_weekly_pct"] == 0.0
    assert cached["ag_fetched_at"] == mem["ag_fetched_at"]


def test_default_antigravity_fetch_timeout_is_realistic():
    """生產預設必須高於 agy /usage 常見 ~45s，同時保持有界（55–75s）。"""
    from tools.antigravity_usage import DEFAULT_FETCH_TIMEOUT_S

    assert DEFAULT_FETCH_TIMEOUT_S == 60.0
    assert 55.0 <= DEFAULT_FETCH_TIMEOUT_S <= 75.0


def test_fetch_usage_text_timeout_is_bounded_no_network(monkeypatch):
    """模擬 pty 掛起：必須在自訂 timeout_s 內以 TimeoutError 失敗，不合成用量。"""
    import time as time_mod

    from tools import antigravity_usage as ag

    monkeypatch.setattr(ag.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(ag.pty, "fork", lambda: (4242, 7))
    monkeypatch.setattr(
        ag.fcntl, "ioctl", lambda *_a, **_k: None
    )
    monkeypatch.setattr(ag.os, "write", lambda *_a, **_k: 0)
    monkeypatch.setattr(ag.os, "read", lambda *_a, **_k: b"")
    monkeypatch.setattr(ag.os, "close", lambda *_a, **_k: None)
    monkeypatch.setattr(ag.os, "kill", lambda *_a, **_k: None)
    monkeypatch.setattr(ag.os, "waitpid", lambda *_a, **_k: (0, 0))

    def slow_select(_r, _w, _x, timeout=0.0):
        # 模擬無資料可讀，讓呼叫端消耗完整 timeout 預算
        time_mod.sleep(min(float(timeout or 0.0), 0.05))
        return ([], [], [])

    monkeypatch.setattr(ag.select, "select", slow_select)

    started = time_mod.monotonic()
    try:
        ag.fetch_usage_text(timeout_s=0.25)
        assert False, "expected TimeoutError on hung pty"
    except TimeoutError as error:
        assert "timed out" in str(error)
        assert "0.25" in str(error)
    elapsed = time_mod.monotonic() - started
    assert elapsed < 2.0, f"timeout path must stay bounded, took {elapsed:.2f}s"


def test_ag_worker_timeout_preserves_cache_and_allows_retry(
    tmp_path, monkeypatch, capsys
):
    """逾時不得覆寫 0%、不更新 ag_fetched_at，且釋放 single-flight 讓下一輪可重試。"""
    demo = _load_usage_push_demo()
    path = tmp_path / "usage_cache.json"
    prior_fetched = "2026-08-25T02:00:00+00:00"
    prior = {
        "session_pct": 1.0,
        "fetched_at": "2026-08-25T01:00:00+00:00",
        "ag_5h_pct": 100.0,
        "ag_5h_resets_at": "2026-08-25T07:00:00+00:00",
        "ag_weekly_pct": 49.89,
        "ag_weekly_resets_at": "2026-08-31T00:00:00+00:00",
        "ag_fetched_at": prior_fetched,
    }
    demo.save_cache(prior, path)
    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, p=path: real_merge(fields, p),
    )

    with demo._AG_LOCK:
        demo._AG_LATEST.clear()
        demo._AG_LATEST.update(
            {
                "ag_5h_pct": 100.0,
                "ag_5h_resets_at": "2026-08-25T07:00:00+00:00",
                "ag_weekly_pct": 49.89,
                "ag_weekly_resets_at": "2026-08-31T00:00:00+00:00",
                "ag_fetched_at": prior_fetched,
            }
        )

    def boom_timeout(*_a, **_k):
        raise TimeoutError("Antigravity fetch timed out after 10s")

    monkeypatch.setattr(demo, "fetch_usage_text", boom_timeout)

    thread = demo.refresh_antigravity_async()
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()

    mem = demo.get_antigravity_fields()
    assert mem["ag_5h_pct"] == 100.0
    assert mem["ag_weekly_pct"] == 49.89
    assert mem["ag_fetched_at"] == prior_fetched

    cached = demo.load_cache(path)
    assert cached["ag_5h_pct"] == 100.0
    assert cached["ag_weekly_pct"] == 49.89
    assert cached["ag_fetched_at"] == prior_fetched

    out = capsys.readouterr().out
    assert "抓取逾時" in out
    assert "保留上一次用量資料" in out

    with demo._AG_FETCHING_LOCK:
        assert demo._AG_FETCHING is False

    # single-flight 已釋放 → 下一輪可再次排程
    calls = {"n": 0}

    def empty_fetch(*_a, **_k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(demo, "fetch_usage_text", empty_fetch)
    retry = demo.refresh_antigravity_async()
    assert retry is not None, "after timeout, Antigravity refresh must be eligible again"
    retry.join(timeout=5)
    assert calls["n"] == 1
