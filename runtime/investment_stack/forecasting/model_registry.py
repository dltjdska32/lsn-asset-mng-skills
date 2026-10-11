from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
from typing import Mapping


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    role: str
    license: str
    source_url: str
    checkpoint_bytes: int | None = None
    checkpoint_sha256: str | None = None
    tokenizer_id: str | None = None
    tokenizer_bytes: int | None = None
    tokenizer_sha256: str | None = None
    default_enabled: bool = True
    security_note: str | None = None
    revision: str | None = None
    tokenizer_revision: str | None = None


MODEL_SPECS: Mapping[str, ModelSpec] = {
    "chronos2-small": ModelSpec(
        model_id="autogluon/chronos-2-small",
        role="multivariate_covariate_time_series",
        license="Apache-2.0",
        source_url="https://github.com/amazon-science/chronos-forecasting",
        checkpoint_bytes=112_000_000,
        checkpoint_sha256="492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd",
        revision="ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a",
    ),
    "kronos-mini": ModelSpec(
        model_id="NeoQuasar/Kronos-mini",
        role="ohlcv_kline",
        license="MIT",
        source_url="https://github.com/shiyu-coder/Kronos",
        checkpoint_bytes=16_440_776,
        checkpoint_sha256="a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c",
        revision="f4e68697d9d5aed55cef5c96aabc3376bcad9f81",
        tokenizer_revision="b22fb9cb30a2de2f77e8b617169cd756ba964a08",
        tokenizer_id="NeoQuasar/Kronos-Tokenizer-2k",
        tokenizer_bytes=15_842_376,
        tokenizer_sha256="b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717",
    ),
    "fincast-v1": ModelSpec(
        model_id="Vincent05R/FinCast-v1",
        role="financial_time_series",
        license="Apache-2.0",
        source_url="https://github.com/vincent05r/FinCast-fts",
        checkpoint_bytes=3_966_703_063,
        checkpoint_sha256="d5ca999b02c944effa60d2b94174dc4d5a0cd2c0543ae289b2e36f37431492a8",
        default_enabled=False,
        security_note="Official main checkpoint is v1.pth (pickle-based). Keep disabled unless explicitly approved and hash-verified.",
    ),
}


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_checkpoint(path: str | Path, expected_sha256: str) -> bool:
    p = Path(path)
    return p.is_file() and sha256_file(p) == expected_sha256.lower()
