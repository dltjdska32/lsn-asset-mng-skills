"""Environment-only credential access."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CredentialMissing(RuntimeError):
    """A requested credential is absent; the value is never included."""


class EnvironmentCredentials:
    """Read secrets from an injected mapping or the process environment."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environment is None else environment

    @staticmethod
    def validate_name(name: str) -> str:
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"Invalid credential environment variable name: {name!r}")
        return name

    def get(self, name: str) -> str | None:
        checked = self.validate_name(name)
        value = self._environment.get(checked)
        if value is None or not value.strip():
            return None
        return value

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise CredentialMissing(f"Required credential {name} is not configured")
        return value

