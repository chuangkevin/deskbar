import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tools.work_sessions_agent as session_agent
from tools.work_sessions_agent import (
    POLL_SECONDS,
    DeskbarClient,
    SessionCollector,
    WorkSessionsAgent,
    open_claude_dispatch,
    open_session_target,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_action_polling_has_one_second_worst_case_latency_budget():
    """Deskbar touch actions must not sit in the Pi queue for several seconds."""
    assert POLL_SECONDS <= 1.0


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


def test_claude_app_cli_session_uuid_is_local_only_open_target(tmp_path):
    recent = NOW - timedelta(minutes=1)
    cli_uuid = "123e4567-e89b-12d3-a456-426614174000"
    local_id = "local_private_session_id"
    private_cwd = "/Users/kevin/Documents/Private Client"
    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/c.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({
        "sessionId": local_id,
        "cliSessionId": cli_uuid,
        "cwd": private_cwd,
        "lastActivityAt": recent.isoformat(),
        "title": "Safe App Title",
        "prompt": "do not transmit prompt",
        "body": "do not transmit body",
    }), encoding="utf-8")
    import os
    os.utime(app_file, (recent.timestamp(), recent.timestamp()))

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()

    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["source"] == "claude"
    assert item["open_id"] == "opaque-token-abcdefghijkl"
    target = collector.target_for_open_id(item["open_id"])
    assert target is not None
    assert (target.source, target.native_id) == ("claude", cli_uuid)
    encoded = json.dumps(payload)
    for forbidden in (local_id, cli_uuid, private_cwd, "do not transmit", "claude://resume"):
        assert forbidden not in encoded


def test_claude_epoch_millisecond_activity_time_beats_a_fresh_metadata_mtime(tmp_path):
    """A background metadata rewrite must not resurrect an idle Claude task."""
    stale = NOW - timedelta(minutes=31)
    fresh_mtime = NOW - timedelta(minutes=1)
    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/c.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({
        "sessionId": "idle-claude-session",
        "cwd": "/private/idle-project",
        "title": "Idle Claude task",
        "lastActivityAt": int(stale.timestamp() * 1000),
    }), encoding="utf-8")
    import os
    os.utime(app_file, (fresh_mtime.timestamp(), fresh_mtime.timestamp()))

    payload = SessionCollector(home=tmp_path, now=lambda: NOW).payload()

    assert payload["items"] == []


def test_claude_app_metadata_mtime_is_only_a_fallback_when_activity_is_known(tmp_path):
    stale = NOW - timedelta(minutes=31)
    fresh_mtime = NOW - timedelta(minutes=1)
    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/c.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({
        "sessionId": "idle-claude-session",
        "cwd": "/private/idle-project",
        "title": "Idle Claude task",
        "lastActivityAt": stale.isoformat(),
    }), encoding="utf-8")
    import os
    os.utime(app_file, (fresh_mtime.timestamp(), fresh_mtime.timestamp()))

    assert SessionCollector(home=tmp_path, now=lambda: NOW).payload()["items"] == []


def test_collector_includes_recent_claude_dispatch_with_safe_task_progress(tmp_path):
    recent = NOW - timedelta(minutes=1)
    cli_uuid = "123e4567-e89b-12d3-a456-426614174000"
    session_id = "local_dispatch_task"
    base = tmp_path / "Library/Application Support/Claude/local-agent-mode-sessions/org"
    descriptor = base / f"{session_id}.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(json.dumps({
        "sessionId": session_id,
        "cliSessionId": cli_uuid,
        "sessionType": "dispatch_child",
        "title": "Release checklist",
        "lastActivityAt": int(recent.timestamp() * 1000),
        "initialMessage": "private prompt must never be sent",
    }), encoding="utf-8")
    tasks = base / session_id / ".claude/tasks/task-group"
    tasks.mkdir(parents=True)
    for task_id, status in (("1", "completed"), ("2", "completed"), ("3", "in_progress"), ("4", "pending")):
        (tasks / f"{task_id}.json").write_text(json.dumps({
            "id": task_id, "status": status, "subject": "private task detail",
        }), encoding="utf-8")

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()

    assert payload["items"] == [{
        "source": "claude", "label": "Release checklist", "project_label": "Claude Dispatch",
        "last_active_at": recent.isoformat().replace("+00:00", "Z"),
        "open_id": "opaque-token-abcdefghijkl", "activity_state": "working",
        "progress_label": "2/4 完成 · 進行中",
    }]
    assert collector.target_for_open_id("opaque-token-abcdefghijkl") == session_agent.OpenTarget("claude", cli_uuid)
    encoded = json.dumps(payload)
    assert "private" not in encoded and session_id not in encoded and cli_uuid not in encoded


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


