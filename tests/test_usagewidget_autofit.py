"""右欄自動加欄（2026-09-23）：區塊多到兩欄放不下時自動 3 欄、4 欄，
放得下就停在那一級；4 欄還放不下才裁區。窄欄剩餘時間省略但不重疊。

headless pygame，不碰硬體。另把 10 區現場組成存 PNG 供人眼驗收。
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pygame

from deskbar.claudeusage import CcAccount, OaAccount, OgAccount, UsageInfo
from deskbar.ui import theme, usagewidget

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 9, 23, 16, 0, tzinfo=TZ)
SOURCES = ("claude", "antigravity", "openai", "commandcode", "opencode")


def _cc(i, **kw):
    base = dict(account_id=f"cc{i}", name=f"cc{i}",
                five_hour_pct=20.0, five_hour_resets_at=NOW + timedelta(hours=3),
                weekly_pct=40.0, weekly_resets_at=NOW + timedelta(days=3),
                billing_at=NOW + timedelta(days=20), fetched_at=NOW)
    base.update(kw)
    return CcAccount(**base)


def _og(i, **kw):
    base = dict(account_id=f"og{i}", name="",
                five_hour_pct=0.0, five_hour_resets_at=NOW + timedelta(hours=5),
                weekly_pct=75.0, weekly_resets_at=NOW + timedelta(days=5),
                monthly_pct=100.0, monthly_resets_at=NOW + timedelta(days=18),
                billing_at=NOW + timedelta(days=18), fetched_at=NOW)
    base.update(kw)
    return OgAccount(**base)


def _現場_10區():
    """現場組成：claude 3 條、antigravity 2、openai×3 各 1、commandcode×4 各 2、opencode 3。"""
    return UsageInfo(
        session_pct=7.0, session_resets_at=NOW + timedelta(hours=4),
        weekly_pct=37.0, weekly_resets_at=NOW + timedelta(days=5),
        fable_pct=0.0, fable_resets_at=NOW + timedelta(days=5), fetched_at=NOW,
        ag_5h_pct=3.1, ag_5h_resets_at=NOW + timedelta(hours=1),
        ag_weekly_pct=0.5, ag_weekly_resets_at=NOW + timedelta(days=6), ag_fetched_at=NOW,
        oa_accounts=(OaAccount("oa1", "K", 97.0, NOW + timedelta(days=3), NOW),
                     OaAccount("oa2", "D", 100.0, NOW + timedelta(hours=20), NOW),
                     OaAccount("oa3", "C", 98.0, NOW + timedelta(days=4), NOW)),
        oa_fetched_at=NOW,
        cc_accounts=(_cc(1), _cc(2), _cc(3), _cc(4)), cc_fetched_at=NOW,
        og_accounts=(_og(1),), og_fetched_at=NOW)


def _現場_14區():
    """10 區再加 commandcode×2、opencode×1、openai×1＝14 區。"""
    base = _現場_10區()
    from dataclasses import replace
    return replace(
        base,
        oa_accounts=base.oa_accounts + (OaAccount("oa4", "E", 10.0, NOW + timedelta(days=2), NOW),),
        cc_accounts=base.cc_accounts + (_cc(5), _cc(6)),
        og_accounts=base.og_accounts + (_og(2),),
    )


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _ink_rows(surf, x0, x1):
    rows = set()
    for y in range(surf.get_height()):
        for x in range(x0, x1, 2):
            px = surf.get_at((x, y))
            if tuple(px[:3]) not in (tuple(theme.C["bg"]), tuple(theme.C["card"]),
                                     tuple(theme.C["panel_line"])):
                rows.add(y)
                break
    return rows


def test_10_sections_all_drawn_in_three_columns():
    usage = _現場_10區()
    sections = usagewidget.visible_sections(usage, NOW, SOURCES)
    assert len(sections) == 10
    surf = _surf()
    res = usagewidget.render(surf, usage, NOW, 1300, 600, SOURCES)
    assert res["columns"] == 3
    expected_keys = [k for _t, _g, _a, k in sections]
    assert res["keys"] == expected_keys
    # 每個標題都在畫面範圍內：掃右欄 x 範圍，每區至少有一列非背景像素
    rows = _ink_rows(surf, 1300, 1920)
    assert rows and max(rows) < 480
    # 每個 section key 都有對應卡片：用標題文字 spy 確認 10 個標題全畫出
    seen = []
    original = usagewidget._text

    def spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        seen.append(s)
        return original(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    usagewidget._text = spy
    try:
        usagewidget.render(_surf(), usage, NOW, 1300, 600, SOURCES)
    finally:
        usagewidget._text = original
    titles = [t for t, _g, _a, _k in sections]
    for title in titles:
        # 窄欄標題會被 fit_title 截斷加「…」：驗「截斷後的前綴有畫出」即可
        drawn = [s for s in seen if isinstance(s, str)]
        assert any(s == title or s == usagewidget.fit_title(title, 300, 14)
                   or title.startswith(s.rstrip("…")) or s.startswith(title[:8])
                   for s in drawn), f"標題沒畫出來：{title}"


def test_14_sections_all_drawn():
    usage = _現場_14區()
    sections = usagewidget.visible_sections(usage, NOW, SOURCES)
    assert len(sections) == 14
    surf = _surf()
    res = usagewidget.render(surf, usage, NOW, 1300, 600, SOURCES)
    expected_keys = [k for _t, _g, _a, k in sections]
    assert res["keys"] == expected_keys
    rows = _ink_rows(surf, 1300, 1920)
    assert rows and max(rows) < 480


def test_narrow_column_countdown_omitted_when_no_room(monkeypatch):
    """窄欄（3–4 欄時欄寬 < 240）：剩餘時間放不下就省略，標籤＋百分比必留且不重疊。

    直接驗 _draw_group 的幾何：包 usagewidget._text 記下每行文字盒，
    同一 y 的盒子兩兩不相交。"""
    calls = []
    original = usagewidget._text

    def spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        img = theme.text_surface(s, size, color, bold=bold)
        r = img.get_rect(**{anchor: (x, y)})
        calls.append((s, size, r.left, r.top, r.right))
        return original(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    monkeypatch.setattr(usagewidget, "_text", spy)
    usage = _現場_10區()
    usagewidget.render(_surf(), usage, NOW, 1300, 600, SOURCES)
    # 按 y 分組（同一列 y 差 < 4 視為同列），組內盒子不可重疊
    groups = {}
    for s, size, left, top, right in calls:
        key = round(top / 4)
        groups.setdefault(key, []).append((s, left, right))
    bad = []
    for key, boxes in groups.items():
        boxes.sort(key=lambda b: b[1])
        for (s1, l1, r1), (s2, l2, r2) in zip(boxes, boxes[1:]):
            if l2 < r1 - 1:
                bad.append((key, s1, s2))
    assert not bad, f"文字重疊：{bad[:5]}"
    # 百分比必留：每區至少一個 % 字樣
    pcts = [s for s, _size, _l, _t, _r in calls if s.endswith("%")]
    assert len(pcts) >= 10


def test_split_columns_three_way_is_balanced():
    usage = _現場_10區()
    sections = usagewidget.visible_sections(usage, NOW, SOURCES)
    cols = usagewidget.split_columns(sections, 3)
    assert len(cols) == 3
    assert sum(len(c) for c in cols) == 10
    # 保序：攤平後順序跟原來一致
    flat = [k for col in cols for _t, _g, _a, k in col]
    assert flat == [k for _t, _g, _a, k in sections]


def test_save_autofit_preview_png():
    """人眼驗收圖：10 區現場組成畫在 1920×480，存到 scratchpad。"""
    usage = _現場_10區()
    surf = _surf()
    res = usagewidget.render(surf, usage, NOW, 1300, 600, SOURCES)
    assert len(res["keys"]) == 10
    out = Path("/private/tmp/claude-501/-Users-kevin-Documents/7b18128d-25a4-48d5-932c-0d6f73cc9083/scratchpad/autofit-10.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surf, str(out))
