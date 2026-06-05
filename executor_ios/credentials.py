"""
credentials.py — credential retrieval from environment variables.

Named "credentials" rather than "secrets" so it never shadows Python's stdlib
``secrets`` module (which some dependencies import) in a frozen/standalone build
where package siblings can become importable at the top level.

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
