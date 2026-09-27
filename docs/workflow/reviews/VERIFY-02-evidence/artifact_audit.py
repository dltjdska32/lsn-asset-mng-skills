import hashlib, json, subprocess, sys, tarfile, zipfile
from pathlib import Path
base = Path(__file__).parent.resolve()
source = base / 'exact-clone'
sha = '2a078da91ddfd761a1785ee482f3cd23eb1acaf7'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == sha
assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip() == ''
# Compare committed contents, not checkout CRLF representations.
with zipfile.ZipFile(base / 'exact-source.zip') as archive:
    archive_files = set(archive.namelist())
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=source).decode().split('\0')[:-1]
    for name in tracked:
        assert name in archive_files, name
        blob = subprocess.check_output(['git', 'show', f'{sha}:{name}'], cwd=source)
        assert archive.read(name).replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n'), name
wheel = source / 'dist/investment_stack-0.1.0-py3-none-any.whl'
sdist = source / 'dist/investment_stack-0.1.0.tar.gz'
with zipfile.ZipFile(wheel) as z, zipfile.ZipFile(base / 'exact-source/dist' / wheel.name) as first:
    assert z.namelist() == first.namelist()
    assert all(z.read(n) == first.read(n) for n in z.namelist())
    runtime = [n for n in z.namelist() if n.startswith('investment_stack/') and n.endswith('.py')]
    for name in runtime:
        assert z.read(name) == (Path(sys.prefix) / 'Lib/site-packages' / name).read_bytes(), name
    payload = [n for n in z.namelist() if '.data/data/' in n]
    for name in payload:
        assert z.read(name) == (Path(sys.prefix) / name.split('.data/data/')[1]).read_bytes(), name
    assert len(payload) == 37
out = base / 'sdist-unpacked'
out.mkdir(exist_ok=True)
with tarfile.open(sdist) as t:
    t.extractall(out, filter='data')
result = {'target_sha': sha, 'tracked_files_match_archive_with_crlf_normalized': len(tracked),
          'runtime_files_match_installed_wheel': len(runtime), 'installed_data_files_match': len(payload),
          'archive_and_clone_wheel_payload_identical': True,
          'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, sdist)},
          'python': sys.version, 'executable': sys.executable}
(base / 'artifact-audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
