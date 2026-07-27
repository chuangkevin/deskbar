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


def dev_window_to_logical(px: float, py: float, win_w: int, win_h: int,
                          dev_rotate: int, lw: int = 1920, lh: int = 480) -> tuple[int, int]:
    """Mac dev 視窗座標 → 邏輯座標。dev 外層旋轉的反解（與 App._flip 的
    rotate(logical, -dev_rotate) 嚴格互逆）：0=直接縮放、90=順時針、180=顛倒、270=逆時針。"""
    u = min(max(px, 0), max(1, win_w - 1)) / max(1, win_w - 1)
    v = min(max(py, 0), max(1, win_h - 1)) / max(1, win_h - 1)
    if dev_rotate == 0:
        x, y = u * (lw - 1), v * (lh - 1)
    elif dev_rotate == 90:
        x, y = v * (lw - 1), (1 - u) * (lh - 1)
    elif dev_rotate == 180:
        x, y = (1 - u) * (lw - 1), (1 - v) * (lh - 1)
    elif dev_rotate == 270:
        x, y = (1 - v) * (lw - 1), u * (lh - 1)
    else:
        raise ValueError(f"unsupported dev_rotate {dev_rotate}")
    return round(x), round(y)
