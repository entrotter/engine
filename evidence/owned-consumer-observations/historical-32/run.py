"""One frozen32-input supported CLI attempt, original150s product cap."""
import hashlib,json,os,re,signal,socket,subprocess,sys,time
from pathlib import Path
import certifi
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
readiness=json.loads((HERE/'readiness.json').read_text())
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()==readiness['head']
for name,digest in readiness['sources'].items():assert sha(ROOT/name)==digest,name
for name,digest in readiness['inputs'].items():assert sha(HERE/name)==digest,name
anvil=Path(readiness['anvil_path']);assert sha(anvil)==readiness['anvil_sha256']
assert sha(Path(certifi.where()))==readiness['CA_sha256']
assert json.loads((HERE/'plan.json').read_text())==json.loads((ROOT/'evidence/aave-consumer-price/native-006/plan.json').read_text())
for name in ('stdout.log','stderr.log','observed-trace.json','host-terminal.json','child-terminal.json'):
    assert not (HERE/name).exists(),name
urls=set(re.findall(r'ENTROTTER_RPC_URL:\s*(\S+)',(ROOT/'.github/workflows/isolated.yml').read_text()))
assert len(urls)==1
env=dict(os.environ);env.update(ENTROTTER_RPC_URL=urls.pop(),SSL_CERT_FILE=certifi.where(),PYTHONPATH=str(ROOT/'src'),PATH=str(anvil.parent)+os.pathsep+env.get('PATH',''),ENTROTTER_EXPORT_STATE_DIR=str(HERE/'export-state'))
started=time.monotonic();cause='completed';code=None;process=None;cleanup_errors=[]
with (HERE/'stdout.log').open('xb') as out,(HERE/'stderr.log').open('xb') as err:
    try:
        process=subprocess.Popen([sys.executable,str(HERE/'cli-child.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
        code=process.wait(timeout=190)
    except BaseException as exc:
        cause='host_watchdog190s' if isinstance(exc,subprocess.TimeoutExpired) else ('host_cancelled' if isinstance(exc,KeyboardInterrupt) else 'host_wait_error')
    finally:
        cleanup_deadline=time.monotonic()+10
        if process is not None:
            try:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:process.wait(timeout=min(5,max(.01,cleanup_deadline-time.monotonic())))
                    except subprocess.TimeoutExpired:pass
            except BaseException:cleanup_errors.append('owned_client_stop_error')
            finally:
                try:
                    if process.poll() is None:
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    code=process.wait(timeout=max(.01,cleanup_deadline-time.monotonic()))
                except BaseException:cleanup_errors.append('owned_client_reap_error')
ports=[]
if (HERE/'owned-ledger.json').exists():
    try:
        ledger=HERE/'owned-ledger.json';assert ledger.stat().st_size<=16384
        rows=json.loads(ledger.read_text());assert isinstance(rows,list) and len(rows)<=3
        for row in rows:
            if row['port'] is None:continue
            while True:
                with socket.socket() as sock:
                    sock.settimeout(.2);closed=sock.connect_ex(('127.0.0.1',row['port']))!=0
                try:os.killpg(row['pid'],0);absent=False
                except ProcessLookupError:absent=True
                except PermissionError:absent=False
                if (closed and absent) or time.monotonic()>=cleanup_deadline:break
                time.sleep(min(.05,max(0,cleanup_deadline-time.monotonic())))
            ports.append({**row,'host_group_absent':absent,'host_port_closed':closed})
    except Exception:cleanup_errors.append('owned_ledger_probe_error')
result={'code':code,'cause':cause,'host_cleanup_errors':cleanup_errors,'host_seconds':time.monotonic()-started,'cli_reaped':process is not None and process.poll() is not None,'original_product_cap_seconds':150,'host_watchdog_seconds':190,'native_no_CPU_RSS_sandbox':True,'sources_unchanged':all(sha(ROOT/n)==h for n,h in readiness['sources'].items()),'inputs_unchanged':all(sha(HERE/n)==h for n,h in readiness['inputs'].items()),'owned_host_observations':ports,'no_signals_to_grandchild_identifiers':True}
(HERE/'host-terminal.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
raise SystemExit(code if type(code) is int and code>=0 and cause=='completed' and not cleanup_errors else 1)
