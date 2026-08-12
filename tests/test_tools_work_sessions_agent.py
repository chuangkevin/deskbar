import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tools.work_sessions_agent as session_agent
from tools.work_sessions_agent import DeskbarClient, SessionCollector, WorkSessionsAgent, focus_source_app

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, values: list[dict], mtime: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(value) for value in values) + "\n", encoding="utf-8")
    path.touch()
    import os
    os.utime(path, (mtime.timestamp(), mtime.timestamp()))


def test_collector_dedupes_sources_filters_stale_and_never_pushes_private_fields(tmp_path):
    recent = NOW - timedelta(minutes=2)
    stale = NOW - timedelta(minutes=31)
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/11/codex.jsonl", [
        {"session_meta": {"session_id": "native-codex", "cwd": "/private/deskbar"}},
        {"timestamp": recent.isoformat(), "prompt": "not for Pi"},
    ], recent)
    _write_jsonl(tmp_path / ".claude/projects/project/claude.jsonl", [
        {"sessionId": "native-claude", "cwd": "/private/other", "timestamp": recent.isoformat(),
         "lastPrompt": "not for Pi"},
    ], recent)
    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/c.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({"sessionId": "native-claude", "cwd": "/private/other",
                                    "lastActivityAt": recent.isoformat(), "title": "authorized title"}), encoding="utf-8")
    import os
    os.utime(app_file, (recent.timestamp(), recent.timestamp()))
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/10/stale.jsonl", [
        {"session_meta": {"session_id": "stale", "cwd": "/private/stale"}},
        {"timestamp": stale.isoformat()},
    ], stale)

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()
    assert len(payload["items"]) == 2
    assert {item["label"] for item in payload["items"]} == {"deskbar", "authorized title"}
    assert {item["project_label"] for item in payload["items"]} == {"deskbar", "other"}
    encoded = json.dumps(payload)
    for forbidden in ("native-codex", "native-claude", "not for Pi", "/private/"):
        assert forbidden not in encoded


def test_missing_source_is_reported_without_crashing(tmp_path):
    payload = SessionCollector(home=tmp_path, now=lambda: NOW).payload()
    assert payload["items"] == []
    assert {tuple(error.items()) for error in payload["errors"]} == {
        (("source", "claude"), ("code", "unavailable")),
        (("source", "codex"), ("code", "unavailable")),
    }


def test_collector_uses_login_home_when_launchagent_home_is_blank(monkeypatch, tmp_path):
    class LoginUser:
        pw_dir = str(tmp_path)

    monkeypatch.setenv("HOME", "")
    monkeypatch.setattr(session_agent.pwd, "getpwuid", lambda _uid: LoginUser())
    assert SessionCollector().home == tmp_path


def test_collector_only_parses_metadata_and_tail_record(monkeypatch, tmp_path):
    """Long transcripts must not make the periodic collector parse every event."""
    recent = NOW - timedelta(minutes=1)
    middle = [{"timestamp": (NOW - timedelta(days=1)).isoformat(), "prompt": "private"}] * 500
    path = tmp_path / ".codex/sessions/2026/08/11/long.jsonl"
    _write_jsonl(path, [
        {"session_meta": {"session_id": "native", "cwd": "/private/fast"}},
        *middle,
        {"timestamp": recent.isoformat()},
    ], recent)
    real_loads, calls = session_agent.json.loads, []

    def counted(value, *args, **kwargs):
        calls.append(value)
        return real_loads(value, *args, **kwargs)

    monkeypatch.setattr(session_agent.json, "loads", counted)
    assert SessionCollector(home=tmp_path, now=lambda: NOW).payload()["items"]
    assert len(calls) <= 4


def test_focus_uses_fixed_argv_and_no_shell():
    calls = []

    class Result:
        returncode = 0

    assert focus_source_app("codex", runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls == [((['/usr/bin/open', '-b', 'com.openai.codex'],), {'check': False, 'timeout': 10, 'shell': False})]
    assert focus_source_app("claude", runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls[-1] == ((['/usr/bin/open', '-a', 'Claude'],), {'check': False, 'timeout': 10, 'shell': False})
    assert focus_source_app("unknown", runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())) is False
    tree = ast.parse(Path(__file__).parents[1].joinpath("tools/work_sessions_agent.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Call) and any(
        isinstance(keyword, ast.keyword) and keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True for keyword in node.keywords
    ) for node in ast.walk(tree))


def test_agent_only_opens_known_opaque_capability_and_acks(tmp_path):
    recent = NOW - timedelta(minutes=1)
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/11/codex.jsonl", [
        {"session_meta": {"session_id": "native", "cwd": "/private/deskbar"}}, {"timestamp": recent.isoformat()},
    ], recent)
    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")

    class Client:
        def __init__(self):
            self.posts, self.gets = [], 0
        def post(self, path, payload):
            self.posts.append((path, payload)); return {}
        def get(self, path):
            self.gets += 1
            open_id = collector.payload()["items"][0]["open_id"]
            return {"actions": [
                {"action_id": "known", "open_id": open_id, "source": "codex"},
                {"action_id": "unknown", "open_id": "not-a-capability", "source": "codex"},
            ]}

    client, opened = Client(), []
    agent = WorkSessionsAgent(collector, client, opener=opened.append)
    agent.collect_and_push()
    assert agent.poll_and_focus() == 2
    assert opened == ["codex"]
    assert [post[0] for post in client.posts].count("/api/work-sessions/actions/ack") == 2


