import json,os,signal,subprocess,sys,time
from pathlib import Path
q=Path(__file__).resolve().parent
log=q/'full-native-002.log'
assert not log.exists()
env=dict(os.environ)
env.pop('ENTROTTER_RPC_URL',None)
env['PATH']='$WORKSPACE_ROOT/.tools/foundry-v1.8.3:'+env['PATH']
env['PYTHONPATH']='src'
env['ENTROTTER_EXPORT_STATE_DIR']=str(q/'full-native-002-export-state')
env['ENTROTTER_TEST_EVIDENCE_DIR']=str(q/'full-native-002-evidence')
started=time.monotonic()
with log.open('xb') as output:
 process=subprocess.Popen([sys.executable,'-m','unittest','discover','-s','tests','-v'],env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 try:
  code=process.wait(timeout=600)
  cause='completed'
 except subprocess.TimeoutExpired:
  os.killpg(process.pid,signal.SIGKILL)
  code=process.wait(timeout=10)
  cause='owned_suite_deadline'
result={'returncode':code,'cause':cause,'host_seconds':round(time.monotonic()-started,6),'shared_native_test_budget_seconds':600,'signing_keys':'none','archive_environment_removed':True,'export_and_evidence_state':'fresh unique ignored directories','suite_process_reaped':process.poll() is not None}
(q/'full-native-002-terminal.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(code if code>=0 else 1)
