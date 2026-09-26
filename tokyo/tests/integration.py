"""Opt-in genuine archive and process-lifecycle checks. Never silently skip."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import compare
p=argparse.ArgumentParser();p.add_argument('--anvil',required=True);p.add_argument('--cast',required=True);args=p.parse_args()
args.anvil=str(Path(args.anvil).resolve());args.cast=str(Path(args.cast).resolve())
expected=json.loads((ROOT/'evidence/example.json').read_text())['report']
base=[sys.executable,str(ROOT/'compare.py'),'--anvil',args.anvil,'--cast',args.cast,'--block-hash',expected['source']['blockHash']]
checks=[]
def absent(pid):
    try: os.kill(pid,0)
    except ProcessLookupError:return True
    return False
with tempfile.TemporaryDirectory(prefix='tokyo-integration-') as tmp:
    path=Path(tmp)/'report.json'
    completed=subprocess.run(base+['--output',str(path)],capture_output=True,text=True,timeout=260)
    if completed.returncode: raise RuntimeError(completed.stderr)
    got=json.loads(path.read_text())['report']
    for key in ['source','contracts','constraints','setup','trials']:
        if got[key]!=expected[key]:raise AssertionError('Clean reproduction mismatch: '+key)
    checks.append({'name':'fresh archive reproduction; exact receipts, calldata, snapshots and deltas','status':'PASS','runtimeSeconds':got['runtimeSeconds']})
    if not absent(got['nodePid']):raise AssertionError('success leaked Anvil')
    checks.append({'name':'Anvil cleanup after successful execution','status':'PASS'})
    rejected=subprocess.run(base+['--block-hash','0x'+'f'*64,'--output',str(Path(tmp)/'wrong.json')],capture_output=True,text=True,timeout=30)
    if rejected.returncode==0 or 'mismatch' not in rejected.stderr or (Path(tmp)/'wrong.json').exists():raise AssertionError('wrong hash accepted')
    checks.append({'name':'real upstream wrong-hash rejection without report','status':'PASS'})
    with compare.read_proxy(os.environ.get('TOKYO_RPC_URL','https://eth.drpc.org')) as proxy:
        try:
            with compare.node(args.anvil,proxy,23000000) as (local,pid):
                raise compare.Failure('injected fault')
        except compare.Failure as e:
            if str(e)!='injected fault':raise
        if not absent(pid):raise AssertionError('fault leaked Anvil')
        checks.append({'name':'real Anvil cleanup after injected exception','status':'PASS'})
    proc=subprocess.Popen(base+['--output',str(Path(tmp)/'cancelled.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    child=None
    try:
        for _ in range(150):
            result=subprocess.run(['pgrep','-P',str(proc.pid),'-x','anvil'],capture_output=True,text=True)
            if result.stdout.strip():child=int(result.stdout.strip().splitlines()[0]);break
            if proc.poll() is not None: raise AssertionError('CLI exited before cancellation check')
            time.sleep(.1)
        if child is None:raise AssertionError('Anvil child not found')
        proc.send_signal(signal.SIGTERM);out,err=proc.communicate(timeout=30)
        if proc.returncode==0 or not absent(child) or (Path(tmp)/'cancelled.json').exists():raise AssertionError('cancellation failed')
        checks.append({'name':'SIGTERM cleans owned Anvil; no partial report','status':'PASS'})
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
print(json.dumps({'checks':checks,'passed':len(checks),'failed':0,'skipped':0},indent=2))
