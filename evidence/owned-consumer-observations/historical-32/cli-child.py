"""Run the real CLI module; passive lifecycle profile, no runtime replacement."""
import json,os,runpy,socket,sys,time
from pathlib import Path
from urllib.parse import urlsplit
HERE=Path(__file__).resolve().parent
objects=[];telemetry_errors=[]
def secondary(code):
    if code not in telemetry_errors and len(telemetry_errors)<16:telemetry_errors.append(code)
def atomic(name,value):
    body=json.dumps(value,indent=2)+'\n'
    if len(body.encode())>16384:raise ValueError('Finite telemetry bound exceeded')
    temporary=HERE/(name+'.tmp');temporary.write_text(body);temporary.replace(HERE/name)
def profile(frame,event,arg):
    if event!='return' or frame.f_code.co_name not in ('__enter__','__exit__'):
        return
    name=frame.f_code.co_filename
    if not name.endswith(('/entrotter_engine/evm.py','/entrotter_engine/parent_cache.py')):
        return
    obj=frame.f_locals.get('self')
    if obj is not None and all(obj is not prior for prior in objects):
        objects.append(obj)
    try:
        rows=[]
        for owned in objects:
            process=getattr(owned,'process',None)
            if process is None:continue
            url=getattr(getattr(owned,'rpc',None),'url',getattr(owned,'url',''))
            rows.append({'kind':type(owned).__name__,'pid':process.pid,'port':urlsplit(url).port})
        atomic('owned-ledger.json',rows)
    except Exception:secondary('lifecycle_record_failed')
started=time.monotonic();code=None;primary=None
sys.argv=['entrotter_engine','trace-observe',str(HERE/'plan.json'),'--native','-o',str(HERE/'observed-trace.json')]
try:
    sys.setprofile(profile)
    try:runpy.run_module('entrotter_engine',run_name='__main__')
    except SystemExit as exc:
        code=exc.code if isinstance(exc.code,int) else (0 if exc.code is None else 1)
    except BaseException as exc:
        primary='cancelled' if isinstance(exc,KeyboardInterrupt) else 'cli_exception'
        raise
finally:
    sys.setprofile(None)
    rows=[]
    for owned in objects:
        process=getattr(owned,'process',None)
        if process is None:continue
        try:
            url=getattr(getattr(owned,'rpc',None),'url',getattr(owned,'url',''))
            port=urlsplit(url).port
            try:os.killpg(process.pid,0);group_absent=False
            except ProcessLookupError:group_absent=True
            except PermissionError:group_absent=False
            with socket.socket() as sock:
                sock.settimeout(.2);port_closed=port is not None and sock.connect_ex(('127.0.0.1',port))!=0
            rows.append({'kind':type(owned).__name__,'pid':process.pid,'port':port,'owner_reaped':process.poll() is not None,'returncode':process.returncode,'group_absent':group_absent,'port_closed':port_closed,'pipes_closed':all(s is None or s.closed for s in (process.stdin,process.stdout,process.stderr)), 'stats':getattr(owned,'stats',None)})
        except Exception:secondary('terminal_owner_probe_failed')
    try:atomic('child-terminal.json',{'cli_code':code,'primary':primary,'command_seconds':time.monotonic()-started,'passive_profile_only':True,'owned':rows,'telemetry_errors':telemetry_errors})
    except Exception:secondary('terminal_record_failed')
raise SystemExit(code if code is not None else 1)
