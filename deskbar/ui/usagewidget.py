"""右欄：Claude Code、Antigravity (Gemini) 與 OpenAI usage 油表。

兩欄並排（2026-09 右欄加寬 360→600 後）：visible_sections 算出的區塊保序切成
兩段（左欄＝前段、右欄＝後段，不打亂閱讀順序），切點選各欄高度最平均者
（見 split_columns）；每欄各自走 fit_layout／裁區，欄寬＝(總寬−中縫)/欄數。
只有一欄有內容時不留空欄。

各區內容：
1. CLAUDE CODE 區：5H SESSION / 本週 / FABLE（FABLE 無資料時略過）
2. ANTIGRAVITY · GEMINI 區：5H / 本週（無資料時整區略過，不畫分隔線與標題）
3. OPENAI 區：每個帳號一區（無資料時整區略過，不畫分隔線與標題）
4. CURSOR 區：本期（帳單週期約一個月；無資料時整區略過）
5. COMMANDCODE 區：5H / 本週（無資料時整區略過）

2026-09-11 起來源多到一欄放不下（5 區 9 列）：render() 會先算總高度，超過可用高度時
把垂直間距等比例縮小（只縮間距，不縮字級、不縮長條），縮到底線仍放不下才裁掉最後幾區。
兩欄化之後每欄只負擔約一半高度，極少需要壓縮或裁區。

usage 資料完全被動接收：Mac agent POST 到 deskbar 的 /api/usage。

2026-08-10 實機確認：舊三行制造成文字與橫條重疊；每組因此固定改為文字一行、橫條一行。

下次付款日（2026-09-22）：visible_sections 回傳的每個 section 帶第 4 個元素
key（claude / antigravity / openai:<account_id> / cursor / commandcode；
無帳號資料的舊 OPENAI 區用 openai）。billing_for(key, usage, billing_dates, now)
決定每區的下次付款日：手動（手機設定頁填的每月固定日）優先於自動
（cursor→cu_billing_at、commandcode→cc_billing_at）；
兩者都沒有就不畫。
"""
from __future__ import annotations

from datetime import date, datetime

import pygame

from deskbar.claudeusage import WINDOW_S, fmt_countdown, over_pace, pace_pct
from deskbar.ui import theme

TITLE_Y = 16              # 第一張卡片的頂邊；頂緣日光帶（sunstrip，8px）在上面，不能蓋到
SECTION_FIRST_GROUP = 20
GROUP_STEP = 40
SECTION_SEP_GAP = 10
SECTION_TITLE_GAP = 8
CARD_PAD_X = 10           # 卡片內左右留白
CARD_PAD_BOTTOM = 8       # 最後一條橫條到卡片底邊
CARD_RADIUS = 8
BAR_H = 9
BAR_RADIUS = 4
BAR_MARGIN = 0            # 橫條滿寬，讓獨立的第二行清楚呈現可用範圍。
BAR_Y_OFFSET = 19         # 文字列完整結束後再起橫條，避免字框與橫條相貼。
# 2026-09-10：所有來源的刷新間隔都是 300 秒，門檻也放 300 會讓每一區在下次刷新前
# 一律掛上「(5 分前)」——變成常駐雜訊而不是警訊。放到 900 秒＝連續漏三輪才提醒。
STALE_AFTER_S = 900       # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」
VERY_STALE_AFTER_S = 3600 # 超過這麼久，整組轉 muted 灰（agent 可能已經停了）
HIDE_AFTER_S = 24 * 60 * 60
DEFAULT_SOURCES = ("claude", "antigravity", "openai", "cursor", "commandcode")


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _center_text(surface, s, size, color, x0, w, cy):
    img = theme.text_surface(s, size, color)
    surface.blit(img, img.get_rect(center=(x0 + w / 2, cy)))


def fit_title(title: str, max_w: float, size: int = 14) -> str:
    """純函數：標題放不進 max_w 就從尾端裁掉、補「…」；放得下原樣回傳。"""
    font = theme.font(size)
    if font.size(title)[0] <= max_w:
        return title
    ellipsis = "…"
    for cut in range(len(title) - 1, 0, -1):
        cand = title[:cut].rstrip(" ·") + ellipsis
        if font.size(cand)[0] <= max_w:
            return cand
    return ellipsis


