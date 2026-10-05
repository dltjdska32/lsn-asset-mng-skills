#!/usr/bin/env python3
"""Build from a clean tree and reject stale or missing runtime payloads."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    import os
    os.chdir(root)
    # ZIP extraction can preserve source mtimes older than a cached build/lib.
    shutil.rmtree(root / "build", ignore_errors=True)
    from setuptools.build_meta import build_sdist, build_wheel
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    wheel = dist / build_wheel(str(dist))
    sdist = dist / build_sdist(str(dist))
    checked = 0
    with zipfile.ZipFile(wheel) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("wheel integrity failed")
        for source in (root / "runtime" / "investment_stack").rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            if source.suffix not in {".py", ".sql", ".json"}:
                continue
            name = source.relative_to(root / "runtime").as_posix()
            if archive.read(name) != source.read_bytes():
                raise RuntimeError(f"stale distribution payload: {name}")
            checked += 1
    print(json.dumps({"verified_runtime_files": checked, "distributions": [
        {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in (wheel, sdist)]}, indent=2))


if __name__ == "__main__":
    main()
