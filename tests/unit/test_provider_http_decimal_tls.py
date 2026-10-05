"""JSON precision and scoped Windows TLS tests for provider transport."""

import ssl
import gzip
import zlib
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from investment_stack.providers.http import fetch_json, urllib_transport, ProviderTransportError


class ProviderHttpTests(unittest.TestCase):
    def test_json_fractional_tokens_decode_as_decimal(self) -> None:
        result = fetch_json("https://example.invalid", transport=lambda *_: b'{"price":0.123456789123456789}')
        self.assertEqual(result["price"], Decimal("0.123456789123456789"))

    def test_windows_transport_uses_scoped_truststore_context(self) -> None:
        seen = {}

        class Response:
            headers = {}
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"ok"

        class Opener:
            def open(self, request, timeout):
                seen["request"] = request
                seen["timeout"] = timeout
                return Response()

        trust_context = object()
        fake_truststore = SimpleNamespace(
            SSLContext=lambda protocol: (seen.update(protocol=protocol) or trust_context)
        )
        with (
            patch("investment_stack.providers.http.sys.platform", "win32"),
            patch.dict(sys.modules, {"truststore": fake_truststore}),
            patch("investment_stack.providers.http.urllib.request.build_opener") as build_opener,
        ):
            build_opener.return_value = Opener()
            self.assertEqual(urllib_transport("https://example.invalid", {"X-Test": "1"}, 3), b"ok")

        handler = build_opener.call_args.args[0]
        self.assertIs(handler._context, trust_context)
        self.assertEqual(seen["protocol"], ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(seen["timeout"], 3)

    def test_captured_gzip_json_preserves_decimal(self):
        payload = gzip.compress(b'{"value":0.123456789123456789}')
        result = fetch_json('https://example.invalid', transport=lambda *_: payload)
        self.assertEqual(result['value'], Decimal('0.123456789123456789'))

    def test_http_compression_and_corrupt_gzip_fail_closed(self):
        from unittest.mock import MagicMock
        for encoding, payload in [('gzip', gzip.compress(b'{"ok":true}')),
                                  ('deflate', zlib.compress(b'{"ok":true}'))]:
            response = MagicMock()
            response.__enter__.return_value = response
            response.headers = {'Content-Encoding': encoding}
            response.read.return_value = payload
            with patch('investment_stack.providers.http.sys.platform', 'linux'), patch('investment_stack.providers.http.urllib.request.urlopen', return_value=response):
                self.assertEqual(fetch_json('https://example.invalid'), {'ok': True})
        with self.assertRaises(ProviderTransportError):
            fetch_json('https://example.invalid', transport=lambda *_: b'\x1f\x8bbroken')


if __name__ == "__main__":
    unittest.main()
