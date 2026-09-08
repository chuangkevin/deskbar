"""右欄：Claude Code、Antigravity (Gemini) 與 OpenAI usage 油表。

全寬單欄、由上到下三區：
1. CLAUDE CODE 區：5H SESSION / 本週 / FABLE（FABLE 無資料時略過）
2. ANTIGRAVITY · GEMINI 區：5H / 本週（無資料時整區略過，不畫分隔線與標題）
3. OPENAI 區：本週（無資料時整區略過，不畫分隔線與標題）

usage 資料完全被動接收：Mac agent POST 到 deskbar 的 /api/usage。

2026-08-10 實機確認：舊三行制造成文字與橫條重疊；每組因此固定改為文字一行、橫條一行。
"""
from __future__ import annotations

from datetime import datetime

import pygame

from deskbar.claudeusage import WINDOW_S, fmt_countdown, over_pace, pace_pct
from deskbar.ui import theme

TITLE_Y = 2
SECTION_FIRST_GROUP = 20
GROUP_STEP = 40
SECTION_SEP_GAP = 10
SECTION_TITLE_GAP = 8
BAR_H = 9
BAR_RADIUS = 4
BAR_MARGIN = 0            # 橫條滿寬，讓獨立的第二行清楚呈現可用範圍。
BAR_Y_OFFSET = 19         # 文字列完整結束後再起橫條，避免字框與橫條相貼。
STALE_AFTER_S = 300       # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」
VERY_STALE_AFTER_S = 3600 # 超過這麼久，整組轉 muted 灰（agent 可能已經停了）
HIDE_AFTER_S = 24 * 60 * 60
DEFAULT_SOURCES = ("claude", "antigravity", "openai")
SOURCE_CARD_TOP = 24
SOURCE_CARD_H = 94
SOURCE_CARD_GAP = 10
SOURCE_CARDS_PER_PAGE = 3
SOURCE_PAGE_S = 10
SOURCE_BAR_H = 6
SOURCE_PROVIDER_LABELS = {
    "openai": "Codex",
    "claude": "Claude",
    "antigravity": "Antigravity",
    "custom": "Custom",
}
SOURCE_METRIC_LABELS = {
    "session": "5H SESSION",
    "5h": "5H",
    "weekly": "本週",
    "fable": "FABLE",
}
SOURCE_METRIC_ORDER = {"session": 0, "5h": 1, "weekly": 2, "fable": 3}


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _center_text(surface, s, size, color, x0, w, cy):
    img = theme.text_surface(s, size, color)
    surface.blit(img, img.get_rect(center=(x0 + w / 2, cy)))


def _level_color(pct: float, over: bool = False):
    # 正常用量一律 usage_bar 珊瑚橘；轉紅使用 usage_warn（針對低對比 TN 面板微調）。
    if over or pct > 85:
        return theme.C["usage_warn"]
    return theme.C["usage_bar"]


