from __future__ import annotations

import unittest

from investment_stack.providers import (
    CredentialMissing,
    EnvironmentCredentials,
    ProviderCapability,
    ProviderRegistry,
    ProviderSpec,
)


class EnvironmentCredentialsTest(unittest.TestCase):
    def test_missing_and_required_credentials_are_safe(self) -> None:
        credentials = EnvironmentCredentials({})
        self.assertIsNone(credentials.get("MARKET_API_KEY"))
        with self.assertRaisesRegex(CredentialMissing, "MARKET_API_KEY"):
            credentials.require("MARKET_API_KEY")

    def test_invalid_environment_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EnvironmentCredentials({}).get("bad-name")


class ProviderRegistryTest(unittest.TestCase):
    def test_missing_credential_falls_back_by_capability(self) -> None:
        registry = ProviderRegistry(
            [
                ProviderSpec(
                    "preferred",
                    frozenset({ProviderCapability.CURRENT_PRICE}),
                    priority=1,
                    credential_env="PREFERRED_API_KEY",
                ),
                ProviderSpec(
                    "public-fallback",
                    frozenset({ProviderCapability.CURRENT_PRICE}),
                    priority=2,
                ),
            ],
            credentials=EnvironmentCredentials({}),
        )
        resolution = registry.resolve(ProviderCapability.CURRENT_PRICE)
        self.assertEqual("public-fallback", resolution.selected.name if resolution.selected else None)
        self.assertEqual("credential unavailable", resolution.attempts[0].reason)
        self.assertFalse(resolution.partial_required)

    def test_unavailable_capability_requests_partial_result(self) -> None:
        resolution = ProviderRegistry().resolve(ProviderCapability.NEWS)
        self.assertFalse(resolution.available)
        self.assertTrue(resolution.partial_required)

    def test_duplicate_names_are_rejected_case_insensitively(self) -> None:
        first = ProviderSpec("Example", frozenset({ProviderCapability.NEWS}))
        second = ProviderSpec("example", frozenset({ProviderCapability.FX}))
        with self.assertRaises(ValueError):
            ProviderRegistry([first, second])


if __name__ == "__main__":
    unittest.main()

