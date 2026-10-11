#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.investment_stack.forecasting.model_registry import MODEL_SPECS, sha256_file

HF_SPECS = {
    "chronos2-small": {
        "repo_id": "autogluon/chronos-2-small",
        "revision": MODEL_SPECS["chronos2-small"].revision,
        "sha256": MODEL_SPECS["chronos2-small"].checkpoint_sha256,
        "model_id": MODEL_SPECS["chronos2-small"].model_id,
        "allow_patterns": ["config.json", "model.safetensors", "generation_config.json", "preprocessor_config.json"],
    },
    "kronos-mini": {
        "repo_id": "NeoQuasar/Kronos-mini",
        "revision": MODEL_SPECS["kronos-mini"].revision,
        "sha256": MODEL_SPECS["kronos-mini"].checkpoint_sha256,
        "model_id": MODEL_SPECS["kronos-mini"].model_id,
        "allow_patterns": ["config.json", "model.safetensors"],
    },
    "kronos-tokenizer-2k": {
        "repo_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "revision": MODEL_SPECS["kronos-mini"].tokenizer_revision,
        "sha256": MODEL_SPECS["kronos-mini"].tokenizer_sha256,
        "model_id": MODEL_SPECS["kronos-mini"].tokenizer_id,
        "allow_patterns": ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"],
    },
}
KRONOS_REPO = "https://github.com/shiyu-coder/Kronos.git"
KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"


def _download_model(name: str, root: Path, local_files_only: bool) -> dict:
    spec = HF_SPECS[name]
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    
    # Download files
    try:
        snapshot_download(
            repo_id=spec["repo_id"],
            revision=spec["revision"],
            allow_patterns=spec["allow_patterns"],
            local_dir=str(target),
            local_files_only=local_files_only,
        )
    except Exception as e:
        raise RuntimeError(f"Download failed for {name}: {e}")

    # Identify primary weight file to check expected SHA
    weight_candidates = ["model.safetensors"]
    weight = None
    for cand in weight_candidates:
        if (target / cand).is_file():
            weight = target / cand
            break
            
    if not weight:
        raise RuntimeError(f"Missing primary file (model.safetensors or tokenizer.json) for {name}")
        
    actual = sha256_file(weight)
    expected = spec["sha256"]
    if expected and actual.lower() != expected.lower():
        raise RuntimeError(f"SHA256 mismatch for {name}: expected={expected}, actual={actual}")

    # Build files manifest for all downloaded files
    files_manifest = {}
    for path in target.rglob("*"):
        if path.is_file() and path.name != "snapshot_manifest.json":
            rel_path = path.relative_to(target).as_posix()
            files_manifest[rel_path] = sha256_file(path)
            
    manifest = {
        "version": 1,
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "files": files_manifest
    }
    
    manifest_path = target / "snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return {
        "name": name,
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "path": str(target),
        "manifest_path": str(manifest_path),
        "verified": True,
    }


def _ensure_kronos_source(root: Path, skip: bool, local_files_only: bool = False) -> dict:
    target = root / "kronos-source"
    if skip:
        return {"status": "SKIPPED", "path": str(target), "commit": KRONOS_COMMIT}
    if local_files_only:
        from runtime.investment_stack.forecasting.integrity import verify_kronos_source
        try:
            verify_kronos_source(target, KRONOS_COMMIT)
        except (RuntimeError, OSError) as exc:
            return {"status": "UNAVAILABLE", "path": str(target), "reason": str(exc)}
        return {"status": "READY", "path": str(target), "commit": KRONOS_COMMIT}
    if not shutil.which("git"):

        raise RuntimeError("git executable is required to fetch Kronos source")
    if not (target / ".git").exists():
        subprocess.run(["git", "clone", "--no-tags", KRONOS_REPO, str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "fetch", "origin", KRONOS_COMMIT, "--depth", "1"], check=True)
    subprocess.run(["git", "-C", str(target), "checkout", "--detach", KRONOS_COMMIT], check=True)
    actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
    if actual != KRONOS_COMMIT:
        raise RuntimeError(f"Kronos source commit mismatch: {actual}")
    return {"status": "READY", "path": str(target), "commit": actual}


def main() -> int:
    ap = argparse.ArgumentParser(description="Download and verify official pretrained forecasting models")
    ap.add_argument("--models-dir", default=str(ROOT / "models"))
    ap.add_argument("--local-files-only", action="store_true")
    ap.add_argument("--skip-kronos-source", action="store_true")
    ns = ap.parse_args()

    root = Path(ns.models_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = {"models_dir": str(root), "models": [], "kronos_source": None, "status": "COMPLETE"}
    try:
        for name in ("chronos2-small", "kronos-mini", "kronos-tokenizer-2k"):
            result["models"].append(_download_model(name, root, ns.local_files_only))
        result["kronos_source"] = _ensure_kronos_source(root, ns.skip_kronos_source, ns.local_files_only)
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2

    # Still write PRETRAINED_MODELS.json for compatibility if needed, but per-folder manifest is primary
    manifest = root / "PRETRAINED_MODELS.json"
    manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
