"""
Shared utilities for Flask blueprints — ok(), err(), db(), dict_rows().
No auth required: postbox is a local-only single-user app.
"""
from flask import current_app, jsonify


def db() -> str:
    return current_app.config.get("DB_PATH")


def dict_rows(rows) -> list[dict]:
    return [dict(r) for r in rows]


def ok(data=None, **kwargs):
    return jsonify({"ok": True, "data": data, **kwargs})


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code
