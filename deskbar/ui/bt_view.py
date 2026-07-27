"""「藍牙配對」設定頁：掃描附近裝置→點擊配對→自動設為在場感應目標。

在場感應為什麼要配對：未配對的手機常不回 l2ping 的 L2CAP echo（隨機位址
＋權限策略），「開了藍牙也沒反應」多半是這個；配對＋信任後探測穩定，
而且使用者在螢幕上點裝置就好、不必手抄 MAC。

已配對裝置顯示「解除配對」鈕；感應目標顯示「感應中」標籤，點其他已配對
裝置可直接切換目標。配對進行中鎖操作並提示到手機上按確認。
"""
from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme


def new_state() -> dict:
    return {"devices": [], "busy": None, "msg": ""}


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _btn(surface, label, rect, action, data, hits, size=22, fg=None):
    pygame.draw.rect(surface, theme.C["card"], rect, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], rect, 1, border_radius=8)
    img = theme.font(size).render(label, True, fg or theme.C["text"])
    surface.blit(img, img.get_rect(center=rect.center))
    hits.append(Hit(Rect(rect.x, rect.y, rect.w, rect.h), action, data))


def render(surface, ui: dict, settings, now) -> list:
    hits: list = []
    _text(surface, "藍牙配對", 32, theme.C["text"], 40, 24)
    target = settings.presence_mac
    if target:
        _text(surface, f"在場感應目標：{target}", 22, theme.C["ok"], 280, 34)
    else:
        _text(surface, "尚未設定感應目標——點下方裝置配對", 22, theme.C["muted"],
              280, 34)
    _btn(surface, "重新掃描", pygame.Rect(1480, 20, 200, 52), "bt_rescan", None,
         hits, size=24)
    _btn(surface, "返回", pygame.Rect(1700, 20, 180, 52), "open_settings", None,
         hits, size=24)

    if ui["busy"] == "scan":
        _text(surface, "掃描中…（手機藍牙設定頁保持開啟較易被發現）", 26,
              theme.C["muted"], 960, 240, "center")
    elif not ui["devices"]:
        _text(surface, "沒掃到裝置——手機停留在藍牙設定頁再掃一次", 24,
              theme.C["muted"], 960, 240, "center")
    else:
        for idx, dev in enumerate(ui["devices"][:8]):
            col, row = idx % 2, idx // 2
            x, y = 40 + col * 940, 96 + row * 86
            r = pygame.Rect(x, y, 900, 76)
            pygame.draw.rect(surface, theme.C["card"], r, border_radius=10)
            pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=10)
            name = theme.truncate_to_width(dev.name or "（未知名稱）",
                                           theme.font(26), 430)
            _text(surface, name, 26, theme.C["text"], x + 24, y + 12)
            _text(surface, dev.mac, 18, theme.C["muted"], x + 24, y + 46)
            if dev.mac == target:
                _text(surface, "感應中", 20, theme.C["ok"], x + 520, y + 26)
            elif dev.paired:
                _text(surface, "已配對", 20, theme.C["muted"], x + 520, y + 26)
            hits.append(Hit(Rect(x, y, 640, 76), "bt_pick", dev))
            if dev.paired:
                _btn(surface, "解除配對", pygame.Rect(x + 700, y + 12, 180, 52),
                     "bt_unpair", dev.mac, hits, fg=theme.C["warn"])
    if ui["msg"]:
        color = theme.C["warn"] if "失敗" in ui["msg"] else theme.C["ok"]
        _text(surface, ui["msg"], 22, color, 40, 446)

    if ui["busy"] in ("pair", "unpair"):
        veil = pygame.Surface((1920, 480), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surface.blit(veil, (0, 0))
        if ui["busy"] == "pair":
            _text(surface, "配對中…請在手機跳出的視窗按「配對」", 32,
                  theme.C["text"], 960, 226, "center")
        else:
            _text(surface, "解除配對中…", 32, theme.C["text"], 960, 226, "center")
        hits.clear()
    return hits
