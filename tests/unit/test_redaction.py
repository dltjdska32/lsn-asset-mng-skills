from __future__ import annotations

import io
import logging
import unittest

from investment_stack.security import SecretRedactionFilter, SecretRedactor


class SecretRedactorTest(unittest.TestCase):
    def test_known_secret_is_removed_from_text(self) -> None:
        redactor = SecretRedactor(["super-secret-value"])
        rendered = redactor.text("provider failed with super-secret-value")
        self.assertNotIn("super-secret-value", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_secret_shaped_mapping_keys_are_redacted_recursively(self) -> None:
        redactor = SecretRedactor()
        output = redactor.value(
            {"api_key": "abc", "nested": {"access_token": "def"}, "status": "partial"}
        )
        self.assertEqual("[REDACTED]", output["api_key"])
        self.assertEqual("[REDACTED]", output["nested"]["access_token"])
        self.assertEqual("partial", output["status"])

    def test_inline_credentials_are_redacted(self) -> None:
        rendered = SecretRedactor().text("token=abc123 status=failed")
        self.assertEqual("token=[REDACTED] status=failed", rendered)

    def test_logging_filter_redacts_before_handler_output(self) -> None:
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.addFilter(SecretRedactionFilter(["known-value"]))
        logger = logging.getLogger("investment_stack.tests.redaction")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        logger.info("provider token=%s known=%s", "abc123", "known-value")

        rendered = output.getvalue()
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("known-value", rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
