"""
config.py — runtime configuration. No credentials and no personal data in source.

Every value resolves in this order:
  1. an environment variable
  2. config.json at the repo root (gitignored, never committed)
  3. nothing — and the caller raises a clear error rather than guessing

Nothing here holds a secret. `config.json` holds only the sending address and
two file PATHS; the actual OAuth client secret and refresh token stay in those
files, outside this directory.

Set up:
    cp config.example.json config.json     # then edit config.json
or:
    set BRACE_SENDER_EMAIL=sdr@yourdomain.com
    set BRACE_GMAIL_CREDENTIALS=C:\\path\\to\\credentials.json
    set BRACE_GMAIL_OAUTH_KEYS=C:\\path\\to\\gcp-oauth.keys.json
"""

import os
import json

from core.paths import CONFIG_PATH

_ENV_KEYS = {
    "sender_email": "BRACE_SENDER_EMAIL",
    "gmail_credentials_path": "BRACE_GMAIL_CREDENTIALS",
    "gmail_oauth_keys_path": "BRACE_GMAIL_OAUTH_KEYS",
}


def _load_file():
    """Read config.json if present.

    A malformed file RAISES rather than falling back to {}. Swallowing the
    parse error here produces a "missing config value" message that sends you
    hunting for a key that is actually sitting right there, one bad escape
    away. The most common cause is a Windows path written with single
    backslashes, which is not valid JSON — use forward slashes or double them.
    """
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{CONFIG_PATH} is not valid JSON: {e}\n"
            f"  Most likely a Windows path with single backslashes.\n"
            f'  Use "C:/Users/you/file.json" or "C:\\\\Users\\\\you\\\\file.json".'
        ) from e
    except OSError as e:
        raise RuntimeError(f"Could not read {CONFIG_PATH}: {e}") from e


_FILE = _load_file()


def get(key, default=None):
    """Env var wins, then config.json, then the default."""
    env_name = _ENV_KEYS.get(key)
    if env_name:
        val = os.environ.get(env_name)
        if val:
            return val
    val = _FILE.get(key)
    return val if val else default


def require(key):
    """Same as get(), but fails loudly. Used for anything that would otherwise
    send mail from the wrong account or silently do nothing."""
    val = get(key)
    if not val:
        env_name = _ENV_KEYS.get(key, "(no env var)")
        raise RuntimeError(
            f"Missing config value {key!r}.\n"
            f"  Set the {env_name} environment variable, or add {key!r} to\n"
            f"  {CONFIG_PATH}\n"
            f"  Start from config.example.json."
        )
    return val
