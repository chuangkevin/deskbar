from __future__ import annotations

import os

from flask import Flask, jsonify, request

from deskbar.webapi.context import WebContext


def register_usage_source_routes(app: Flask, context: WebContext) -> None:
    @app.get("/api/usage-sources")
    def list_usage_sources():
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        include_archived = request.args.get("include_archived") == "1"
        try:
            sources = state.list_usage_sources(include_archived=include_archived)
        except ValueError:
            return jsonify({"error": "usage sources unavailable"}), 503
        return jsonify({"sources": sources})

    @app.post("/api/usage-sources")
    def create_usage_source():
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        auth_error = _require_management_auth()
        if auth_error is not None:
            return auth_error
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            source = state.create_usage_source(data)
        except OSError:
            return jsonify({"error": "usage sources update failed"}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"source": source}), 201

    @app.post("/api/usage-sources/order")
    def reorder_usage_sources():
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        auth_error = _require_management_auth()
        if auth_error is not None:
            return auth_error
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            sources = state.reorder_usage_sources(data.get("source_ids"))
        except OSError:
            return jsonify({"error": "usage sources update failed"}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"sources": sources})

    @app.patch("/api/usage-sources/<source_id>")
    def patch_usage_source(source_id: str):
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        auth_error = _require_management_auth()
        if auth_error is not None:
            return auth_error
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            source = state.update_usage_source(source_id, data)
        except OSError:
            return jsonify({"error": "usage sources update failed"}), 503
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"source": source})

    @app.post("/api/usage-sources/<source_id>/token")
    def rotate_usage_source_token(source_id: str):
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        auth_error = _require_management_auth()
        if auth_error is not None:
            return auth_error
        try:
            result = state.rotate_usage_source_token(source_id)
        except OSError:
            return jsonify({"error": "usage sources update failed"}), 503
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        response = jsonify({"token": result["token"]})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/usage-sources/<source_id>/observations")
    def observe_usage_source(source_id: str):
        state = context.usage_state
        if state is None:
            return jsonify({"error": "not available"}), 501
        token = request.headers.get("X-Deskbar-Source-Token", "")
        try:
            if not state.verify_usage_source_token(source_id, token):
                return jsonify({"error": "unauthorized"}), 401
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except KeyError:
            return jsonify({"error": "not found"}), 404
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            result = state.observe_usage_source(source_id, data)
        except OSError:
            return jsonify({"error": "usage sources update failed"}), 503
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result)


def _require_management_auth():
    push_token = os.environ.get("DESKBAR_PUSH_TOKEN")
    if not push_token:
        return None
    if request.headers.get("X-Deskbar-Token") != push_token:
        return jsonify({"error": "unauthorized"}), 401
    return None
