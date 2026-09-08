from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.claudeusage import UsageInfo
from deskbar.store import AppState
from deskbar.ui import theme, usagewidget

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=TZ)
X0 = 1540
W = 360


@pytest.fixture(autouse=True)
def _dark_theme():
    theme.set_theme("dark")
    yield
    theme.set_theme("dark")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _metric(pct: float, *, resets_at: datetime | str | None = None) -> dict:
    if resets_at is None:
        resets_at = NOW + timedelta(hours=2)
    payload = {"used_pct": pct}
    if isinstance(resets_at, datetime):
        payload["resets_at"] = _iso(resets_at)
    elif isinstance(resets_at, str):
        payload["resets_at"] = resets_at
    return payload


def _source(
    source_id: str,
    display_name: str,
    *,
    provider: str = "openai",
    account: str | None = None,
    order: int = 0,
    metrics: dict | None = None,
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    selected_metrics: list[str] | None = None,
    stale_after_hours: int = 24,
    hide_when_stale: bool = True,
    enabled: bool = True,
    visible: bool = True,
    archived: bool = False,
    status: str = "ok",
) -> dict:
    observed_at = observed_at or (NOW - timedelta(minutes=1))
    received_at = received_at or observed_at
    observation = None
    if metrics is not None:
        observation = {
            "provider_account_id": account,
            "observed_at": _iso(observed_at),
            "received_at": _iso(received_at),
            "metrics": metrics,
        }
    return {
        "source_id": source_id,
        "provider": provider,
        "provider_account_id": account,
        "display_name": display_name,
        "order": order,
        "visible": visible,
        "enabled": enabled,
        "selected_metrics": selected_metrics or [],
        "stale_after_hours": stale_after_hours,
        "hide_when_stale": hide_when_stale,
        "archived": archived,
        "observation": observation,
        "created_at": _iso(NOW - timedelta(days=1, minutes=order)),
        "updated_at": _iso(NOW - timedelta(minutes=order)),
        "token_set": False,
        "status": status,
    }


def _usage() -> UsageInfo:
    return UsageInfo(
        session_pct=42.0,
        session_resets_at=NOW + timedelta(hours=2),
        weekly_pct=61.0,
        weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=12.0,
        fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=NOW,
        oa_weekly_pct=88.0,
        oa_weekly_resets_at=NOW + timedelta(days=3),
    )


def _surf() -> pygame.Surface:
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def _render_texts(monkeypatch, records, *, at: datetime = NOW, usage=None):
    texts = []
    original = usagewidget._text

    def spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        rect = original(surface, s, size, color, x, y, anchor=anchor, bold=bold)
        texts.append({"text": s, "rect": rect, "size": size, "color": color})
        return rect

    monkeypatch.setattr(usagewidget, "_text", spy)
    surf = _surf()
    usagewidget.render(surf, usage, at, X0, W, source_records=records)
    return texts, surf


def _strings(texts) -> list[str]:
    return [item["text"] for item in texts]


def _usage_ink_rows(surf: pygame.Surface) -> list[int]:
    bg = theme.C["bg"]
    return [
        y
        for y in range(surf.get_height())
        if any(surf.get_at((x, y))[:3] != bg for x in range(X0, X0 + W))
    ]


def test_two_codex_accounts_render_distinct_labels_and_values_without_sum(monkeypatch):
    records = [
        _source("codex-work", "Work Codex", account="acct-work", order=0,
                metrics={"weekly": _metric(18)}),
        _source("codex-personal", "Personal Codex", account="acct-personal", order=1,
                metrics={"weekly": _metric(73)}),
    ]

    texts, surf = _render_texts(monkeypatch, records)
    rendered = _strings(texts)

    assert "Work Codex" in rendered
    assert "Personal Codex" in rendered
    assert "18%" in rendered
    assert "73%" in rendered
    assert "91%" not in rendered
    assert surf.get_at((X0 + 2, usagewidget.SOURCE_CARD_TOP + 30))[:3] == theme.C["work_codex"]


