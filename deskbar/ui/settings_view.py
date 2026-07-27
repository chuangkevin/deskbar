import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import qr
from deskbar.ui import theme

QR_X, QR_Y, QR_SIZE = 1500, 96, 200
# 帳號卡最多排到這裡就要停手，留位置給 QR code（QR 優先，帳號卡超出者不畫）。
ACCOUNTS_MAX_RIGHT = QR_X - 30


def _btn(surface, label, x, y, w, h, action, data, hits, size=24, fg=None):
    r = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surface, theme.C["card"], r, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=8)
    img = theme.font(size).render(label, True, fg or theme.C["text"])
    surface.blit(img, img.get_rect(center=r.center))
    hits.append(Hit(Rect(x, y, w, h), action, data))


def render(surface, snap, settings, confirm_remove) -> list[Hit]:
    hits: list[Hit] = []
    img = theme.font(32).render("帳號與日曆", True, theme.C["text"])
    surface.blit(img, (40, 24))
    _btn(surface, f"在場感應：{'開' if settings.presence_enabled else '關'}",
         220, 20, 260, 52, "toggle_presence", None, hits, size=22)
    _btn(surface, f"同步頻率：{settings.sync_interval_min} 分鐘", 1180, 20, 280, 52,
         "cycle_sync_interval", None, hits, size=22)
    _btn(surface, "旋轉螢幕", 1480, 20, 200, 52, "rotate", None, hits)
    _btn(surface, "完成", 1700, 20, 180, 52, "settings_done", None, hits)
    x = 40
    shown = 0
    for email, acc in settings.accounts.items():
        if x + 430 > ACCOUNTS_MAX_RIGHT:
            # QR code 優先：帳號卡排不下就不畫，不與 QR 重疊。
            break
        shown += 1
        main, dark = theme.account_color(acc.color)
        card = pygame.Rect(x, 96, 430, 330)
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
        pygame.draw.circle(surface, main, (x + 26, 126), 8)
        st = snap.statuses.get(email)
        name = email if len(email) <= 26 else email[:24] + "…"
        surface.blit(theme.font(22).render(name, True, theme.C["text"]), (x + 44, 112))
        if st is None:
            surface.blit(theme.font(20).render("（已離線）", True, theme.C["muted"]),
                         (x + 44, 140))
        elif not st.ok:
            surface.blit(theme.font(20).render(st.error or "同步異常", True,
                                               theme.C["warn"]), (x + 44, 140))
        _btn(surface, f"泳道：{acc.lane_label}", x + 16, 170, 200, 44,
             "cycle_label", email, hits, size=22)
        _btn(surface, "移除", x + 330, 170, 84, 52, "remove_account", email, hits,
             size=22, fg=theme.C["warn"])
        cy = 230
        row_h = 36
        max_rows = 5
        cal_items = list(acc.calendars.items())
        if len(cal_items) > max_rows:
            shown_items = cal_items[:max_rows - 1]
            remaining = len(cal_items) - len(shown_items)
        else:
            shown_items = cal_items
            remaining = 0
        for cal_id, enabled in shown_items:
            box = pygame.Rect(x + 16, cy, 24, 24)
            pygame.draw.rect(surface, theme.C["panel_line"], box, 0 if enabled else 1,
                             border_radius=4)
            if enabled:
                pygame.draw.rect(surface, main, box.inflate(-8, -8), border_radius=2)
            label = cal_id if len(cal_id) <= 24 else cal_id[:22] + "…"
            surface.blit(theme.font(20).render(label, True, theme.C["text2"]),
                         (x + 52, cy))
            hits.append(Hit(Rect(x + 16, cy - 6, 400, row_h), "toggle_cal", (email, cal_id)))
            cy += row_h
        if remaining > 0:
            surface.blit(theme.font(20).render(f"其餘 {remaining} 個用手機網頁管理", True,
                                               theme.C["muted"]), (x + 16, cy))
        x += 460
    if x == 40:
        surface.blit(theme.font(24).render("尚無帳號——在 Mac 執行 make add-account",
                                           True, theme.C["muted"]), (40, 200))
    hidden = len(settings.accounts) - shown
    if hidden > 0:
        surface.blit(theme.font(20).render(
            f"＋{hidden} 個帳號未顯示（可用手機網頁或 SSH 管理）", True, theme.C["muted"]),
            (40, 434))
    qr.draw_qr(surface, QR_X, QR_Y, QR_SIZE, qr.WEB_URL)
    surface.blit(theme.font(20).render("掃描設定鬧鐘", True, theme.C["text2"]),
                 (QR_X, QR_Y + QR_SIZE + 10))
    host = qr.WEB_URL.split("//")[-1].rstrip("/")
    surface.blit(theme.font(22).render(host, True, theme.C["muted"]),
                 (QR_X, QR_Y + QR_SIZE + 36))
    if confirm_remove:
        bar = pygame.Rect(0, 380, 1920, 100)
        pygame.draw.rect(surface, theme.C["danger_bg"], bar)
        surface.blit(theme.font(26).render(f"確定移除 {confirm_remove}？", True,
                                           theme.C["text"]), (60, 414))
        _btn(surface, "確定移除", 1420, 398, 220, 60, "confirm_remove",
             confirm_remove, hits, fg=theme.C["warn"])
        _btn(surface, "取消", 1660, 398, 180, 60, "remove_account", None, hits)
    return hits
