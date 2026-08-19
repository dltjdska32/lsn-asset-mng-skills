"""Strict materiality configuration loading without silent defaults."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from investment_stack.materiality.engine import MaterialityConfig


_REQUIRED = {
    "version",
    "min_weight",
    "min_risk_proxy",
    "uncertainty_pass_threshold",
}


def _flat_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"invalid flat YAML line in {path}: {raw_line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key or not value or key in values:
            raise ValueError(f"invalid or duplicate materiality config key: {key!r}")
        values[key] = value
    return values


def load_materiality_config(path: Path) -> MaterialityConfig:
    values = _flat_yaml(Path(path))
    missing = _REQUIRED - values.keys()
    unknown = values.keys() - _REQUIRED
    if missing or unknown:
        raise ValueError(
            "materiality config keys mismatch; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    try:
        config = MaterialityConfig(
            values["version"],
            Decimal(values["min_weight"]),
            Decimal(values["min_risk_proxy"]),
            Decimal(values["uncertainty_pass_threshold"]),
        )
    except InvalidOperation as exc:
        raise ValueError("materiality thresholds must be decimal strings") from exc
    for name in ("min_weight", "min_risk_proxy", "uncertainty_pass_threshold"):
        value = getattr(config, name)
        if value < 0 or value > 1:
            raise ValueError(f"{name} must be between 0 and 1")
    return config