def test_target_opener_uses_fixed_argv_and_no_shell():
    calls = []
    cli_uuid = "123e4567-e89b-12d3-a456-426614174000"

    class Result:
        returncode = 0

    assert open_session_target("claude", cli_uuid, runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls == [((['/usr/bin/open', f'claude://resume?session={cli_uuid}'],), {'check': False, 'timeout': 10, 'shell': False})]
    assert open_session_target("claude", "local-not-a-uuid", runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls[-1] == ((['/usr/bin/open', '-a', 'Claude'],), {'check': False, 'timeout': 10, 'shell': False})
    assert open_session_target("codex", cli_uuid, runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls[-1] == ((['/usr/bin/open', f'codex://threads/{cli_uuid}'],), {'check': False, 'timeout': 10, 'shell': False})
    assert open_session_target("codex", "codex-native-id", runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls[-1] == ((['/usr/bin/open', '-b', 'com.openai.codex'],), {'check': False, 'timeout': 10, 'shell': False})
    assert open_claude_dispatch(runner=lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    assert calls[-1] == ((['/usr/bin/open', 'claude://claude.ai/cowork/agent'],), {'check': False, 'timeout': 10, 'shell': False})
    assert open_session_target("unknown", runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())) is False
    tree = ast.parse(Path(__file__).parents[1].joinpath("tools/work_sessions_agent.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Call) and any(
        isinstance(keyword, ast.keyword) and keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True for keyword in node.keywords
    ) for node in ast.walk(tree))


def test_agent_opens_known_claude_target_and_acks_mismatches(tmp_path):
    recent = NOW - timedelta(minutes=1)
    cli_uuid = "123e4567-e89b-12d3-a456-426614174000"
    app_file = tmp_path / "Library/Application Support/Claude/claude-code-sessions/a/b/c.json"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(json.dumps({
        "sessionId": "local_private_session_id",
        "cliSessionId": cli_uuid,
        "cwd": "/private/deskbar",
        "lastActivityAt": recent.isoformat(),
        "title": "Claude Task",
    }), encoding="utf-8")
    import os
    os.utime(app_file, (recent.timestamp(), recent.timestamp()))
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
                {"action_id": "known", "open_id": open_id, "source": "claude"},
                {"action_id": "wrong-source", "open_id": open_id, "source": "codex"},
                {"action_id": "unknown", "open_id": "not-a-capability", "source": "claude"},
            ]}

    client, opened = Client(), []
    agent = WorkSessionsAgent(collector, client, opener=lambda source, native_id: opened.append((source, native_id)) or True)
    agent.collect_and_push()
    assert agent.poll_and_focus() == 3
    assert opened == [("claude", cli_uuid)]
    assert [post[0] for post in client.posts].count("/api/work-sessions/actions/ack") == 3


def test_agent_dispatches_only_the_explicit_claude_dispatch_action(tmp_path):
    collector = SessionCollector(home=tmp_path, now=lambda: NOW)

    class Client:
        def __init__(self):
            self.posts = []

        def post(self, path, payload):
            self.posts.append((path, payload)); return {}

        def get(self, path):
            assert path == "/api/work-sessions/actions"
            return {"actions": [
                {"action_id": "dispatch", "source": "claude", "kind": "claude_dispatch"},
                {"action_id": "forged", "source": "claude", "kind": "claude_dispatch", "open_id": "not-allowed"},
            ]}

    client, opened, dispatched = Client(), [], []
    agent = WorkSessionsAgent(
        collector,
        client,
        opener=lambda source, native_id: opened.append((source, native_id)) or True,
        dispatch_opener=lambda: dispatched.append(True) or True,
    )
    assert agent.poll_and_focus() == 2
    assert dispatched == [True]
    assert opened == []
    assert [post[0] for post in client.posts] == [
        "/api/work-sessions/actions/ack",
        "/api/work-sessions/actions/ack",
    ]


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


def test_codex_sqlite_source_metadata_filters_exec_and_subagent_records(tmp_path):
    recent = NOW - timedelta(minutes=1)
    session_meta = {
        "internal-exec": ("/private/exec-project", "delegated prompt should not be shown"),
        "internal-subagent": ("/private/subagent-project", "subagent prompt should not be shown"),
        "visible-vscode": ("/private/jsonl-vscode", "JSONL title must not win"),
        "visible-user": ("/private/jsonl-user", "JSONL user title must not win"),
    }
    for native_id, (cwd, title) in session_meta.items():
        _write_jsonl(tmp_path / f".codex/sessions/2026/08/11/{native_id}.jsonl", [
            {"type": "session_meta", "payload": {"session_id": native_id, "cwd": cwd, "title": title}},
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
            ("internal-exec", "Internal Exec Prompt", "/private/exec-project", "exec", "user"),
            ("internal-subagent", "Subagent Internal Work", "/private/subagent-project", "vscode", "subagent"),
            ("visible-vscode", "Visible VS Code Task", "/private/deskbar", "vscode", "user"),
            ("visible-user", "Visible User Task", "/private/app-task", "user", "user"),
        ],
    )
    connection.commit()
    connection.close()

    payload = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl").payload()

    assert {item["label"] for item in payload["items"]} == {"Visible VS Code Task", "Visible User Task"}
    assert {item["project_label"] for item in payload["items"]} == {"deskbar", "app-task"}
    encoded = json.dumps(payload)
    for forbidden in (
        "internal-exec", "internal-subagent", "Internal Exec Prompt", "Subagent Internal Work",
        "delegated prompt", "subagent prompt", "JSONL title", "/private/",
    ):
        assert forbidden not in encoded


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
