from urllib.parse import urlparse

from flask import Flask, jsonify, request

_UNSAFE_METHODS = {"POST", "PATCH", "DELETE", "PUT"}
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https://geocoding-api.open-meteo.com; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def _origin_host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    return parsed.netloc.lower()


def _same_origin(value: str | None, host: str) -> bool:
    origin_host = _origin_host(value)
    if origin_host is None:
        return True
    return origin_host == host.lower()


def register_security(app: Flask) -> None:
    """Registers same-origin CSRF guards and security headers on the Flask app."""

    @app.before_request
    def _reject_cross_site_unsafe_requests():
        """Keep the no-login tailnet workflow, but block browser CSRF.

        Same-origin mobile settings requests pass. Script/Shortcut/curl pushes
        usually have no Origin/Referer and continue to work. A random external
        web page loaded in the user's browser cannot POST/PATCH/DELETE deskbar
        state through the browser anymore.
        """
        if request.method not in _UNSAFE_METHODS:
            return None
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        host = request.host
        if not _same_origin(origin, host):
            return jsonify({"error": "cross-site request blocked"}), 403
        if origin is None and not _same_origin(referer, host):
            return jsonify({"error": "cross-site request blocked"}), 403
        return None

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        return resp