def test_new_codex_format_and_activity_state(tmp_path):
    recent = NOW - timedelta(minutes=1)
    # Test new Codex wrapper format: {"type":"session_meta", "payload":{"session_id":..., "cwd":...}}
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/11/new_codex.jsonl", [
        {"type": "session_meta", "payload": {"session_id": "new-native-id", "cwd": "/private/new_deskbar"}},
        {"type": "event", "payload": {"type": "user", "role": "user"}, "timestamp": (recent - timedelta(seconds=10)).isoformat()},
        {"type": "event", "payload": {"type": "assistant_message", "role": "assistant"}, "timestamp": recent.isoformat()},
    ], recent)

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["source"] == "codex"
    assert item["label"] == "new_deskbar"
    assert item["activity_state"] == "result"

    encoded = json.dumps(payload)
    for forbidden in ("new-native-id", "/private/", "prompt", "text", "message"):
        assert forbidden not in encoded


def test_codex_desktop_title_is_preferred_without_sending_private_thread_fields(tmp_path):
    recent = NOW - timedelta(minutes=1)
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/11/new_codex.jsonl", [
        {"type": "session_meta", "payload": {"session_id": "codex-native-id", "cwd": "/private/old-project"}},
        {"type": "event_msg", "payload": {"type": "custom_tool_call"}, "timestamp": recent.isoformat()},
    ], recent)
    database = tmp_path / ".codex/state_5.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT NOT NULL, cwd TEXT NOT NULL)")
    connection.execute(
        "INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
        ("codex-native-id", "Deskbar 工作台視覺修正", "/private/deskbar"),
    )
    connection.commit()
    connection.close()

    payload = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl").payload()
    assert payload["items"] == [{
        "source": "codex",
        "label": "Deskbar 工作台視覺修正",
        "project_label": "deskbar",
        "last_active_at": recent.isoformat().replace("+00:00", "Z"),
        "open_id": "opaque-token-abcdefghijkl",
        "activity_state": "working",
    }]
    encoded = json.dumps(payload)
    for forbidden in ("codex-native-id", "/private/", "old-project"):
        assert forbidden not in encoded


def test_codex_filters_internal_exec_and_subagent_records_from_app_task_list(tmp_path):
    recent = NOW - timedelta(minutes=1)
    for native_id in ("desktop-task", "internal-exec", "internal-subagent"):
        _write_jsonl(tmp_path / f".codex/sessions/2026/08/11/{native_id}.jsonl", [
            {"type": "session_meta", "payload": {"session_id": native_id, "cwd": "/private/deskbar"}},
            {"type": "event_msg", "payload": {"type": "custom_tool_call"}, "timestamp": recent.isoformat()},
        ], recent)
    database = tmp_path / ".codex/state_5.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT NOT NULL, cwd TEXT NOT NULL, "
        "source TEXT, thread_source TEXT)"
    )
    connection.executemany(
        "INSERT INTO threads (id, title, cwd, source, thread_source) VALUES (?, ?, ?, ?, ?)",
        [
            ("desktop-task", "Codex App 顯示的標題", "/private/deskbar", "vscode", "user"),
            ("internal-exec", "整段內部 prompt", "/private/deskbar", "exec", "user"),
            ("internal-subagent", "子代理 prompt", "/private/deskbar", "vscode", "subagent"),
        ],
    )
    connection.commit()
    connection.close()

    payload = SessionCollector(home=tmp_path, now=lambda: NOW).payload()

    assert [item["label"] for item in payload["items"]] == ["Codex App 顯示的標題"]


def test_duplicate_codex_rollout_records_become_one_opaque_item(tmp_path):
    recent = NOW - timedelta(minutes=1)
    earlier = NOW - timedelta(minutes=2)
    for filename, stamp in (("first", earlier), ("second", recent)):
        _write_jsonl(tmp_path / f".codex/sessions/2026/08/11/{filename}.jsonl", [
            {"type": "session_meta", "payload": {"session_id": "same-native-id", "cwd": "/private/deskbar"}},
            {"timestamp": stamp.isoformat()},
        ], stamp)

    payload = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl").payload()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["label"] == "deskbar"
    assert payload["items"][0]["last_active_at"] == recent.isoformat().replace("+00:00", "Z")


def test_claude_title_priority_order(tmp_path):
    recent = NOW - timedelta(minutes=1)
    _write_jsonl(tmp_path / ".claude/projects/p1/proj.jsonl", [
        {"sessionId": "sess-1", "cwd": "/home/user/proj_alpha", "customTitle": "Project Custom Title"},
        {"timestamp": recent.isoformat()},
    ], recent)

    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/sess-1.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({
        "sessionId": "sess-1",
        "cwd": "/home/user/proj_alpha",
        "lastActivityAt": recent.isoformat(),
        "title": "App Override Title"
    }), encoding="utf-8")
    import os
    os.utime(app_file, (recent.timestamp(), recent.timestamp()))

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["label"] == "App Override Title"
    assert item["project_label"] == "proj_alpha"


def test_claude_metadata_without_title_or_project_is_not_a_visible_task(tmp_path):
    recent = NOW - timedelta(minutes=1)
    _write_jsonl(tmp_path / ".claude/projects/-/queue.jsonl", [
        {"sessionId": "queue-only", "type": "queue-operation", "timestamp": recent.isoformat()},
    ], recent)

    payload = SessionCollector(home=tmp_path, now=lambda: NOW).payload()

    assert payload["items"] == []
