import threading
from flask import Flask

from deskbar.webapi.context import WebContext
from deskbar.webapi.routes import register_routes
from deskbar.webapi.security import register_security


def create_app(store, settings_provider=None, settings_lock=None, on_save=None,
               usage_state=None, notes_store=None, shot_bridge=None) -> Flask:
    """Factory creating and configuring the Flask application."""
    app = Flask("deskbar")
    context = WebContext(
        store=store,
        settings_provider=settings_provider,
        settings_lock=settings_lock,
        on_save=on_save,
        usage_state=usage_state,
        notes_store=notes_store,
        shot_bridge=shot_bridge,
    )
    register_security(app)
    register_routes(app, context)
    return app


def start_web(store, port: int = 8080, settings_provider=None, settings_lock=None,
              on_save=None, usage_state=None, notes_store=None,
              shot_bridge=None) -> None:
    """Starts the Flask web application thread."""
    app = create_app(store, settings_provider=settings_provider, settings_lock=settings_lock,
                      on_save=on_save, usage_state=usage_state, notes_store=notes_store,
                      shot_bridge=shot_bridge)
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True)
    t.start()