def test_hidden_disabled_archived_pending_and_hide_stale_sources_are_not_rendered(monkeypatch):
    stale_seen = NOW - timedelta(days=2)
    records = [
        _source("stale-visible", "Stale But Visible", provider="claude", order=0,
                metrics={"weekly": _metric(55)}, observed_at=stale_seen,
                received_at=NOW, hide_when_stale=False, status="ok"),
        _source("fresh", "Fresh Account", order=1, metrics={"weekly": _metric(25)}),
        _source("disabled", "Disabled Account", order=2, metrics={"weekly": _metric(30)},
                enabled=False),
        _source("hidden", "Hidden Account", order=3, metrics={"weekly": _metric(40)},
                visible=False),
        _source("archived", "Archived Account", order=4, metrics={"weekly": _metric(50)},
                archived=True),
        _source("pending", "Pending Account", order=5, metrics=None),
        _source("stale-hidden", "Stale Hidden", order=6, metrics={"weekly": _metric(60)},
                observed_at=stale_seen, received_at=NOW, status="ok"),
    ]

    texts, surf = _render_texts(monkeypatch, records)
    rendered = _strings(texts)

    assert "Stale But Visible" in rendered
    assert "Fresh Account" in rendered
    assert "(2880 分前)" in rendered
    for hidden in [
        "Disabled Account",
        "Hidden Account",
        "Archived Account",
        "Pending Account",
        "Stale Hidden",
    ]:
        assert hidden not in rendered
    muted_bar_y = usagewidget.SOURCE_CARD_TOP + 45 + 18 + usagewidget.SOURCE_BAR_H // 2
    assert surf.get_at((X0 + 20, muted_bar_y))[:3] == theme.C["muted"]


def test_selected_metrics_filter_and_invalid_reset_countdown_is_safe(monkeypatch):
    records = [
        _source(
            "claude-team",
            "Claude Team",
            provider="claude",
            metrics={
                "session": _metric(11),
                "weekly": _metric(22, resets_at="not-a-date"),
                "fable": _metric(33),
            },
            selected_metrics=["weekly", "fable"],
        ),
    ]

    texts, _surf = _render_texts(monkeypatch, records)
    rendered = _strings(texts)

    assert "本週" in rendered
    assert "FABLE" in rendered
    assert "22%" in rendered
    assert "33%" in rendered
    assert "剩 —" in rendered
    assert "5H SESSION" not in rendered
    assert "11%" not in rendered


def test_six_plus_sources_and_metric_overflow_are_reachable_by_deterministic_carousel(monkeypatch):
    records = [
        _source(
            "acct-0",
            "Account 0",
            order=0,
            metrics={f"m{i}": _metric(10 + i) for i in range(1, 6)},
        )
    ]
    records.extend(
        _source(f"acct-{i}", f"Account {i}", order=i,
                metrics={"weekly": _metric(20 + i)})
        for i in range(1, 7)
    )
    pages = usagewidget._source_pages(records, NOW)
    assert len(pages) == 3
    assert all(len(chunk[1]) <= 2 for page in pages for chunk in page)

    seen: set[str] = set()
    counters: set[str] = set()
    for i in range(len(pages)):
        texts, _surf = _render_texts(monkeypatch, records, at=NOW + timedelta(seconds=10 * i))
        rendered = _strings(texts)
        seen.update(text for text in rendered if text.startswith("Account "))
        counters.update(text for text in rendered if text in {"1/3", "2/3", "3/3"})

    assert {f"Account {i}" for i in range(7)} <= seen
    assert counters == {"1/3", "2/3", "3/3"}


def test_source_cards_stay_inside_existing_y340_right_column_budget():
    records = [
        _source(f"acct-{i}", f"Account {i}", order=i,
                metrics={"weekly": _metric(20 + i)})
        for i in range(6)
    ]
    surf = _surf()

    usagewidget.render(surf, None, NOW, X0, W, source_records=records)

    rows = _usage_ink_rows(surf)
    assert rows
    assert max(rows) <= 340


def test_archived_registry_tombstone_blocks_flat_legacy_fallback(tmp_path):
    path = tmp_path / "usage_sources.json"
    state = AppState(path)
    source = state.create_usage_source(
        {"provider": "codex", "provider_account_id": "acct", "display_name": "Archived Codex"}
    )
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    state.observe_usage_source(
        source["source_id"],
        {
            "provider_account_id": "acct",
            "observed_at": observed_at.isoformat(),
            "metrics": {"weekly": {"used_pct": 44}},
        },
    )
    state.update_usage_source(source["source_id"], {"archived": True})

    reloaded = AppState(path)
    reloaded.set_usage(_usage())
    snap = reloaded.snapshot()
    assert snap.usage_sources
    assert snap.usage_sources[0]["archived"] is True

    surf = _surf()
    usagewidget.render(surf, snap.usage, NOW, X0, W,
                       source_records=snap.usage_sources)

    assert _usage_ink_rows(surf) == []
