from __future__ import annotations

import argparse
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed(state: AppState) -> None:
    now = datetime.now(timezone.utc)
    openai = state.create_usage_source(
        {
            "provider": "openai",
            "provider_account_id": "acct-work",
            "display_name": "Work Codex Account With A Long Readable Name",
            "selected_metrics": ["weekly"],
            "stale_after_hours": 24,
        }
    )
    state.observe_usage_source(
        openai["source_id"],
        {
            "provider_account_id": "acct-work",
            "observed_at": _iso(now - timedelta(minutes=7)),
            "metrics": {
                "weekly": {
                    "used_pct": 42,
                    "resets_at": _iso(now + timedelta(days=3)),
                }
            },
        },
    )
    claude = state.create_usage_source(
        {
            "provider": "claude",
            "display_name": "Claude Team",
            "stale_after_hours": 1,
        }
    )
    state.observe_usage_source(
        claude["source_id"],
        {
            "observed_at": _iso(now - timedelta(hours=3)),
            "metrics": {
                "session": {"used_pct": 66},
                "weekly": {"used_pct": 28},
            },
        },
    )
    state.create_usage_source(
        {
            "provider": "custom",
            "display_name": "Pending CI Quota Collector",
            "hide_when_stale": False,
        }
    )
    removed = state.create_usage_source(
        {
            "provider": "custom",
            "display_name": "Removed preview source",
        }
    )
    state.update_usage_source(removed["source_id"], {"archived": True})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local Deskbar usage source UI preview.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    tmpdir = tempfile.TemporaryDirectory(prefix="deskbar-usage-sources-")
    state = AppState(Path(tmpdir.name) / "usage_sources.json")
    _seed(state)
    settings = Settings()
    saved = []
    app = create_app(
        _FakeStore(),
        usage_state=state,
        settings_provider=settings,
        settings_lock=threading.Lock(),
        on_save=lambda _settings: saved.append(1),
    )
    print(f"Serving Deskbar usage source preview at http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
