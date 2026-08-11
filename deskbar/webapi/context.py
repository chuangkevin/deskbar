import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class WebContext:
    """Immutable WebContext encapsulating web server dependencies."""
    store: Any
    settings_provider: Any = None
    settings_lock: Optional[threading.Lock] = None
    on_save: Optional[Callable[[Any], None]] = None
    usage_state: Any = None
    notes_store: Any = None
    shot_bridge: Any = None
    shot_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def calendars_available(self) -> bool:
        return (
            self.settings_provider is not None
            and self.settings_lock is not None
            and self.on_save is not None
        )
