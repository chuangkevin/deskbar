"""切換過場動畫／開機 splash／迫近脈動：純視覺效果的獨立模組。

刻意不依賴 app.py／dashboard.py 的任何內部狀態——三組工具各自純函數／小型狀態機，
呼叫端（App 主迴圈、dashboard.render）自行決定何時 start／frame／套用顏色，
方便在不改動既有渲染路徑的情況下先行開發與測試（見任務報告「整合說明」）。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pygame

from deskbar.ui import theme


class SlideTransition:
    """視圖切換過場：200ms 內把「舊畫面」依方向水平滑出、「新畫面」從對側滑入，
    兩者在同一張畫布上合成；超過 DURATION 秒後直接視為結束，frame() 回傳 new_surface
    原樣（不再合成，省得每格白做一次 blit）。

    用法（呼叫端自行計時，這支不內建時鐘，方便測試也方便跟既有 time.monotonic()
    節奏對齊）：
        t = SlideTransition()
        t.start(old_surface, direction=1)
        ...
        while t.active():
            frame = t.frame(new_surface, time.monotonic() - t0)
    """

    DURATION = 0.2

    def __init__(self):
        self._old = None
        self._direction = 1
        self._active = False

    def start(self, old_surface, direction: int) -> None:
        """記錄過場起點。direction>=0：舊畫面往左滑出、新畫面從右側滑入（例如
        cycle_span／goto_day 等「前進」動作）；direction<0：方向相反（「後退」）。
        old_surface 當下就地複製一份快照，之後呼叫端繼續改動原本的 surface
        （例如每格重繪 self.logical）不會影響這裡存的過場素材。"""
        self._old = old_surface.copy()
        self._direction = 1 if direction >= 0 else -1
        self._active = True

    def active(self) -> bool:
        return self._active

    def frame(self, new_surface, elapsed_s: float):
        """回傳這一幀該畫的合成結果。elapsed_s 是距離 start() 呼叫的秒數，由呼叫端
        自行量測傳入。超過 DURATION 即結束（active() 之後回 False），並直接回傳
        new_surface 本身（不複製、不合成）。"""
        if not self._active or self._old is None:
            return new_surface
        progress = elapsed_s / self.DURATION
        if progress >= 1.0:
            self._active = False
            self._old = None
            return new_surface
        w, h = new_surface.get_size()
        offset = round(w * progress)
        if self._direction > 0:
            old_x = -offset
            new_x = w - offset
        else:
            old_x = offset
            new_x = offset - w
        canvas = pygame.Surface((w, h))
        canvas.blit(self._old, (old_x, 0))
        canvas.blit(new_surface, (new_x, 0))
        return canvas


def splash_frames(w: int, h: int, text: str = "deskbar") -> list:
    """開機畫面的逐格畫面清單，共 13 張，黑底、文字置中、字級 72：

    - 前 10 張是「掃光顯現」：第 i 張（i=1..10）露出文字左起 i*10% 寬度，
      模擬由左至右掃出來的效果，第 10 張即完整文字。
    - 後 3 張是文字整體 alpha 淡出（100%→約 67%→約 33%→0% 的其中 3 個中段/末段
      取樣點），供開機動畫收尾轉場用。

    純畫面產生函數，不含計時——播放節奏（多久換一張）由呼叫端決定（見任務報告
    「整合說明」：App.run 開機時序建議）。
    """
    f = theme.font(72)
    text_img = f.render(text, True, theme.C["text"])
    tw, th = text_img.get_size()
    tx, ty = (w - tw) // 2, (h - th) // 2

    frames = []
    for i in range(1, 11):
        frame = pygame.Surface((w, h))
        frame.fill((0, 0, 0))
        reveal_w = min(tw, round(tw * i / 10))
        if reveal_w > 0:
            clip = text_img.subsurface(pygame.Rect(0, 0, reveal_w, th))
            frame.blit(clip, (tx, ty))
        frames.append(frame)

    for i in range(1, 4):
        frame = pygame.Surface((w, h))
        frame.fill((0, 0, 0))
        alpha = max(0, round(255 * (1 - i / 3)))
        faded = text_img.copy()
        faded.set_alpha(alpha)
        frame.blit(faded, (tx, ty))
        frames.append(frame)
    return frames


def pulse_border_color(main_rgb, now: datetime, period_s: float = 2.0) -> tuple:
    """迫近行程外框呼吸色：sin 波把 main_rgb 與白色 (255,255,255) 之間插值。

    t=0（插值係數 0）＝原色，t=1＝全白，中間依 sin(now.timestamp() 的相位)
    連續變化，形成呼吸效果。period_s 是完整呼吸週期（秒）。"""
    phase = math.sin(now.timestamp() * (2 * math.pi / period_s))
    t = (phase + 1) / 2
    return tuple(round(c + (255 - c) * t) for c in main_rgb)


def imminent_ids(events, now: datetime, window_min: int = 5) -> set:
    """回傳「迫近中」事件的 id 集合：尚未開始（start > now）、且開始時間落在
    now 起 window_min 分鐘內（含端點）。整日事件（all_day=True）一律不算——
    整日事件的 start 是當天 00:00，用同一套時間窗判斷沒有意義。"""
    window = timedelta(minutes=window_min)
    return {e.id for e in events if not e.all_day and now < e.start <= now + window}
