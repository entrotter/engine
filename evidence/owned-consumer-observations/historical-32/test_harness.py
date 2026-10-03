"""Offline fault controls; no archive, product replay or substitute result."""
import ast,json,os,signal,subprocess,sys,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
class FaultControls(unittest.TestCase):
    def namespace(self):
        tree=ast.parse((HERE/'cli-child.py').read_text())
        prefix=tree.body[:next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='started' for t in n.targets))]
        ns={'__file__':str(HERE/'cli-child.py')};exec(compile(ast.Module(prefix,[]),'profile-source','exec'),ns)
        return ns
    def frame(self,obj):
        return types.SimpleNamespace(f_code=types.SimpleNamespace(co_name='__enter__',co_filename='/src/entrotter_engine/parent_cache.py'),f_locals={'self':obj})
    def test_telemetry_io_failure_does_not_replace_return(self):
        ns=self.namespace();owned=types.SimpleNamespace(process=types.SimpleNamespace(pid=123),url='http://127.0.0.1:1')
        def fail(*a):raise PermissionError()
        ns['atomic']=fail
        self.assertIsNone(ns['profile'](self.frame(owned),'return',owned))
        self.assertEqual(ns['telemetry_errors'],['lifecycle_record_failed'])
        self.assertIs(ns['objects'][0],owned)
    def test_telemetry_invalid_port_remains_secondary(self):
        ns=self.namespace();owned=types.SimpleNamespace(process=types.SimpleNamespace(pid=123),url='http://127.0.0.1:bad')
        self.assertIsNone(ns['profile'](self.frame(owned),'return',owned))
        self.assertEqual(ns['telemetry_errors'],['lifecycle_record_failed'])
    def test_telemetry_baseexception_stop_propagates(self):
        ns=self.namespace();owned=types.SimpleNamespace(process=types.SimpleNamespace(pid=123),url='http://127.0.0.1:1')
        def stop(*a):raise KeyboardInterrupt()
        ns['atomic']=stop
        with self.assertRaises(KeyboardInterrupt):ns['profile'](self.frame(owned),'return',owned)
    def host_fault(self,timeout=False,race=False):
        source=(HERE/'run.py').read_text();tree=ast.parse(source)
        body=tree.body[next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='started' for t in n.targets)):]
        with tempfile.TemporaryDirectory() as t:
            q=Path(t);process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            original_wait=process.wait;calls=0
            def wait(*a,**k):
                nonlocal calls;calls+=1
                if calls==1:
                    if timeout:raise subprocess.TimeoutExpired('owned',190)
                    raise KeyboardInterrupt()
                return original_wait(*a,**k)
            original_kill=os.killpg
            def raced(pid,sig):
                original_kill(pid,sig)
                if race:raise ProcessLookupError()
            ns={'HERE':q,'ROOT':q,'sha':lambda p:None,'readiness':{'sources':{},'inputs':{}},'env':dict(os.environ),'sys':sys,'os':os,'signal':signal,'socket':__import__('socket'),'subprocess':subprocess,'time':time,'json':json}
            try:
                with patch.object(subprocess,'Popen',return_value=process),patch.object(process,'wait',side_effect=wait),patch.object(os,'killpg',side_effect=raced):
                    with self.assertRaises(SystemExit) as stop:exec(compile(ast.Module(body,[]),'host-actual-ownership-source','exec'),ns)
                self.assertEqual(stop.exception.code,1)
                self.assertIsNotNone(process.poll());self.assertGreaterEqual(calls,2)
                result=json.loads((q/'host-terminal.json').read_text())
                self.assertEqual(result['cause'],'host_watchdog190s' if timeout else 'host_cancelled')
                self.assertTrue(result['cli_reaped']);self.assertFalse(result['host_cleanup_errors'])
                with self.assertRaises(ProcessLookupError):original_kill(process.pid,0)
            finally:
                if process.poll() is None:original_kill(process.pid,signal.SIGKILL)
                original_wait(timeout=5)
    def test_host_cancellation_reaps_actual_owned_child(self):self.host_fault()
    def test_host_deadline_exit_race_reaps_actual_owned_child(self):self.host_fault(timeout=True,race=True)
if __name__=='__main__':unittest.main(verbosity=2)
