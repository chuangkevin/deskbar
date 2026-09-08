from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from deskbar.ui import theme, usagewidget

OUTPUT_DIR = Path("/tmp/deskbar-usage-pi-preview")
X0 = 1540
W = 360
BASE_NOW = datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _metric(pct: float) -> dict:
    return {"used_pct": pct, "resets_at": _iso(BASE_NOW + timedelta(hours=3))}


def preview_sources() -> list[dict]:
    providers = [
        ("openai", "Work Codex", 18),
        ("openai", "Personal Codex", 73),
        ("claude", "Claude Team", 42),
        ("claude", "Claude Lab", 64),
        ("antigravity", "Gemini Agent", 31),
        ("custom", "Build Minutes", 86),
    ]
    records = []
    for order, (provider, label, pct) in enumerate(providers):
        records.append(
            {
                "source_id": f"preview-{order}",
                "provider": provider,
                "provider_account_id": f"acct-{order}",
                "display_name": label,
                "order": order,
                "visible": True,
                "enabled": True,
                "selected_metrics": ["weekly"],
                "stale_after_hours": 24,
                "hide_when_stale": True,
                "archived": False,
                "observation": {
                    "provider_account_id": f"acct-{order}",
                    "observed_at": _iso(BASE_NOW - timedelta(minutes=order + 1)),
                    "received_at": _iso(BASE_NOW - timedelta(minutes=order + 1)),
                    "metrics": {"weekly": _metric(pct)},
                },
                "created_at": _iso(BASE_NOW - timedelta(days=1, minutes=order)),
                "updated_at": _iso(BASE_NOW - timedelta(minutes=order)),
                "token_set": False,
                "status": "ok",
            }
        )
    return records


def render_preview(theme_name: str, page: int, records: list[dict]) -> Path:
    theme.set_theme(theme_name)
    now = BASE_NOW + timedelta(seconds=usagewidget.SOURCE_PAGE_S * page)
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    usagewidget.render(surf, None, now, X0, W, source_records=records)
    out = OUTPUT_DIR / f"usage-sources-{theme_name}-page{page + 1}.png"
    pygame.image.save(surf, out)
    return out


def main() -> list[Path]:
    pygame.init()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = preview_sources()
    page_count = len(usagewidget._source_pages(records, BASE_NOW))
    written = []
    for theme_name in ("light", "dark"):
        for page in range(page_count):
            written.append(render_preview(theme_name, page, records))
    pygame.quit()
    return written


if __name__ == "__main__":
    for path in main():
        print(path)
