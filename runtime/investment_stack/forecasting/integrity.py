import json
from pathlib import Path
import hashlib
import sys
import subprocess

from investment_stack.forecasting.model_registry import MODEL_SPECS

def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def verify_snapshot_manifest(model_dir: str | Path, expected_model_id: str) -> dict:
    supplied_dir = Path(model_dir)
    if supplied_dir.is_symlink():
        raise ValueError("symlink snapshot directory is not allowed")
    model_dir = supplied_dir.resolve()
    manifest_path = model_dir / "snapshot_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("symlink snapshot manifest is not allowed")
    if not manifest_path.exists():
        raise RuntimeError(f"Missing snapshot_manifest.json in {model_dir}")
    
    with manifest_path.open("r", encoding="utf-8") as f:
        try:
            manifest = json.load(f)
        except json.JSONDecodeError:
            raise RuntimeError(f"Malformed snapshot_manifest.json in {model_dir}")
    
    if not isinstance(manifest, dict) or not manifest:
        raise RuntimeError("Empty or invalid manifest")
    
    # Check version
    if manifest.get("version") != 1:
        raise RuntimeError("Unsupported manifest version")
    
    if manifest.get("model_id") != expected_model_id:
        raise RuntimeError(f"Manifest model_id mismatch: expected {expected_model_id}")
        
    spec = next((s for s in MODEL_SPECS.values() if s.model_id == expected_model_id), None)
    if not spec:
        spec = next((s for s in MODEL_SPECS.values() if s.tokenizer_id == expected_model_id), None)
        if not spec:
            raise RuntimeError(f"No spec found for {expected_model_id}")
            
    is_tokenizer = spec.tokenizer_id == expected_model_id
    
    # Check required fields
    required = ["revision", "files"]
    for req in required:
        if req not in manifest:
            raise RuntimeError(f"Missing required manifest field: {req}")
            
    if not isinstance(manifest["revision"], str) or len(manifest["revision"]) != 40 or any(c not in "0123456789abcdef" for c in manifest["revision"]):
        raise ValueError("exact pinned revision required, not 'main' or short hash")
    
    expected_revision = spec.tokenizer_revision if is_tokenizer else spec.revision
    if expected_revision is None or manifest["revision"] != expected_revision:
        raise ValueError("snapshot revision does not match pinned registry revision")

    # Verify files
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise RuntimeError("Missing or empty files manifest")
        
    # verify coverage
    if "config.json" not in files:
        raise ValueError("Missing config.json in manifest")
        
    if "model.safetensors" not in files:
        raise ValueError("Missing model.safetensors in manifest")
        
    # Check against spec hashes
    if is_tokenizer:
        if files["model.safetensors"].lower() != spec.tokenizer_sha256:
            raise ValueError(f"tokenizer weight hash mismatch: expected {spec.tokenizer_sha256}")
    else:
        if files["model.safetensors"].lower() != spec.checkpoint_sha256:
            raise ValueError(f"model weight hash mismatch: expected {spec.checkpoint_sha256}")
    
    for filename, expected_hash in files.items():
        if not isinstance(filename, str) or Path(filename).is_absolute() or any(part in ("..", ".") for part in Path(filename).parts) or "\\" in filename:
            raise ValueError(f"Path escape attempt: {filename}")
        
        file_path = (model_dir / filename).resolve()
        
        # Path confinement
        if (model_dir / filename).is_symlink() or not file_path.is_relative_to(model_dir):
            raise ValueError(f"Path escape attempt: {filename}")
        
        if not file_path.is_file():
            raise RuntimeError(f"Missing required model file: {filename}")
        
        actual_hash = sha256_file(file_path)
        if actual_hash.lower() != expected_hash.lower():
            raise RuntimeError(f"SHA256 mismatch for {filename}: expected {expected_hash}, actual {actual_hash}")

    # The manifest is an exhaustive inventory. Extra hidden, newly injected or
    # changed files must not silently survive integrity validation.
    declared = set(files)
    actual = set()
    for path in model_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink snapshot entry: {path.relative_to(model_dir)}")
        if path.is_file() and path != manifest_path:
            actual.add(path.relative_to(model_dir).as_posix())
    if actual != declared:
        raise ValueError(f"snapshot file inventory mismatch: missing={sorted(declared - actual)}, "
                         f"undeclared={sorted(actual - declared)}")
    return manifest

def verify_kronos_source(source_root: str | Path, expected_commit: str) -> Path:
    source_root = Path(source_root).resolve()
    if not source_root.exists():
        raise RuntimeError(f"Kronos source root not found: {source_root}")
    
    if not (source_root / ".git").exists() and not (source_root / ".git").is_file():
        raise RuntimeError("Kronos source root is not a git repository")
    
    for name, loaded in tuple(sys.modules.items()):
        if name == "model" or name.startswith("model."):
            module_file = getattr(loaded, "__file__", None)
            if not module_file or not Path(module_file).resolve().is_relative_to(source_root):
                raise RuntimeError(f"foreign preloaded Kronos module: {name}")
    if "model" in sys.modules:
        mod = sys.modules["model"]
        if not hasattr(mod, "__file__") or not mod.__file__:
            raise RuntimeError("sys.modules['model'] preloaded without file")
        mod_file = Path(mod.__file__).resolve()
        if not mod_file.is_relative_to(source_root):
            try:
                del sys.modules["model"]
            finally:
                raise RuntimeError(f"sys.modules['model'] preloaded from elsewhere: {mod_file}")

    try:
        actual = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to check git commit: {e.output}")
        
    if actual != expected_commit:
        raise RuntimeError(f"Kronos source commit mismatch: expected {expected_commit}, actual {actual}")
    
    try:
        status = subprocess.check_output(["git", "-C", str(source_root), "status", "--porcelain"], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to check git status: {e.output}")
    
    if status.strip():
        raise RuntimeError(f"Kronos source is dirty: {status}")

    # `git status --porcelain` omits ignored files. Python may prefer an
    # ignored model/kronos/__init__.py package over tracked model/kronos.py.
    # Deny ignored executable/importable artifacts anywhere in this source
    # checkout; allow ordinary ignored non-code weights, logs and data caches.
    # This must run before any `model.*` module import.
    try:
        ignored = subprocess.check_output(
            ["git", "-C", str(source_root), "ls-files", "--others", "--ignored",
             "--exclude-standard", "-z"], stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to inventory ignored source entries: {exc.output}") from exc
    if isinstance(ignored, str):
        ignored_paths = [v for v in ignored.split("\0") if v]
    else:
        ignored_paths = [v.decode("utf-8", errors="surrogateescape")
                         for v in ignored.split(b"\0") if v]
    executable_suffixes = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dll", ".pth", ".pyi"}
    for relative in ignored_paths:
        path = source_root / relative
        if (path.suffix.lower() in executable_suffixes or path.is_symlink()
                or (path.is_dir() and relative.startswith("model/"))):
            raise RuntimeError(f"ignored executable/import-shadowing Kronos source: {relative}")

    # Symlinks inside Python's import root can redirect to unchecked bytes
    # even when the repository itself is clean.
    import_root = source_root / "model"
    if import_root.exists():
        for candidate in import_root.rglob("*"):
            if candidate.is_symlink():
                raise RuntimeError(f"Kronos import-tree symlink: {candidate.relative_to(source_root)}")

    return source_root
