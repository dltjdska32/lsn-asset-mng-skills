"""Logging integration that redacts secrets before handlers emit records."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from investment_stack.security.redaction import SecretRedactor


class SecretRedactionFilter(logging.Filter):
    """Replace secrets in the rendered message and custom string attributes."""

    _STANDARD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)

    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._redactor = SecretRedactor(known_secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redactor.text(record.getMessage())
        record.args = ()
        for key, value in vars(record).items():
            if key not in self._STANDARD_RECORD_KEYS and isinstance(value, str):
                setattr(record, key, self._redactor.text(value))
        return True
