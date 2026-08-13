"""Low-saturation museum-grade ambient weather scene renderers.

Includes:
- GlassRainRenderer: Dark green-black glass refraction rain streaks & condensation.
- MagneticFogRenderer: Cyan-green soft fog clusters & magnetic field force filaments.
- ReverseLightningRenderer: Low frequency smooth upward lightning with root glow.
- TidalAuroraRenderer: Cyan-violet tidal aurora ribbons, flowing halo & curtains.
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame

from deskbar.ui.scene_common import hash_unit
from deskbar.ui.scene_assets import SceneAssets, TintRequest
from deskbar.ui.scene_runtime import SceneFrame


SCENE_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "scenes"


class GlassRainRenderer:
    """Dark green-black glass refraction rain streaks & condensation renderer."""

    __slots__ = ("_closed", "_overlay")

    def __init__(self) -> None:
        self._closed = False
        self._overlay: pygame.Surface | None = None

    @property
    def decoded_bytes(self) -> int:
        if self._closed or self._overlay is None:
            return 0
        return self._overlay.get_width() * self._overlay.get_height() * 4

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        if self._closed:
            return
        w, h = panel.get_size()
        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)

        # Base background (dark ink teal-green gradient)
        panel.fill((10, 26, 32))
        self._overlay.fill((0, 0, 0, 0))

        seed = frame.day_seed
        t = frame.t

        # Soft background subtle gradient band
        for y_step in range(0, h, 8):
            grad_val = int(10 + 10 * (y_step / max(1, h)))
            panel.fill((grad_val, grad_val + 16, grad_val + 22), pygame.Rect(0, y_step, w, 8))

        # 1. Local fog glow & condensation patches on the glass (局部霧光)
        for c in range(6):
            cx = (hash_unit(c, seed, 41) * w + math.sin(t * 0.3 + c) * 30.0) % w
            cy = hash_unit(c, seed, 43) * h
            rx = 60 + int(hash_unit(c, seed, 47) * 80)
            ry = 30 + int(hash_unit(c, seed, 49) * 40)
            rect = pygame.Rect(round(cx - rx), round(cy - ry), rx * 2, ry * 2)
            pygame.draw.ellipse(self._overlay, (35, 95, 90, 22), rect)

        # 2. Refraction water marks & static glass droplets (折射水痕與靜態水滴高光)
        for d in range(18):
            dx = hash_unit(d, seed, 113) * w
            dy = (hash_unit(d, seed, 117) * h + math.sin(t * 0.2 + d) * 3.0) % h
            dr = 2.5 + hash_unit(d, seed, 121) * 4.0
            drect = pygame.Rect(round(dx - dr), round(dy - dr), round(dr * 2), round(dr * 2))
            pygame.draw.ellipse(self._overlay, (6, 18, 20, 130), drect.move(1, 1), 1)
            pygame.draw.ellipse(self._overlay, (80, 160, 145, 60), drect)
            pygame.draw.ellipse(
                self._overlay,
                (220, 250, 240, 180),
                pygame.Rect(round(dx - dr * 0.4), round(dy - dr * 0.4), max(2, round(dr * 0.6)), max(2, round(dr * 0.6))),
            )

        # 3. Render 28 smooth refraction rain streaks
        num_streaks = 28
        for i in range(num_streaks):
            x_base = hash_unit(i, seed, 11) * w
            speed = 35.0 + hash_unit(i, seed, 17) * 45.0
            streak_len = 50.0 + hash_unit(i, seed, 23) * 75.0
            y_pos = (hash_unit(i, seed, 29) * h + t * speed) % (h + streak_len + 40) - streak_len

            dx = streak_len * 0.18
            x1 = x_base + (y_pos / h) * 30.0
            y1 = y_pos
            x2 = x1 + dx
            y2 = y1 + streak_len

            alpha = int(70 + hash_unit(i, seed, 31) * 90)
            # Dark refraction shadow edge
            pygame.draw.aaline(self._overlay, (4, 18, 20, alpha), (x1 - 1, y1), (x2 - 1, y2))
            # Glass refraction highlight line
            pygame.draw.aaline(self._overlay, (70, 185, 165, alpha + 20), (x1, y1), (x2, y2))
            # Specular tip dot
            pygame.draw.circle(self._overlay, (210, 250, 245, min(255, alpha + 80)), (round(x2), round(y2)), 1)

        panel.blit(self._overlay, (0, 0))

    def close(self) -> None:
        self._closed = True
        self._overlay = None


class MagneticFogRenderer:
    """Cyan-green soft fog clusters and magnetic field force filaments renderer."""

    __slots__ = ("_closed", "_overlay")

    def __init__(self) -> None:
        self._closed = False
        self._overlay: pygame.Surface | None = None

    @property
    def decoded_bytes(self) -> int:
        if self._closed or self._overlay is None:
            return 0
        return self._overlay.get_width() * self._overlay.get_height() * 4

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        if self._closed:
            return
        w, h = panel.get_size()
        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)

        # Base background (deep cyan space)
        panel.fill((8, 24, 32))
        self._overlay.fill((0, 0, 0, 0))

        seed = frame.day_seed
        t = frame.t

        # 1. Multi-layered soft fog clusters (柔和霧團, no flat ends/butt caps)
        for f in range(6):
            y_base = h * (0.15 + f * 0.15)
            amplitude = 22.0 + hash_unit(f, seed, 53) * 25.0
            freq = 0.004 + hash_unit(f, seed, 59) * 0.003
            speed = (0.10 + f * 0.03) * (1 if f % 2 == 0 else -1)
            phase = hash_unit(f, seed, 61) * math.tau

            # Sample soft overlapping fog blobs along wave path
            for x in range(-20, w + 20, 14):
                y = y_base + math.sin(x * freq + t * speed + phase) * amplitude
                y += math.cos(x * freq * 1.8 - t * 0.08) * (amplitude * 0.4)

                # Fade smoothly near left/right screen edges
                edge_fade = math.sin(max(0.0, min(1.0, (x + 20) / (w + 40))) * math.pi)
                alpha = int((20 + math.sin(t * 0.3 + f + x * 0.01) * 8) * edge_fade)

                if alpha > 1:
                    blob_r = int(30 + hash_unit(f, seed, x) * 20)
                    rect = pygame.Rect(round(x - blob_r), round(y - blob_r * 0.6), blob_r * 2, int(blob_r * 1.2))
                    pygame.draw.ellipse(self._overlay, (25, 110, 95, alpha), rect)

        # 2. Translucent magnetic field force filaments (半透明細絲)
        for fil in range(12):
            y_start = h * (0.1 + fil * 0.07)
            pts = []
            speed = 0.08 + hash_unit(fil, seed, 131) * 0.06
            phase = hash_unit(fil, seed, 137) * math.tau

            for x in range(0, w + 8, 8):
                y = y_start + math.sin(x * 0.006 + t * speed + phase) * 28.0
                y += math.cos(x * 0.012 - t * 0.05) * 12.0
                pts.append((x, round(y)))

            alpha = int(35 + math.sin(t * 0.4 + fil) * 15)
            color = (70, 200, 175, alpha) if fil % 2 == 0 else (45, 150, 140, alpha)
            if len(pts) > 1:
                pygame.draw.lines(self._overlay, color, False, pts, 2)

        # 3. Magnetic field pole concentric rings
        pole_x = w * 0.35 + math.sin(t * 0.08) * (w * 0.1)
        pole_y = h * 0.5 + math.cos(t * 0.06) * (h * 0.1)

        for ring in range(8):
            r_x = 70 + ring * 60 + int(math.sin(t * 0.15 + ring) * 15)
            r_y = int(r_x * 0.55)
            rect = pygame.Rect(round(pole_x - r_x), round(pole_y - r_y), r_x * 2, r_y * 2)
            alpha = int(22 + math.sin(t * 0.4 + ring * 0.8) * 10)
            pygame.draw.ellipse(self._overlay, (55, 160, 140, alpha), rect, 1)

        panel.blit(self._overlay, (0, 0))

    def close(self) -> None:
        self._closed = True
        self._overlay = None


class ReverseLightningRenderer:
    """Low frequency smooth upward lightning renderer (10s cycle, smooth sin envelope, root glow)."""

    __slots__ = ("_closed", "_overlay")

    def __init__(self) -> None:
        self._closed = False
        self._overlay: pygame.Surface | None = None

    @property
    def decoded_bytes(self) -> int:
        if self._closed or self._overlay is None:
            return 0
        return self._overlay.get_width() * self._overlay.get_height() * 4

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        if self._closed:
            return
        w, h = panel.get_size()
        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)

        # Base background (dark blue storm night)
        panel.fill((12, 18, 30))
        self._overlay.fill((0, 0, 0, 0))

        seed = frame.day_seed
        t = frame.t

        # Lightning cycle: Period 10 seconds (>= 8s requirement)
        period = 10.0
        cycle_t = t % period
        burst_start = 4.5
        burst_duration = 2.8

        # Smooth envelope (sin curve, no whole-screen white flash)
        if burst_start <= cycle_t < (burst_start + burst_duration):
            progress = (cycle_t - burst_start) / burst_duration
            envelope = math.sin(progress * math.pi)
            jitter = 0.85 + 0.15 * math.sin(t * 18.0) + 0.1 * math.cos(t * 31.0)
            pulse = max(0.0, min(1.0, envelope * jitter))
        else:
            pulse = 0.0

        # Upper cloud canopy with soft cloud-base reflection (雲底反光)
        cloud_h = int(h * 0.45)
        for y_step in range(0, cloud_h, 6):
            c_fade = 1.0 - y_step / float(cloud_h)
            base_val = int(14 + c_fade * 16)
            # Cloud reflection intensity during lightning pulse (limited to cloud canopy!)
            r_refl = int(base_val + pulse * 50 * c_fade)
            g_refl = int(base_val + 4 + pulse * 90 * c_fade)
            b_refl = int(base_val + 14 + pulse * 140 * c_fade)
            panel.fill((min(255, r_refl), min(255, g_refl), min(255, b_refl)), pygame.Rect(0, y_step, w, 6))

        # Even between bolts the cloud shelf drifts.  This gives the storm a
        # living, slow-moving baseline instead of a static black screen while
        # keeping the actual discharge rare and calm.
        for band in range(4):
            points = []
            y_base = h * (0.12 + band * 0.075)
            phase = hash_unit(seed, band, 307) * math.tau
            for x in range(-8, w + 9, 8):
                y = y_base + math.sin(x * 0.007 + t * 0.52 + phase) * 9.0
                y += math.cos(x * 0.014 - t * 0.22 + phase) * 4.0
                points.append((x, round(y)))
            pygame.draw.lines(self._overlay, (46, 88, 126, 22), False, points, 2)

        if pulse > 0.01:
            # Deterministic upward lightning path
            cycle_idx = int(t // period)
            x_root = w * 0.45 + hash_unit(cycle_idx, seed, 71) * (w * 0.2)
            y_root = float(h - 8)
            y_target = h * 0.10

            num_segments = 18
            dy = (y_root - y_target) / num_segments
            nodes = [(x_root, y_root)]

            curr_x = x_root
            curr_y = y_root
            for seg in range(1, num_segments + 1):
                curr_y -= dy
                offset = (hash_unit(seg, seed, cycle_idx * 17) - 0.5) * 32.0
                curr_x += offset + (hash_unit(seg, seed, 83) - 0.5) * 12.0
                nodes.append((curr_x, curr_y))

            # Main upward bolt (clear blue-white pathway with multi-tier glow)
            for i in range(len(nodes) - 1):
                p1 = (round(nodes[i][0]), round(nodes[i][1]))
                p2 = (round(nodes[i + 1][0]), round(nodes[i + 1][1]))

                # Outer blue glow aura
                pygame.draw.line(self._overlay, (30, 100, 210, int(85 * pulse)), p1, p2, 14)
                # Mid cyan-white glow
                pygame.draw.line(self._overlay, (80, 170, 255, int(160 * pulse)), p1, p2, 7)
                # Inner white core
                pygame.draw.line(self._overlay, (220, 240, 255, int(240 * pulse)), p1, p2, 3)
                pygame.draw.line(self._overlay, (255, 255, 255, int(255 * pulse)), p1, p2, 1)

            # Upward sub-branches splitting off into upper sky
            branch_indices = [4, 8, 12, 15]
            for b_idx in branch_indices:
                if b_idx < len(nodes) - 2:
                    b_x, b_y = nodes[b_idx]
                    b_dir = -1.0 if b_idx % 2 == 0 else 1.0
                    b_nodes = [(b_x, b_y)]
                    for b_step in range(4):
                        b_y -= 14.0
                        b_x += b_dir * (10.0 + hash_unit(b_step, seed, b_idx) * 10.0)
                        b_nodes.append((b_x, b_y))

                    for i in range(len(b_nodes) - 1):
                        bp1 = (round(b_nodes[i][0]), round(b_nodes[i][1]))
                        bp2 = (round(b_nodes[i + 1][0]), round(b_nodes[i + 1][1]))
                        pygame.draw.line(self._overlay, (30, 100, 210, int(60 * pulse)), bp1, bp2, 6)
                        pygame.draw.line(self._overlay, (180, 225, 255, int(200 * pulse)), bp1, bp2, 2)

            # Ground root electrical discharge glow (根部 glow)
            for r_halo, alpha_mult in ((50, 0.4), (28, 0.7), (12, 1.0)):
                alpha_halo = int(140 * pulse * alpha_mult)
                pygame.draw.circle(self._overlay, (60, 160, 255, alpha_halo), (round(x_root), round(y_root)), r_halo)
                pygame.draw.circle(
                    self._overlay,
                    (220, 245, 255, int(200 * pulse * alpha_mult)),
                    (round(x_root), round(y_root)),
                    max(2, r_halo // 3),
                )

        panel.blit(self._overlay, (0, 0))

    def close(self) -> None:
        self._closed = True
        self._overlay = None


class TidalAuroraRenderer:
    """Blue-violet variant of the baked, non-uniform aurora curtains.

    The original implementation tried to approximate volumetric light with
    runtime polygons.  Pygame's hard alpha edges made those polygons read as
    coloured ribbons.  The approved Aurora scene already owns a purpose-baked
    soft light field, so this variant reuses that texture and changes its
    colour, timing and layering into a slower tidal current.
    """

    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(SCENE_ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        panel.blit(self._assets.load("aurora_base_night"), (-(1240 - 1118) // 2, 0))
        tile_area = pygame.Rect((1240 - 1118) // 2, 0, 1118, 472)
        layers = (
            ("aurora_curtain_2", (205, 82, 255), 136, 4.6, 0.13, 21.0, 0.0),
            ("aurora_curtain_1", (92, 238, 255), 154, 6.8, 0.46, 18.0, 1.7),
            ("aurora_curtain_0", (145, 170, 255), 124, 3.5, 0.76, 24.0, 3.4),
        )
        width = panel.get_width()
        for name, tint, base_alpha, speed, start, breathe_period, phase in layers:
            curtain = self._assets.tinted(TintRequest(name, tint, None))
            breathe = math.sin(frame.t * math.tau / breathe_period + phase)
            curtain.set_alpha(round(base_alpha + breathe * 10.0))
            vertical = round(math.sin(frame.t * math.tau / (28.0 + speed) + phase) * 3.0)
            left = -round((frame.t * speed + start * 1118) % 1118)
            while left < width:
                panel.blit(curtain, (left, vertical), tile_area)
                left += 1118

    def close(self) -> None:
        self._assets.close()
