"""
Credential storage — passwords go into the OS keychain (Windows Credential Manager),
never into SQLite.
"""
try:
    import keyring as _keyring
    _KEYRING_OK = True
except ImportError:
    _keyring = None
    _KEYRING_OK = False

_SERVICE         = "postbox"
_AI_SERVICE      = "postbox_ai"
_AI_USER         = "anthropic_api_key"
_OAUTH_SERVICE   = "postbox_oauth"
_MS_SERVICE      = "postbox_ms"
_MS_CLIENT_KEY   = "client_id"
_GOOGLE_CFG_SVC  = "postbox_google_cfg"
_GOOGLE_CFG_KEY  = "config"


def store_password(account_id: int, password: str) -> None:
    if _KEYRING_OK:
        _keyring.set_password(_SERVICE, str(account_id), password)
    else:
        # Fallback: write to a local file (not recommended for production)
        import json, os
        _path = _fallback_path()
        data = _load_fallback()
        data[str(account_id)] = password
        with open(_path, "w") as f:
            json.dump(data, f)


def get_password(account_id: int) -> str | None:
    if _KEYRING_OK:
        return _keyring.get_password(_SERVICE, str(account_id))
    else:
        return _load_fallback().get(str(account_id))


def delete_password(account_id: int) -> None:
    if _KEYRING_OK:
        try:
            _keyring.delete_password(_SERVICE, str(account_id))
        except Exception:
            pass
    else:
        import json
        data = _load_fallback()
        data.pop(str(account_id), None)
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def store_api_key(key: str) -> None:
    if _KEYRING_OK:
        _keyring.set_password(_AI_SERVICE, _AI_USER, key)
    else:
        import json
        data = _load_fallback()
        data["__api_key__"] = key
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def get_api_key() -> str | None:
    import os
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env
    if _KEYRING_OK:
        return _keyring.get_password(_AI_SERVICE, _AI_USER)
    return _load_fallback().get("__api_key__")


def store_ms_client_id(client_id: str) -> None:
    if _KEYRING_OK:
        _keyring.set_password(_MS_SERVICE, _MS_CLIENT_KEY, client_id)
    else:
        import json
        data = _load_fallback()
        data["__ms_client_id__"] = client_id
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def get_ms_client_id() -> str | None:
    if _KEYRING_OK:
        return _keyring.get_password(_MS_SERVICE, _MS_CLIENT_KEY)
    return _load_fallback().get("__ms_client_id__")


def store_google_client_config(client_id: str, client_secret: str) -> None:
    import json
    value = json.dumps({"client_id": client_id, "client_secret": client_secret})
    if _KEYRING_OK:
        _keyring.set_password(_GOOGLE_CFG_SVC, _GOOGLE_CFG_KEY, value)
    else:
        data = _load_fallback()
        data["__google_cfg__"] = value
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def get_google_client_config() -> dict | None:
    import json
    if _KEYRING_OK:
        val = _keyring.get_password(_GOOGLE_CFG_SVC, _GOOGLE_CFG_KEY)
    else:
        val = _load_fallback().get("__google_cfg__")
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


def store_oauth_tokens(account_id: int, tokens: dict) -> None:
    import json
    value = json.dumps(tokens)
    if _KEYRING_OK:
        _keyring.set_password(_OAUTH_SERVICE, str(account_id), value)
    else:
        data = _load_fallback()
        data[f"__oauth_{account_id}__"] = value
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def get_oauth_tokens(account_id: int) -> dict | None:
    import json
    if _KEYRING_OK:
        val = _keyring.get_password(_OAUTH_SERVICE, str(account_id))
    else:
        val = _load_fallback().get(f"__oauth_{account_id}__")
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


def delete_oauth_tokens(account_id: int) -> None:
    if _KEYRING_OK:
        try:
            _keyring.delete_password(_OAUTH_SERVICE, str(account_id))
        except Exception:
            pass
    else:
        import json
        data = _load_fallback()
        data.pop(f"__oauth_{account_id}__", None)
        with open(_fallback_path(), "w") as f:
            json.dump(data, f)


def _fallback_path() -> str:
    import os
    return os.path.join(os.path.expanduser("~"), ".postbox_creds.json")


def _load_fallback() -> dict:
    import json, os
    try:
        with open(_fallback_path()) as f:
            return json.load(f)
    except Exception:
        return {}
