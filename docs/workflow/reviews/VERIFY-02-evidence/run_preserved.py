import os, subprocess, sys, json
from pathlib import Path
root = Path(__file__).parent / 'exact-source'
env = dict(os.environ, PYTHONPATH=str(root / 'runtime'), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
names = ['first_pass_probes', 'interim_probes', 'b1f4514_probes', 'final_probes', 'dcd262a_probes', 'briefing_persistence_probe', 'refresh_binding_checks', 'rc12_roundtrip_checks']
results = []
for name in names:
    path = root / 'docs/workflow/reviews' / ('review_code_01_' + name + '.py')
    with (root.parent / (name + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, str(path), '-v'], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    results.append({'suite': name, 'returncode': result.returncode})
    print(json.dumps(results[-1]), flush=True)
(root.parent / 'preserved-results.json').write_text(json.dumps(results, indent=2))
sys.exit(any(row['returncode'] for row in results))