def is_exhausted(pct) -> bool:
    """額度用完＝這個來源現在不能用。>=100 就算，浮點誤差不必特別容忍。"""
    if pct is None or isinstance(pct, bool):
        return False
    try:
        return float(pct) >= 100
    except (TypeError, ValueError):
        return False


def _level_color(pct: float, over: bool = False):
    # 正常用量一律 usage_bar 珊瑚橘；快用完 usage_warn 橘紅；
    # 用完（>=100%）走 usage_full 純紅——那代表現在根本不能用，要一眼看得出差別。
    if is_exhausted(pct):
        return theme.C["usage_full"]
    if over or pct > 85:
        return theme.C["usage_warn"]
    return theme.C["usage_bar"]


def _draw_group(surface, x0: float, w: float, y: float, label: str,
                pct: float | None, resets_at, now: datetime, muted: bool = False,
                window_s: float | None = None) -> None:
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    if muted:
        pct_color = theme.C["muted"]
    elif is_exhausted(pct):
        pct_color = theme.C["usage_full"]
    else:
        pct_color = theme.C["text"]
    _text(surface, label, 15, label_color, x0, y)
    countdown = fmt_countdown(resets_at, now)
    _text(surface, f"剩 {countdown}", 12, theme.C["muted"],
          x0 + w - 52, y + 2, "topright")
    pct_label = f"{round(pct)}%" if pct is not None else "—"
    _text(surface, pct_label, 17, pct_color, x0 + w, y - 1, "topright", bold=True)

    bar_x = x0 + BAR_MARGIN
    bar_w = w - 2 * BAR_MARGIN
    bar_y = y + BAR_Y_OFFSET
    pygame.draw.rect(surface, theme.C["grid"],
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


def next_monthly(date_str: str, today: date) -> date | None:
    """每月固定日推到「今天（含）之後最近一次同日」。

    存 YYYY-MM-DD，只取日；月份沒那一天取該月最後一天。壞字串回 None。"""
    import calendar as _calendar
    try:
        day = date.fromisoformat(date_str).day
    except (ValueError, TypeError, AttributeError):
        return None
    year, month = today.year, today.month
    last = _calendar.monthrange(year, month)[1]
    cand = date(year, month, min(day, last))
    if cand >= today:
        return cand
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def billing_for(key, usage, billing_dates: dict, now: datetime) -> tuple[date, str] | None:
    """回 (付款日, 來源 manual/auto)；手動優先，兩者都沒有回 None。

    自動：cursor→cu_billing_at、commandcode→cc_billing_at
    （取 .date()，用 now 的 tz）；其他 key 只看手動。"""
    manual = (billing_dates or {}).get(key) if isinstance(billing_dates, dict) else None
    if isinstance(manual, str) and manual.strip():
        today = now.date() if isinstance(now, datetime) else now
        nxt = next_monthly(manual.strip(), today)
        if nxt is not None:
            return nxt, "manual"
    auto_dt = None
    if usage is not None:
        if key == "cursor":
            auto_dt = getattr(usage, "cu_billing_at", None)
        elif key == "commandcode":
            auto_dt = getattr(usage, "cc_billing_at", None)
        elif isinstance(key, str) and key.startswith("commandcode:"):
            account_id = key[len("commandcode:"):]
            for account in getattr(usage, "cc_accounts", ()) or ():
                if getattr(account, "account_id", None) == account_id:
                    auto_dt = getattr(account, "billing_at", None)
                    break
    if auto_dt is None:
        return None
    try:
        tz = now.tzinfo if isinstance(now, datetime) else None
        if isinstance(auto_dt, datetime):
            d = auto_dt.astimezone(tz).date() if tz is not None else auto_dt.date()
        elif isinstance(auto_dt, date):
            d = auto_dt
        else:
            return None
    except (ValueError, OSError, OverflowError):
        return None
    return d, "auto"


def visible_sections(usage, now: datetime, enabled_sources=None, oa_aliases=None,
                     oa_hidden=None, cc_aliases=None, cc_hidden=None):
    """純顯示決策：回傳仍應畫出的 ``(title, groups, age, key)`` 區塊。

    每個 provider 以自己的成功抓取時間判斷新鮮度。Claude 在缺少
    ``claude_fetched_at`` 時可退回全域 ``fetched_at``（兩者語意相同）。
    Antigravity / 舊單一 OpenAI 區塊 **不**退回 Claude／全域時間——舊快取缺分來源
    時間戳時以中性年齡 0 處理（不顯示「N 分前」、不誤標過期）。多帳號 OpenAI
    則依帳號自己的 ``fetched_at``，再退回 OA / 全域時間，以相容新 producer payload。
    多帳號 CommandCode 同理：依帳號自己的 ``fetched_at``，再退回 CC / 全域時間；
    ``cc_accounts`` 為空時退回舊的單帳號 ``cc_*`` 欄位。
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

    def age_for_oa_account(account):
        fetched = account.fetched_at or getattr(usage, "oa_fetched_at", None) or usage.fetched_at
        return (now - fetched).total_seconds() if fetched is not None else 0.0

    def age_for_cc_account(account):
        fetched = (getattr(account, "fetched_at", None)
                   or getattr(usage, "cc_fetched_at", None) or usage.fetched_at)
        return (now - fetched).total_seconds() if fetched is not None else 0.0

    aliases = oa_aliases or {}
    hidden = set(oa_hidden or ())
    cc_alias_map = cc_aliases or {}
    cc_hidden_set = set(cc_hidden or ())

    def oa_title(account):
        alias = aliases.get(account.account_id, "")
        if alias:
            return f"OPENAI · {alias}"
        if account.name:
            return f"OPENAI · {account.name.upper()}"
        return "OPENAI"

    def cc_title(account):
        alias = cc_alias_map.get(account.account_id, "")
        if alias:
            return f"COMMANDCODE · {alias}"
        if getattr(account, "name", ""):
            return f"COMMANDCODE · {account.name.upper()}"
        return "COMMANDCODE"

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
        sections.append(("CLAUDE CODE", claude_groups, claude_age, "claude"))

    has_ag = (usage.ag_5h_pct is not None or usage.ag_weekly_pct is not None)
    ag_age = age_for("ag_fetched_at", fallback_to_global=False)
    if "antigravity" in enabled and has_ag and ag_age < HIDE_AFTER_S:
        sections.append(("ANTIGRAVITY · GEMINI", [
            ("5H", usage.ag_5h_pct, usage.ag_5h_resets_at, WINDOW_S["ag_5h"]),
            ("本週", usage.ag_weekly_pct, usage.ag_weekly_resets_at, WINDOW_S["ag_weekly"]),
        ], ag_age, "antigravity"))

    if "openai" in enabled:
        oa_accounts = getattr(usage, "oa_accounts", ())
        if oa_accounts:
            for account in oa_accounts:
                if account.account_id in hidden:
                    continue
                oa_age = age_for_oa_account(account)
                if oa_age < HIDE_AFTER_S:
                    sections.append((oa_title(account), [
                        ("本週", account.weekly_pct, account.weekly_resets_at, WINDOW_S["oa_weekly"]),
                    ], oa_age, f"openai:{account.account_id}"))
        else:
            oa_age = age_for("oa_fetched_at", fallback_to_global=False)
            if usage.oa_weekly_pct is not None and oa_age < HIDE_AFTER_S:
                sections.append(("OPENAI", [
                    ("本週", usage.oa_weekly_pct, usage.oa_weekly_resets_at, WINDOW_S["oa_weekly"]),
                ], oa_age, "openai"))

    if "cursor" in enabled:
        cu_age = age_for("cu_fetched_at", fallback_to_global=False)
        cu_pct = getattr(usage, "cu_pct", None)
        if cu_pct is not None and cu_age < HIDE_AFTER_S:
            # Cursor 的視窗是帳單週期（約一個月），不是一週——標籤用「本期」。
            sections.append(("CURSOR", [
                ("本期", cu_pct, getattr(usage, "cu_resets_at", None), WINDOW_S["cu"]),
            ], cu_age, "cursor"))

    if "commandcode" in enabled:
        cc_accounts = getattr(usage, "cc_accounts", ())
        if cc_accounts:
            for account in cc_accounts:
                if account.account_id in cc_hidden_set:
                    continue
                cc_age = age_for_cc_account(account)
                if cc_age < HIDE_AFTER_S:
                    sections.append((cc_title(account), [
                        ("5H", account.five_hour_pct, account.five_hour_resets_at, WINDOW_S["cc_5h"]),
                        ("本週", account.weekly_pct, account.weekly_resets_at, WINDOW_S["cc_weekly"]),
                    ], cc_age, f"commandcode:{account.account_id}"))
        else:
            cc_age = age_for("cc_fetched_at", fallback_to_global=False)
            cc_5h = getattr(usage, "cc_5h_pct", None)
            cc_weekly = getattr(usage, "cc_weekly_pct", None)
            if (cc_5h is not None or cc_weekly is not None) and cc_age < HIDE_AFTER_S:
                sections.append(("COMMANDCODE", [
                    ("5H", cc_5h, getattr(usage, "cc_5h_resets_at", None), WINDOW_S["cc_5h"]),
                    ("本週", cc_weekly, getattr(usage, "cc_weekly_resets_at", None), WINDOW_S["cc_weekly"]),
                ], cc_age, "commandcode"))
    return sections


MIN_GROUP_STEP = 32       # 壓縮下限：字列 17px＋橫條 9px＋餘裕，再低會貼在一起
MIN_SECTION_GAP = 10      # sep_gap + title_gap 合計的下限
DEFAULT_HEIGHT = 480 - 6  # 右欄可用高度（螢幕 480，底下留一點邊；layout_height 已含 TITLE_Y 起點）


def layout_height(group_counts, *, group_step=GROUP_STEP, sep_gap=SECTION_SEP_GAP,
                  title_gap=SECTION_TITLE_GAP, first_group=SECTION_FIRST_GROUP) -> float:
    """純函數：這組區塊照給定間距畫完，最後一張卡片的底邊在哪個 y。

    每區一張卡片：卡片頂 → title_gap → 標題 → first_group → 各列（group_step）
    → 最後橫條底 → CARD_PAD_BOTTOM → 卡片底；卡片之間空 sep_gap。"""
    if not group_counts:
        return 0.0
    y = TITLE_Y
    bottom = 0.0
    for i, n in enumerate(group_counts):
        if i > 0:
            y = bottom + sep_gap
        bar_bottom = y + title_gap + first_group + (n - 1) * group_step + BAR_Y_OFFSET + BAR_H
        bottom = bar_bottom + CARD_PAD_BOTTOM
    return bottom


def fit_layout(group_counts, height: float = DEFAULT_HEIGHT) -> dict:
    """純函數：放得下就用預設間距；放不下就等比例縮間距（不縮字級／橫條），
    縮到下限還放不下就回 max_sections 讓呼叫端裁掉最後幾區。"""
    default = {"group_step": GROUP_STEP, "sep_gap": SECTION_SEP_GAP,
               "title_gap": SECTION_TITLE_GAP, "first_group": SECTION_FIRST_GROUP,
               "max_sections": len(group_counts), "compact": False}
    if layout_height(group_counts) <= height:
        return default
    # 二分搜尋一個 0..1 的縮放係數，套在三個「可伸縮」的間距上。
    def scaled(k):
        return {
            "group_step": max(MIN_GROUP_STEP, round(GROUP_STEP * k)),
            "sep_gap": max(MIN_SECTION_GAP // 2, round(SECTION_SEP_GAP * k)),
            "title_gap": max(MIN_SECTION_GAP - MIN_SECTION_GAP // 2, round(SECTION_TITLE_GAP * k)),
            "first_group": max(18, round(SECTION_FIRST_GROUP * k)),
        }
    lo, hi = 0.0, 1.0
    best = scaled(0.0)
    for _ in range(12):
        mid = (lo + hi) / 2
        cand = scaled(mid)
        if layout_height(group_counts, **cand) <= height:
            best, lo = cand, mid
        else:
            hi = mid
    if layout_height(group_counts, **best) <= height:
        return {**best, "max_sections": len(group_counts), "compact": True}
    # 連最緊也放不下：從尾端裁區塊
    for keep in range(len(group_counts) - 1, 0, -1):
        if layout_height(group_counts[:keep], **best) <= height:
            return {**best, "max_sections": keep, "compact": True}
    return {**best, "max_sections": 1, "compact": True}


def split_columns(sections, columns: int = 2) -> list[list]:
    """保序切成 ``columns`` 段（左欄是前段、右欄是後段，不打亂閱讀順序）。

    切點選「各欄高度最平均」的那一個；高度用預設間距的
    ``layout_height([len(groups) ...])`` 算。``columns=1`` 或只有 1 個
    section 時原樣回傳一欄；空 list 回 ``[]``。"""
    sections = list(sections)
    if not sections:
        return []
    if columns <= 1 or len(sections) == 1:
        return [sections]
    counts = [len(groups) for _t, groups, _a, _k in sections]

    def height_of(part):
        return layout_height(part) if part else 0.0

    best_cut, best_diff = 1, None
    for cut in range(1, len(counts)):
        diff = abs(height_of(counts[:cut]) - height_of(counts[cut:]))
        if best_diff is None or diff < best_diff:
            best_diff, best_cut = diff, cut
    return [sections[:best_cut], sections[best_cut:]]


def _render_column(surface, sections, now: datetime, x0: float, w: float,
                   height: float = DEFAULT_HEIGHT, usage=None,
                   billing_dates: dict | None = None) -> None:
    """畫一欄 usage 區塊（fit_layout → 逐區畫，含放不下時的裁區）。"""
    if not sections:
        return
    layout = fit_layout([len(groups) for _t, groups, _a, _k in sections], height)
    sections = sections[:layout["max_sections"]]

    inner_x = x0 + CARD_PAD_X
    inner_w = w - 2 * CARD_PAD_X
    card_top = TITLE_Y
    for i, (title, groups, age, key) in enumerate(sections):
        # 每個 provider 一張卡片（2026-09-22 Kevin 實機回報：分隔線不夠明顯、
        # 兩欄之後要對齊）：卡片底色＋細框把每區框起來，內容縮排 CARD_PAD_X。
        title_y = card_top + layout["title_gap"]
        bar_bottom = (title_y + layout["first_group"]
                      + (len(groups) - 1) * layout["group_step"] + BAR_Y_OFFSET + BAR_H)
        card_bottom = bar_bottom + CARD_PAD_BOTTOM
        card = pygame.Rect(round(x0), round(card_top), round(w), round(card_bottom - card_top))
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=CARD_RADIUS)
        pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=CARD_RADIUS)

        billing = billing_for(key, usage, billing_dates or {}, now)
        billing_w = 0.0
        billing_color = theme.C["muted"]
        billing_label = None
        if billing is not None:
            pay_date, _src = billing
            days_left = (pay_date - now.date()).days
            billing_label = f"付款 {pay_date.month}/{pay_date.day}"
            billing_color = theme.C["usage_warn"] if days_left <= 3 else theme.C["muted"]
            billing_w = theme.font(12).size(billing_label)[0]
            _text(surface, billing_label, 12, billing_color, inner_x + inner_w, title_y, "topright")
        right_used = billing_w + 8 if billing_label is not None else 0.0
        if age > STALE_AFTER_S:
            stale_label = f"({int(age // 60)} 分前)"
            _text(surface, stale_label, 16, theme.C["muted"],
                  inner_x + inner_w - right_used, title_y, "topright")
            right_used += theme.font(16).size(stale_label)[0] + 8
        # 標題太長（例：COMMANDCODE · KEVIN202511180YSI）會撞到右邊的付款日／過期字樣，
        # 超過可用寬度就截斷加「…」；要好看的名字請在手機設定頁填別名。
        _text(surface, fit_title(title, inner_w - right_used, 14), 14, theme.C["muted"], inner_x, title_y)
        y = title_y + layout["first_group"]
        for label, pct, resets_at, win in groups:
            _draw_group(surface, inner_x, inner_w, y, label, pct, resets_at, now,
                        muted=age > VERY_STALE_AFTER_S,
                        window_s=win)
            y += layout["group_step"]
        card_top = card_bottom + layout["sep_gap"]


def render(surface, usage, now: datetime, x0: float = 1540, w: float = 360,
           enabled_sources=None, oa_aliases=None, oa_hidden=None,
           cc_aliases=None, cc_hidden=None,
           height: float = DEFAULT_HEIGHT,
           columns: int = 2, gap: float = 20,
           billing_dates: dict | None = None) -> None:
    """畫可見 usage 區塊；未勾選、沒有資料或超過一天的來源完全不留痕跡。
    放不下時自動縮間距（見 fit_layout）。預設兩欄並排；只有一欄有內容時
    不留空欄（split_columns 回幾欄就畫幾欄，欄寬照實際欄數算）。"""
    sections = visible_sections(usage, now, enabled_sources, oa_aliases, oa_hidden,
                                cc_aliases, cc_hidden)
    if not sections:
        return

    cols = split_columns(sections, columns)
    n = len(cols)
    col_w = (w - gap * (n - 1)) / n if n > 1 else w
    for i, col in enumerate(cols):
        _render_column(surface, col, now, x0 + i * (col_w + gap), col_w, height,
                       usage, billing_dates)
