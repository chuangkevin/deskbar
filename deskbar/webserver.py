"""Facade adapter for deskbar.webapi package.

Re-exports public factories create_app and start_web, as well as private constants
and helpers expected by existing code and tests for backwards compatibility.
"""

from deskbar.webapi.app import create_app, start_web
from deskbar.webapi.security import (
    _CSP,
    _UNSAFE_METHODS,
    _origin_host,
    _same_origin,
)
from deskbar.webapi.validation import (
    _PCT_FIELDS,
    _PREF_BOOL,
    _PREF_FLOAT,
    _PREF_INT,
    _PREF_STR,
    _RESETS_FIELDS,
    _TIME_RE,
    _USAGE_FETCHED_FIELDS,
    _USAGE_TZ,
    _parse_dt,
    _to_float,
    _valid_pct,
    _valid_resets_at,
)

__all__ = [
    "create_app",
    "start_web",
]
