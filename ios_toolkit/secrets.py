"""
secrets.py — credential retrieval from environment variables.

This module is named "secrets" again (it was briefly "credentials"). The name is
safe because no Nuitka multidist --main lives inside this package anymore: both
entry points (CablediOS.py and cabled_ios_tunnel.py) sit at the repo root, so
ios_toolkit/ never becomes a top-level import root. This file is therefore only
importable as ``ios_toolkit.secrets`` and can never shadow the stdlib ``secrets``
module that dependencies such as pymobiledevice3 import.

Convention: IOS_CRED_<ROLE>_<FIELD>
  role and field are uppercased automatically.

Plaintext values MUST NOT appear in any log, exception message, or response body.
"""

import os


def get_credential(role: str, field: str) -> str | None:
    """Return the credential value, or None if the env var is not set."""
    key = f"IOS_CRED_{role.upper()}_{field.upper()}"
    return os.environ.get(key)


def credential_env_key(role: str, field: str) -> str:
    """Return the expected env var name (safe to log — does not contain the value)."""
    return f"IOS_CRED_{role.upper()}_{field.upper()}"
