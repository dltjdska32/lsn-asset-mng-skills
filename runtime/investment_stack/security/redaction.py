"""Credential-safe diagnostic redaction."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|token|secret|password|credential)", re.IGNORECASE)
_INLINE_SECRET = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential)(\s*[:=]\s*)([^\s,;]+)"
)


class SecretRedactor:
    """Redact known values and common secret-shaped key/value pairs."""

    replacement = "[REDACTED]"

    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        self._known = tuple(sorted({value for value in known_secrets if value}, key=len, reverse=True))

    def text(self, value: object) -> str:
        redacted = str(value)
        for secret in self._known:
            redacted = redacted.replace(secret, self.replacement)
        return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}{self.replacement}", redacted)

    def value(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and _SENSITIVE_KEY.search(key):
            return self.replacement
        if isinstance(value, Mapping):
            return {str(item_key): self.value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.value(item) for item in value)
        if isinstance(value, str):
            return self.text(value)
        return value

