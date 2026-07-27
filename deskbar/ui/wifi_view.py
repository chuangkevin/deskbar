"""Wi-Fi 設定頁（settings 進入）：網路清單＋觸控密碼鍵盤。

帶去公司/外地時面板本體必須能自己連新網路——沒有網路時，鬧鐘網頁那條
管理路徑根本打不開，所以這頁是「裝置自救」用的，全部操作只靠觸控。

狀態機（ui dict 由 app 持有，這裡只讀）：
- phase="list"：網路清單（2 欄×4 列，訊號排序、活動中優先），點開放/已存
  網路直接連；點加密且未存的網路 → phase="password"。
- phase="password"：全寬觸控鍵盤（QWERTY＋數字列＋符號切換＋shift），
  輸入完按「連線」。busy="connect" 期間鎖操作畫轉場提示。
- busy="scan"/"connect" 由 app 的背景執行緒設定/清除；本頁在主迴圈以低頻
  （5fps）重繪，busy 結束畫面自然跟上。

密碼欄預設遮罩（●），可切換明碼；ui["pw"] 只存在記憶體、連線成功或取消
即清空，永不落地。
"""
from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

_ROWS_LETTERS = ["1234567890", "qwertyuiop", "asdfghjkl"]
_ROW4_LETTERS = "zxcvbnm"
_ROWS_SYM = ["1234567890", "!@#$%^&*()", "-_=+[]{};:"]
_ROW4_SYM = "'\",.<>?/~`"
_KB_X0, _KB_W = 210, 1500
_KB_GAP = 8
_KEY_H = 66
_ROW_YS = (86, 160, 234, 308)
_BOTTOM_Y, _BOTTOM_H = 382, 72
PW_MAX = 63                     # WPA-PSK 上限


def new_state() -> dict:
    return {"phase": "list", "nets": [], "busy": None, "selected": "",
            "selected_secured": False, "pw": "", "shift": False, "sym": False,
            "show_pw": False, "msg": "", "active": None}


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _btn(surface, label, rect: "pygame.Rect", action, data, hits, size=24,
         fg=None, bg=None):
    pygame.draw.rect(surface, bg or theme.C["card"], rect, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], rect, 1, border_radius=8)
    img = theme.font(size).render(label, True, fg or theme.C["text"])
    surface.blit(img, img.get_rect(center=rect.center))
    hits.append(Hit(Rect(rect.x, rect.y, rect.w, rect.h), action, data))


def _signal_bars(surface, x, y, signal: int) -> None:
    for k, th in enumerate((15, 40, 65, 85)):
        h = 10 + k * 7
        color = theme.C["text2"] if signal >= th else theme.C["panel_line"]
        pygame.draw.rect(surface, color,
                         pygame.Rect(x + k * 13, y + 31 - h, 8, h), border_radius=2)


def _lock_glyph(surface, cx, cy, color) -> None:
    import math
    pygame.draw.rect(surface, color, pygame.Rect(cx - 8, cy - 1, 16, 13),
                     border_radius=2)
    pygame.draw.arc(surface, color, pygame.Rect(cx - 6, cy - 12, 12, 15),
                    0, math.pi, 2)


def render(surface, ui: dict, now) -> list:
    hits: list = []
    if ui["phase"] == "password":
        _render_password(surface, ui, hits, now)
    else:
        _render_list(surface, ui, hits)
    return hits


# ---------------------------------------------------------------- 清單

def _render_list(surface, ui: dict, hits: list) -> None:
    _text(surface, "Wi-Fi 設定", 32, theme.C["text"], 40, 24)
    active = ui.get("active")
    status = f"已連線：{active[0]}（{active[1] or '取得 IP 中'}）" if active else "未連線"
    _text(surface, status, 22, theme.C["ok"] if active else theme.C["muted"], 280, 34)
    _btn(surface, "重新掃描", pygame.Rect(1480, 20, 200, 52), "wifi_rescan", None, hits)
    _btn(surface, "返回", pygame.Rect(1700, 20, 180, 52), "wifi_back", None, hits)

    if ui["busy"] == "scan":
        _text(surface, "掃描中…", 28, theme.C["muted"], 960, 240, "center")
    elif not ui["nets"]:
        _text(surface, "找不到網路（無訊號，或此環境沒有 nmcli）", 24,
              theme.C["muted"], 960, 240, "center")
    else:
        for idx, net in enumerate(ui["nets"][:8]):
            col, row = idx % 2, idx // 2
            x, y = 40 + col * 940, 96 + row * 86
            r = pygame.Rect(x, y, 900, 76)
            pygame.draw.rect(surface, theme.C["card"], r, border_radius=10)
            pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=10)
            name = theme.truncate_to_width(net.ssid, theme.font(26), 480)
            _text(surface, name, 26, theme.C["text"], x + 24, y + 22)
            if net.active:
                _text(surface, "已連線", 20, theme.C["ok"], x + 560, y + 26)
            elif net.known:
                _text(surface, "已儲存", 20, theme.C["muted"], x + 560, y + 26)
            _signal_bars(surface, x + 700, y + 22, net.signal)
            if net.secured:
                _lock_glyph(surface, x + 810, y + 36, theme.C["muted"])
            hits.append(Hit(Rect(x, y, 900, 76), "wifi_pick", net))
    if ui["msg"]:
        color = theme.C["warn"] if "失敗" in ui["msg"] else theme.C["ok"]
        _text(surface, ui["msg"], 22, color, 40, 446)


