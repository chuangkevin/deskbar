from __future__ import annotations

from dataclasses import dataclass
from deskbar.layout import Rect


@dataclass(frozen=True)
class Hit:
    rect: Rect
    action: str
    data: object | None = None
