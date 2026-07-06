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

_SERVICE    = "postbox"
_AI_SERVICE = "postbox_ai"
_AI_USER    = "anthropic_api_key"


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