# ---------------------------------------------------------------- 密碼鍵盤

def _kb_rows(ui: dict) -> list:
    rows = list(_ROWS_SYM if ui["sym"] else _ROWS_LETTERS)
    row4 = list(_ROW4_SYM if ui["sym"] else _ROW4_LETTERS)
    if ui["shift"] and not ui["sym"]:
        rows = [rows[0]] + [r.upper() for r in rows[1:]]
        row4 = [c.upper() for c in row4]
    return rows, row4


def _key_rects(n: int) -> list:
    w = (_KB_W - (n - 1) * _KB_GAP) / n
    return [(_KB_X0 + i * (w + _KB_GAP), w) for i in range(n)]


def _render_password(surface, ui: dict, hits: list, now) -> None:
    _text(surface, f"連線到 {theme.truncate_to_width(ui['selected'], theme.font(26), 420)}",
          26, theme.C["text"], 40, 28)
    field = pygame.Rect(560, 14, 900, 56)
    pygame.draw.rect(surface, theme.C["card"], field, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], field, 1, border_radius=8)
    shown = ui["pw"] if ui["show_pw"] else "●" * len(ui["pw"])
    disp = theme.truncate_to_width(shown + "▏", theme.font(28), field.w - 32)
    _text(surface, disp, 28, theme.C["text"], field.x + 16, field.y + 12)
    _btn(surface, "隱藏" if ui["show_pw"] else "顯示",
         pygame.Rect(1480, 14, 180, 56), "wifi_show", None, hits, size=22)

    rows, row4 = _kb_rows(ui)
    for ri, row in enumerate(rows):
        y = _ROW_YS[ri]
        for (x, w), ch in zip(_key_rects(len(row)), row):
            _btn(surface, ch, pygame.Rect(round(x), y, round(w), _KEY_H),
                 "wifi_key", ch, hits, size=28)
    # 第四列：大寫 + 字母/符號 + 刪除。控制鍵一律用文字標籤——比照
    # deskbar.ui.icons 的教訓（⇧/⌫ 這類字符字型檔不一定有，會畫成豆腐方塊）。
    keys4 = (["大寫"] if not ui["sym"] else [""]) + list(row4) + ["刪除"]
    y = _ROW_YS[3]
    for (x, w), ch in zip(_key_rects(len(keys4)), keys4):
        r = pygame.Rect(round(x), y, round(w), _KEY_H)
        if ch == "大寫":
            _btn(surface, "大寫", r, "wifi_shift", None, hits, size=22,
                 bg=theme.C["panel_line"] if ui["shift"] else None)
        elif ch == "刪除":
            _btn(surface, "刪除", r, "wifi_backspace", None, hits, size=22)
        elif ch:
            _btn(surface, ch, r, "wifi_key", ch, hits, size=28)
    # 底列：符號切換／空白鍵／取消／連線
    y = _BOTTOM_Y
    _btn(surface, "ABC" if ui["sym"] else "#+=",
         pygame.Rect(210, y, 220, _BOTTOM_H), "wifi_sym", None, hits, size=24)
    _btn(surface, "空格", pygame.Rect(446, y, 620, _BOTTOM_H), "wifi_key", " ",
         hits, size=24)
    _btn(surface, "取消", pygame.Rect(1082, y, 260, _BOTTOM_H), "wifi_cancel",
         None, hits, size=24)
    can_go = len(ui["pw"]) > 0 and ui["busy"] is None
    _btn(surface, "連線", pygame.Rect(1358, y, 352, _BOTTOM_H), "wifi_connect",
         None, hits, size=26,
         fg=theme.C["text"] if can_go else theme.C["muted"],
         bg=theme.C["usage_bar"] if can_go else None)

    if ui["msg"]:
        _text(surface, ui["msg"], 22, theme.C["warn"], 40, 446)
    if ui["busy"] == "connect":
        veil = pygame.Surface((1920, 480), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surface.blit(veil, (0, 0))
        dots = "…" [: 1] * (1 + now.second % 3)
        _text(surface, f"連線中{dots}", 34, theme.C["text"], 960, 240, "center")
        hits.clear()               # 連線期間鎖操作，避免連點/重入