def _draw_group(surface, x0: float, w: float, y: float, label: str,
                pct: float | None, resets_at, now: datetime, muted: bool = False,
                window_s: float | None = None) -> None:
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    pct_color = theme.C["muted"] if muted else theme.C["text"]
    _text(surface, label, 15, label_color, x0, y)
    countdown = fmt_countdown(resets_at, now)
    _text(surface, f"剩 {countdown}", 12, theme.C["muted"],
          x0 + w - 52, y + 2, "topright")
    pct_label = f"{round(pct)}%" if pct is not None else "—"
    _text(surface, pct_label, 17, pct_color, x0 + w, y - 1, "topright", bold=True)

    bar_x = x0 + BAR_MARGIN
    bar_w = w - 2 * BAR_MARGIN
    bar_y = y + BAR_Y_OFFSET
    pygame.draw.rect(surface, theme.C["card"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     border_radius=BAR_RADIUS)
    pygame.draw.rect(surface, theme.C["panel_line"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     width=1, border_radius=BAR_RADIUS)
    over = (not muted and window_s is not None
            and over_pace(pct, resets_at, now, window_s))
    if pct is not None and pct > 0:
        fill_w = max(0.0, min(bar_w, bar_w * pct / 100))
        fill_color = theme.C["muted"] if muted else _level_color(pct, over)
        pygame.draw.rect(surface, fill_color,
                         pygame.Rect(round(bar_x), round(bar_y), round(fill_w), BAR_H),
                         border_radius=BAR_RADIUS)
    if window_s is not None and not muted:
        pace = pace_pct(resets_at, now, window_s)
        if pace is not None:
            px = bar_x + bar_w * pace / 100
            pygame.draw.line(surface, theme.C["text2"],
                             (round(px), round(bar_y - 3)),
                             (round(px), round(bar_y + BAR_H + 3)), 1)


def _parse_source_time(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _seconds_since(then: datetime, now: datetime) -> float:
    if now.tzinfo is not None and now.utcoffset() is not None:
        return (now - then.astimezone(now.tzinfo)).total_seconds()
    return (now - then.replace(tzinfo=None)).total_seconds()


def _source_stale_after_hours(source: dict) -> int:
    hours = source.get("stale_after_hours", 24)
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        return 24
    return hours


def _source_accent(provider: str, muted: bool = False):
    if muted:
        return theme.C["muted"]
    if provider == "openai":
        return theme.C["work_codex"]
    if provider == "claude":
        return theme.C["work_claude"]
    if provider == "antigravity" and theme.ACCOUNT_COLORS:
        return theme.ACCOUNT_COLORS[2][0]
    if provider == "custom":
        return theme.C["ok"]
    return theme.C["text2"]


def _metric_label(name: str) -> str:
    return SOURCE_METRIC_LABELS.get(name, name.upper())


def _metric_sort_key(name: str):
    return (SOURCE_METRIC_ORDER.get(name, 100), name)


def _source_metric_rows(source: dict) -> list[tuple[str, float, datetime | None, str]]:
    observation = source.get("observation")
    metrics = observation.get("metrics") if isinstance(observation, dict) else None
    if not isinstance(metrics, dict):
        return []
    selected = source.get("selected_metrics")
    if isinstance(selected, list) and selected:
        names = [name for name in selected if isinstance(name, str) and name in metrics]
    else:
        names = sorted((name for name in metrics if isinstance(name, str)),
                       key=_metric_sort_key)

    rows = []
    for name in names:
        payload = metrics.get(name)
        if not isinstance(payload, dict):
            continue
        pct = payload.get("used_pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            continue
        rows.append((_metric_label(name), float(pct),
                     _parse_source_time(payload.get("resets_at")), name))
    return rows


def _visible_source_chunks(source_records, now: datetime):
    chunks = []
    records = [source for source in source_records if isinstance(source, dict)]
    records.sort(key=lambda source: (
        source.get("order") if isinstance(source.get("order"), int) else 0,
        source.get("created_at") if isinstance(source.get("created_at"), str) else "",
        source.get("source_id") if isinstance(source.get("source_id"), str) else "",
    ))
    for source in records:
        if source.get("archived") is True:
            continue
        if source.get("enabled") is not True or source.get("visible") is not True:
            continue
        observation = source.get("observation")
        if not isinstance(observation, dict):
            continue
        observed_at = _parse_source_time(observation.get("observed_at"))
        if observed_at is None:
            continue
        age_s = _seconds_since(observed_at, now)
        stale = age_s > _source_stale_after_hours(source) * 3600
        hide_when_stale = source.get("hide_when_stale", True)
        if stale and hide_when_stale is not False:
            continue
        rows = _source_metric_rows(source)
        if not rows:
            continue
        chunk_count = (len(rows) + 1) // 2
        for chunk_index in range(chunk_count):
            start = chunk_index * 2
            chunks.append((source, rows[start:start + 2], age_s, stale,
                           chunk_index + 1, chunk_count))
    return chunks


def _source_pages(source_records, now: datetime):
    chunks = _visible_source_chunks(source_records, now)
    return [chunks[i:i + SOURCE_CARDS_PER_PAGE]
            for i in range(0, len(chunks), SOURCE_CARDS_PER_PAGE)]


def _carousel_page_index(now: datetime, page_count: int) -> int:
    if page_count <= 1:
        return 0
    return int(now.timestamp() // SOURCE_PAGE_S) % page_count


def _draw_source_metric(surface, x0: float, w: float, y: float, label: str,
                        pct: float, resets_at: datetime | None, now: datetime,
                        accent, muted: bool, metric_name: str) -> None:
    pct_label = f"{round(pct)}%"
    pct_font = theme.font(16, bold=True)
    countdown_label = f"剩 {fmt_countdown(resets_at, now)}"
    countdown_font = theme.font(12)
    pct_w = pct_font.size(pct_label)[0]
    countdown_w = countdown_font.size(countdown_label)[0]
    label_x = x0 + 14
    pct_right = x0 + w - 10
    countdown_right = pct_right - pct_w - 8
    show_countdown = countdown_right - countdown_w >= label_x + 72
    label_right = (countdown_right - countdown_w - 8
                   if show_countdown else pct_right - pct_w - 8)
    label_text = theme.truncate_to_width(label, theme.font(14),
                                         label_right - label_x)
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    pct_color = theme.C["muted"] if muted else theme.C["text"]
    _text(surface, label_text, 14, label_color, label_x, y)
    if show_countdown:
        _text(surface, countdown_label, 12, theme.C["muted"], countdown_right,
              y + 2, "topright")
    _text(surface, pct_label, 16, pct_color, pct_right, y - 1, "topright", bold=True)

    bar_x = x0 + 14
    bar_w = w - 28
    bar_y = y + 18
    pygame.draw.rect(surface, theme.C["bg"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), SOURCE_BAR_H),
                     border_radius=3)
    fill_w = max(0.0, min(bar_w, bar_w * pct / 100))
    if fill_w > 0:
        window_s = WINDOW_S.get(metric_name)
        over = window_s is not None and over_pace(pct, resets_at, now, window_s)
        fill = theme.C["muted"] if muted else (_level_color(pct, over) if over else accent)
        pygame.draw.rect(surface, fill,
                         pygame.Rect(round(bar_x), round(bar_y), round(fill_w), SOURCE_BAR_H),
                         border_radius=3)


def _draw_source_card(surface, x0: float, w: float, y: float, item, now: datetime) -> None:
    source, rows, age_s, stale, chunk_index, chunk_count = item
    muted = stale or age_s > VERY_STALE_AFTER_S
    provider = source.get("provider") if isinstance(source.get("provider"), str) else "custom"
    accent = _source_accent(provider, muted=False)
    card_rect = pygame.Rect(round(x0), round(y), round(w), SOURCE_CARD_H)
    pygame.draw.rect(surface, theme.C["card"], card_rect, border_radius=10)
    pygame.draw.rect(surface, theme.C["panel_line"], card_rect, width=1, border_radius=10)
    pygame.draw.rect(surface, _source_accent(provider, muted=muted),
                     pygame.Rect(card_rect.x, card_rect.y, 5, card_rect.h),
                     border_radius=3)

    label = source.get("display_name") if isinstance(source.get("display_name"), str) else provider
    chunk_suffix = f" {chunk_index}/{chunk_count}" if chunk_count > 1 else ""
    provider_label = SOURCE_PROVIDER_LABELS.get(provider, provider.title()) + chunk_suffix
    provider_color = theme.C["muted"] if muted else accent
    _text(surface, provider_label, 14, provider_color, x0 + 14, y + 7, bold=True)
    if age_s > STALE_AFTER_S:
        _text(surface, f"({max(0, int(age_s // 60))} 分前)", 14, theme.C["muted"],
              x0 + w - 10, y + 7, "topright")
    name_max = w - 28
    if age_s > STALE_AFTER_S:
        name_max -= 92
    display = theme.truncate_to_width(label, theme.font(16), name_max)
    _text(surface, display, 16, theme.C["muted"] if muted else theme.C["text"],
          x0 + 14, y + 25)

    for i, (metric_label, pct, resets_at, metric_name) in enumerate(rows[:2]):
        _draw_source_metric(surface, x0, w, y + 45 + i * 22, metric_label,
                            pct, resets_at, now, accent, muted, metric_name)


def _render_source_records(surface, source_records, now: datetime,
                           x0: float, w: float) -> None:
    pages = _source_pages(source_records, now)
    if not pages:
        return
    page_index = _carousel_page_index(now, len(pages))
    _text(surface, "AI USAGE", 14, theme.C["muted"], x0, TITLE_Y)
    if len(pages) > 1:
        _text(surface, f"{page_index + 1}/{len(pages)}", 14, theme.C["muted"],
              x0 + w, TITLE_Y, "topright")
    for i, item in enumerate(pages[page_index]):
        _draw_source_card(surface, x0, w,
                          SOURCE_CARD_TOP + i * (SOURCE_CARD_H + SOURCE_CARD_GAP),
                          item, now)


def visible_sections(usage, now: datetime, enabled_sources=None):
    """純顯示決策：回傳仍應畫出的 ``(title, groups, age)`` 區塊。

    每個 provider 以自己的成功抓取時間判斷新鮮度。Claude 在缺少
    ``claude_fetched_at`` 時可退回全域 ``fetched_at``（兩者語意相同）。
    Antigravity / OpenAI **不**退回 Claude／全域時間——舊快取缺分來源時間戳時
    以中性年齡 0 處理（不顯示「N 分前」、不誤標過期），避免把 Claude 失敗
    造成的舊 ``fetched_at`` 誤套到仍新鮮的 AG/OA 資料上。
    """
    if usage is None:
        return []
    enabled = set(DEFAULT_SOURCES if enabled_sources is None else enabled_sources)

    def age_for(field, *, fallback_to_global: bool):
        fetched = getattr(usage, field, None)
        if fetched is None and fallback_to_global:
            fetched = usage.fetched_at
        if fetched is None:
            return 0.0
        return (now - fetched).total_seconds()

    claude_groups = [
        ("5H SESSION", usage.session_pct, usage.session_resets_at,
         WINDOW_S["session"]),
        ("本週", usage.weekly_pct, usage.weekly_resets_at, WINDOW_S["weekly"]),
    ]
    if usage.fable_pct is not None:
        claude_groups.append(("FABLE", usage.fable_pct, usage.fable_resets_at,
                              WINDOW_S["fable"]))

    sections = []
    claude_age = age_for("claude_fetched_at", fallback_to_global=True)
    if "claude" in enabled and claude_age < HIDE_AFTER_S:
        sections.append(("CLAUDE CODE", claude_groups, claude_age))

    has_ag = (usage.ag_5h_pct is not None or usage.ag_weekly_pct is not None)
    ag_age = age_for("ag_fetched_at", fallback_to_global=False)
    if "antigravity" in enabled and has_ag and ag_age < HIDE_AFTER_S:
        sections.append(("ANTIGRAVITY · GEMINI", [
            ("5H", usage.ag_5h_pct, usage.ag_5h_resets_at, WINDOW_S["ag_5h"]),
            ("本週", usage.ag_weekly_pct, usage.ag_weekly_resets_at, WINDOW_S["ag_weekly"]),
        ], ag_age))

    oa_age = age_for("oa_fetched_at", fallback_to_global=False)
    if "openai" in enabled and usage.oa_weekly_pct is not None and oa_age < HIDE_AFTER_S:
        sections.append(("OPENAI", [
            ("本週", usage.oa_weekly_pct, usage.oa_weekly_resets_at, WINDOW_S["oa_weekly"]),
        ], oa_age))
    return sections


def render(surface, usage, now: datetime, x0: float = 1540, w: float = 360,
           enabled_sources=None, *, source_records=None) -> None:
    """畫可見 usage 區塊；未勾選、沒有資料或超過一天的來源完全不留痕跡。"""
    if source_records:
        _render_source_records(surface, source_records, now, x0, w)
        return

    sections = visible_sections(usage, now, enabled_sources)
    if not sections:
        return

    title_y = TITLE_Y
    previous_bar_bottom = None
    for i, (title, groups, age) in enumerate(sections):
        if i > 0:
            sep_y = previous_bar_bottom + SECTION_SEP_GAP
            pygame.draw.line(surface, theme.C["panel_line"],
                             (round(x0), round(sep_y)),
                             (round(x0 + w), round(sep_y)), 1)
            title_y = sep_y + SECTION_TITLE_GAP

        _text(surface, title, 14, theme.C["muted"], x0, title_y)
        if age > STALE_AFTER_S:
            _text(surface, f"({int(age // 60)} 分前)", 16, theme.C["muted"],
                  x0 + w, title_y, "topright")
        y = title_y + SECTION_FIRST_GROUP
        for label, pct, resets_at, win in groups:
            _draw_group(surface, x0, w, y, label, pct, resets_at, now,
                        muted=age > VERY_STALE_AFTER_S,
                        window_s=win)
            previous_bar_bottom = y + BAR_Y_OFFSET + BAR_H
            y += GROUP_STEP
