import ast
import json
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
                                    "lastActivityAt": recent.isoformat(), "title": "private title"}), encoding="utf-8")
    import os
    os.utime(app_file, (recent.timestamp(), recent.timestamp()))
    _write_jsonl(tmp_path / ".codex/sessions/2026/08/10/stale.jsonl", [
        {"session_meta": {"session_id": "stale", "cwd": "/private/stale"}},
        {"timestamp": stale.isoformat()},
    ], stale)

    collector = SessionCollector(home=tmp_path, now=lambda: NOW, token_factory=lambda: "opaque-token-abcdefghijkl")
    payload = collector.payload()
    assert len(payload["items"]) == 2
    assert {item["label"] for item in payload["items"]} == {"deskbar", "other"}
    encoded = json.dumps(payload)
    for forbidden in ("native-codex", "native-claude", "private title", "not for Pi", "/private/"):
        assert forbidden not in encoded


def test_missing_source_is_reported_without_crashing(tmp_path):
    payload = SessionCollector(home=tmp_path, now=lambda: NOW).payload()
    assert payload["items"] == []
    assert {tuple(error.items()) for error in payload["errors"]} == {
        (("source", "claude"), ("code", "unavailable")),
        (("source", "codex"), ("code", "unavailable")),
    }


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
    assert calls == [((['/usr/bin/open', '-a', 'ChatGPT'],), {'check': False, 'timeout': 10, 'shell': False})]
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
