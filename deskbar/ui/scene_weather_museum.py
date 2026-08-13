"""Low-saturation museum-grade ambient weather scene renderers.

Includes:
- GlassRainRenderer: Dark green-black glass refraction rain streaks & condensation.
- MagneticFogRenderer: Cyan-green soft fog clusters & magnetic field force filaments.
- ReverseLightningRenderer: Low frequency smooth upward lightning with root glow.
- TidalAuroraRenderer: Cyan-violet tidal aurora ribbons, flowing halo & curtains.
"""

from __future__ import annotations

import math
import pygame

from deskbar.ui.scene_common import hash_unit
from deskbar.ui.scene_runtime import SceneFrame


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
    """Cyan-violet tidal aurora ribbons, flowing halo, and smooth curtains renderer."""

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

        # Base background (deep violet cyan space)
        panel.fill((10, 18, 36))
        self._overlay.fill((0, 0, 0, 0))

        seed = frame.day_seed
        t = frame.t

        # 1. Twinkling background stars (30 stars)
        for s in range(30):
            sx = int(hash_unit(s, seed, 91) * w)
            sy = int(hash_unit(s, seed, 93) * (h * 0.7))
            twinkle = 0.5 + 0.5 * math.sin(t * 1.5 + s * 1.3)
            star_alpha = int(50 + twinkle * 150)
            pygame.draw.circle(panel, (190, 220, 210, star_alpha), (sx, sy), 1)

        # 2. Ambient flowing aurora halo in upper sky (流動 halo)
        for halo_idx in range(3):
            halo_y = h * (0.18 + halo_idx * 0.12) + math.sin(t * 0.2 + halo_idx) * 15.0
            halo_rx = int(w * 0.45)
            halo_ry = int(h * 0.18)
            halo_cx = w * 0.5 + math.sin(t * 0.15 + halo_idx * 2.0) * (w * 0.2)
            rect = pygame.Rect(round(halo_cx - halo_rx), round(halo_y - halo_ry), halo_rx * 2, halo_ry * 2)
            color = (140, 70, 210, 24) if halo_idx % 2 == 0 else (40, 190, 160, 28)
            pygame.draw.ellipse(self._overlay, color, rect)

        # 3. Multi-layered cyan-green & purple aurora curtains (青綠/紫色簾幕)
        curtain_configs = [
            (0.20, (40, 220, 170, 35), (140, 80, 230, 28), 22.0, 65),
            (0.28, (60, 240, 190, 40), (160, 90, 245, 32), 26.0, 75),
            (0.36, (50, 190, 220, 32), (120, 70, 200, 25), 18.0, 55),
        ]

        for base_ratio, c_mint, c_purple, wave_amp, curtain_h in curtain_configs:
            base_y = h * base_ratio
            t_wave = t * 0.16

            # Build smooth upper and lower polygon boundary points across screen width
            top_pts = []
            bot_pts = []
            for x in range(-10, w + 14, 8):
                edge_fade = math.sin(max(0.0, min(1.0, (x + 10) / (w + 20))) * math.pi)
                y_t = base_y + math.sin(x * 0.005 + t_wave) * wave_amp
                y_t += math.cos(x * 0.012 - t_wave * 0.7) * (wave_amp * 0.4)

                y_b = y_t + curtain_h * (0.6 + 0.4 * edge_fade)
                top_pts.append((x, round(y_t)))
                bot_pts.append((x, round(y_b)))

            poly_pts = top_pts + list(reversed(bot_pts))

            # Draw mint cyan curtain body polygon
            if len(poly_pts) > 3:
                pygame.draw.polygon(self._overlay, c_mint, poly_pts)

            # Draw overlapping violet secondary curtain polygon slightly offset
            v_poly = [(px, py + 12) for px, py in top_pts] + [(px, py + 12) for px, py in reversed(bot_pts)]
            if len(v_poly) > 3:
                pygame.draw.polygon(self._overlay, c_purple, v_poly)

            # Overlay fine vertical aurora rays (柔和細絲簾幕 rays)
            for x in range(0, w, 6):
                edge_fade = math.sin((x / w) * math.pi)
                alpha_ray = int((25 + math.sin(t * 0.6 + x * 0.01) * 10) * edge_fade)
                if alpha_ray > 2:
                    y_t = base_y + math.sin(x * 0.005 + t_wave) * wave_amp + math.cos(x * 0.012 - t_wave * 0.7) * (wave_amp * 0.4)
                    pygame.draw.line(self._overlay, (180, 255, 235, alpha_ray), (x, round(y_t)), (x, round(y_t + curtain_h)), 1)

        panel.blit(self._overlay, (0, 0))

    def close(self) -> None:
        self._closed = True
        self._overlay = None
