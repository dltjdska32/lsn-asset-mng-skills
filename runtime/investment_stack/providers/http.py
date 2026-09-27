"""Small stdlib HTTP boundary with injectable transport for deterministic tests."""

from __future__ import annotations

import json
import ssl
import sys
from decimal import Decimal
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any


class ProviderTransportError(RuntimeError):
    pass


Transport = Callable[[str, Mapping[str, str], float], bytes]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        if sys.platform == "win32":
            try:
                import truststore
            except ImportError:
                # Preserve Python's normal certificate validation if the optional
                # platform integration is unavailable; never disable verification.
                context = ssl.create_default_context()
            else:
                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
            response_context = opener.open(request, timeout=timeout)
        else:
            response_context = urllib.request.urlopen(request, timeout=timeout)
        with response_context as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderTransportError(f"provider transport failed: {type(exc).__name__}") from exc


def fetch_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 15.0,
    transport: Transport = urllib_transport,
) -> Any:
    try:
        payload = transport(url, headers or {}, timeout)
        return json.loads(payload.decode("utf-8"), parse_float=Decimal)
    except ProviderTransportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProviderTransportError("provider returned invalid JSON") from exc
    except Exception as exc:
        # Do not reflect transport messages: URLs may contain credentials.
        raise ProviderTransportError(f"provider transport failed: {type(exc).__name__}") from exc
