"""Check that a syntactically valid request hash needs a real request descriptor.

Uses only an empty selection and a synthetic temporary run database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "runtime"))

    from investment_stack.contracts import InputIntegrityError, SelectedInputSet
    from investment_stack.evidence.manager import RunDatabaseManager

    with TemporaryDirectory(prefix="contract-request-descriptor-") as directory:
        manager = RunDatabaseManager(Path(directory), "synthetic-run")
        report = manager.create()
        assert report.valid, report.errors
        # No SelectionRequest exists in this run. A SHA-256-shaped token cannot
        # establish the requested slots, period, currency, or purpose by itself.
        snapshot = SelectedInputSet.create(
            manager.run_id,
            "INSTITUTIONAL_COMPARE",
            1,
            [],
            instrument_id="TEST",
            request_hash="0" * 64,
        )
        try:
            manager.persist_contract_snapshot(snapshot)
        except InputIntegrityError as exc:
            print(f"PASS unresolved_valid_hash_rejected: {type(exc).__name__}: {exc}")
            return 0
        print("FAIL unresolved_valid_hash_accepted: arbitrary 64-character digest persisted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
