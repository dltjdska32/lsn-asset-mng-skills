"""Discover every repository test module and save a machine-readable result."""
from pathlib import Path
import argparse, json, subprocess, sys, time, unittest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    git=['git','-c','safe.directory='+str(root)]
    commit=subprocess.check_output([*git,'rev-parse','HEAD'],cwd=root,text=True).strip()
    if subprocess.check_output([*git,'status','--porcelain','--untracked-files=no'],cwd=root,text=True).strip():
        raise RuntimeError('commit tracked changes before the final regression')
    sys.path[:0]=[str(root),str(root/'runtime')]
    names=['.'.join(p.relative_to(root).with_suffix('').parts) for p in sorted((root/'tests').rglob('test_*.py'))]
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    final_commit=subprocess.check_output([*git,'rev-parse','HEAD'],cwd=root,text=True).strip()
    unchanged=commit==final_commit and not subprocess.check_output([*git,'status','--porcelain','--untracked-files=no'],cwd=root,text=True).strip()
    total=result.testsRun
    summary={'head':commit,'test_modules':len(names),'total':total,'passed':total-len(result.failures)-len(result.errors)-len(result.skipped),
        'skipped':len(result.skipped),'failed':len(result.failures)+len(result.errors),
        'duration_seconds':round(time.monotonic()-started,3),
        'failures':[str(t) for t,_ in (*result.failures,*result.errors)],
        'skip_reasons':[reason for _,reason in result.skipped], 'head_unchanged':unchanged}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if result.wasSuccessful() and unchanged else 1

if __name__=='__main__':raise SystemExit(main())
