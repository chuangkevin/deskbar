NATIVE_W, NATIVE_H = 480, 1920


def pygame_rotation_angle(rotation: int) -> int:
    return {90: -90, 270: 90}[rotation]


def touch_to_logical(nx: float, ny: float, rotation: int,
                     lw: int = 1920, lh: int = 480) -> tuple[int, int]:
    u = min(max(nx, 0.0), 1.0) * (NATIVE_W - 1)
    v = min(max(ny, 0.0), 1.0) * (NATIVE_H - 1)
    if rotation == 90:      # 邏輯順時針 90 → 反解
        x = v * (lw - 1) / (NATIVE_H - 1)
        y = (NATIVE_W - 1 - u) * (lh - 1) / (NATIVE_W - 1)
    elif rotation == 270:
        x = (NATIVE_H - 1 - v) * (lw - 1) / (NATIVE_H - 1)
        y = u * (lh - 1) / (NATIVE_W - 1)
    else:
        raise ValueError(f"unsupported rotation {rotation}")
    return round(x), round(y)
