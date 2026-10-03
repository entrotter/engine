"""Finite privacy-safe CI diagnostics; stdlib processes, never a Docker proof."""
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from entrotter_engine.evm import ExecutionError
from entrotter_engine.rpc import RPCError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trusted_diagnostic', ROOT/'tests_isolated/diagnose_trace_worker.py')
diagnostic = importlib.util.module_from_spec(spec); sys.modules[spec.name]=diagnostic; spec.loader.exec_module(diagnostic)
SECRET = 'private-provider-credential-do-not-output'
PLAN = json.loads((ROOT/'tests/data/canonical-mainnet-prefix.json').read_text())


def response(request_id='0'*64):
    return {'diagnostic_version':'0.1.0','request_id':request_id,'status':'failed',
        'last':{'phase':'source_fetch','branch':'none','method':'eth_chainId','transport':'upstream'},
        'checkpoints':[],'dropped_checkpoints':0,
        'error':{'category':'rpc_error','types':['rpc_error'],'ssl_verify_code':None,'http_status':None},
        'baseline_verified':None,'protocol_verified':False,'candidate_statuses':[],
        'authoritative_default_gate':False,'observed_input_count':0,'observer_rows':[],
        'discarded_observer_rows':0,'observer_errors':[]}


class DiagnosticPrivacyTests(unittest.TestCase):
    def test_error_chain_retains_only_categories_and_integer_codes(self):
        certificate = ssl.SSLCertVerificationError(SECRET)
        certificate.verify_code = 20
        certificate.verify_message = SECRET
        error = RPCError(SECRET); error.__context__ = URLError(certificate)
        result = diagnostic.error_summary(error)
        self.assertEqual(result['category'], 'ssl_certificate')
        self.assertEqual(result['ssl_verify_code'], 20)
        self.assertEqual(result['types'], ['rpc_error', 'url_error', 'ssl_certificate'])
        http = diagnostic.error_summary(HTTPError('https://'+SECRET, 429, SECRET, None, None))
        self.assertEqual(http['http_status'], 429)
        self.assertNotIn(SECRET, json.dumps([result,http]))

    def test_unknown_names_messages_cycles_and_deep_chains_are_bounded(self):
        custom = type(SECRET, (RuntimeError,), {'__str__':lambda self: (_ for _ in ()).throw(AssertionError())})
        error = custom(SECRET); error.__context__ = error
        self.assertEqual(diagnostic.error_summary(error)['types'], ['other'])
        for _ in range(100):
            outer = RuntimeError(SECRET); outer.__context__ = error; error = outer
        result = diagnostic.error_summary(error)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertLess(len(json.dumps(result)), 300)

    def test_numeric_error_codes_are_strict_and_range_limited(self):
        for code in [True, SECRET, -1, 65536]:
            error = ssl.SSLCertVerificationError(SECRET); error.verify_code=code
            self.assertIsNone(diagnostic.error_summary(error)['ssl_verify_code'])

    def test_nested_error_category_does_not_require_optional_numeric_code(self):
        certificate=ssl.SSLCertVerificationError(SECRET)
        error=RPCError(SECRET);error.__context__=URLError(certificate)
        result=diagnostic.error_summary(error)
        self.assertEqual(result['category'],'ssl_certificate')
        self.assertIsNone(result['ssl_verify_code'])
        error.__context__=HTTPError('https://'+SECRET,SECRET,SECRET,None,None)
        result=diagnostic.error_summary(error)
        self.assertEqual(result['category'],'http_error')
        self.assertIsNone(result['http_status'])

    def test_response_rejects_unbound_or_extra_dynamic_fields(self):
        valid = response(); self.assertEqual(diagnostic.validate_response(valid,'0'*64), valid)
        candidates=[]
        row=deepcopy(valid);row['request_id']='1'*64;candidates.append(row)
        row=deepcopy(valid);row['url']=SECRET;candidates.append(row)
        row=deepcopy(valid);row['last']['method']=SECRET;candidates.append(row)
        row=deepcopy(valid);row['error']['types']=[SECRET];candidates.append(row)
        row=deepcopy(valid);row['error']['ssl_verify_code']=True;candidates.append(row)
        row=deepcopy(valid);row['checkpoints']=[valid['last']]*33;candidates.append(row)
        row=deepcopy(valid);row['authoritative_default_gate']=True;candidates.append(row)
        for candidate in candidates:
            with self.subTest(candidate=list(candidate)), self.assertRaises(ValueError):
                diagnostic.validate_response(candidate,'0'*64)

    def test_fixed_image_program_compiles_with_unchanged_shared_protocol_budget(self):
        program=diagnostic.program();compile(program,'trusted-image-diagnostic','exec')
        self.assertIn('envelope = execute_request(raw)', program)
        self.assertNotIn('run_trace_native(', program)
        self.assertEqual(diagnostic.HOST_TIMEOUT,190)

    def test_embedded_program_executes_invalid_input_with_finite_failure_json(self):
        environment = dict(os.environ, PYTHONPATH=str(ROOT/'src'))
        for payload in (b'', b'{}', b'x'*262145):
            with self.subTest(size=len(payload)):
                completed = subprocess.run([sys.executable, '-c', diagnostic.program()],
                    input=payload, capture_output=True, env=environment, timeout=5)
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, b'')
                self.assertLessEqual(len(completed.stdout), diagnostic.MAX_OUTPUT)
                result = diagnostic.validate_response(json.loads(completed.stdout), sha256(payload).hexdigest())
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['error']['category'], 'value_error')
                self.assertEqual(result['last']['phase'], 'input_validation')
                self.assertFalse(result['authoritative_default_gate'])


class DiagnosticHostTests(unittest.TestCase):
    def run_mock_client(self, code, *, timeout=2, stop_error=None, cleanup_error=None, wait_error=None):
        real_popen=subprocess.Popen
        processes=[]; launches=[]; owners=[]
        def launch(command, **kwargs):
            launches.append(command)
            process=real_popen([sys.executable,'-c',code],**kwargs);processes.append(process)
            if wait_error:
                original_wait=process.wait; calls=0
                def wait(*args,**kw):
                    nonlocal calls
                    calls+=1
                    if calls==2: raise wait_error
                    return original_wait(*args,**kw)
                process.wait=wait
            return process
        def cleanup(prefix,owner):
            owners.append(owner)
            if cleanup_error: raise cleanup_error
        with patch.object(diagnostic.isolated,'client',return_value=nullcontext(['docker'])), \
             patch.object(diagnostic.isolated,'verify_daemon') as verify, \
             patch.object(diagnostic.isolated,'_slot',return_value=None), \
             patch.object(diagnostic.isolated,'_cleanup',side_effect=cleanup), \
             patch.object(diagnostic.subprocess,'Popen',side_effect=launch), \
             patch.dict(os.environ,{'ENTROTTER_WORKER_IMAGE':'sha256:'+'42'*32}), \
             patch.object(diagnostic,'HOST_TIMEOUT',timeout):
            if stop_error:
                with patch.object(diagnostic.os,'killpg',side_effect=stop_error):
                    result=diagnostic.run_diagnostic(PLAN)
            else: result=diagnostic.run_diagnostic(PLAN)
        verify.assert_called_once();self.assertEqual(len(owners),1)
        cleanup_summary=json.dumps({key:result.get(key) for key in
            ('host_error','cleanup_error','docker_exit_code','cleanup_verified')},sort_keys=True)
        for process in processes:
            try:
                self.assertTrue(process.stdout.closed,'Diagnostic output descriptor remains open; '+cleanup_summary)
                if result['cleanup_verified']:
                    self.assertIsNotNone(process.poll(),'Verified cleanup left owned client running; '+cleanup_summary)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
        self.assertNotIn(SECRET,json.dumps(result))
        return result,launches,owners

    def test_valid_bound_failure_uses_shared_slot_and_owner_cleanup(self):
        code="import json,sys;from hashlib import sha256;raw=sys.stdin.buffer.read();v="+repr(response())+";v['request_id']=sha256(raw).hexdigest();print(json.dumps(v))"
        result,launches,owners=self.run_mock_client(code)
        self.assertTrue(result['cleanup_verified']);self.assertIsNone(result['host_error'])
        self.assertEqual(result['worker']['status'],'failed')
        args=launches[0]
        self.assertEqual(args[args.index('--name')+1],diagnostic.isolated.WORKER_NAME)
        self.assertIn(diagnostic.isolated.OWNER_LABEL+'='+owners[0],args)
        for flag in ['--cpus=1','--memory=512m','--memory-swap=512m','--pids-limit=128',
                     '--read-only','--network=bridge','--cap-drop=ALL','--security-opt=no-new-privileges=true','--user=65534:65534']:
            self.assertIn(flag,args)
        self.assertEqual(args[-1],diagnostic.program())

    def test_invalid_or_unbound_stdout_is_not_copied_to_artifact(self):
        for text in [SECRET,json.dumps(response())]:
            result,_,_=self.run_mock_client('print('+repr(text)+')')
            self.assertIsNone(result['worker']);self.assertEqual(result['host_error']['category'],'value_error')
            self.assertTrue(result['cleanup_verified'])

    def test_output_limit_stops_client_and_attempts_owner_cleanup(self):
        result,_,_=self.run_mock_client("import os;os.write(1,b'x'*32768)")
        self.assertIsNone(result['worker']);self.assertEqual(result['host_error']['category'],'value_error')
        self.assertTrue(result['cleanup_verified'],json.dumps({key:result.get(key) for key in
            ('host_error','cleanup_error','docker_exit_code','cleanup_verified')},sort_keys=True))

    def test_output_limit_kills_live_client_and_reaps_owned_process(self):
        result,_,_=self.run_mock_client("import os,time;os.write(1,b'x'*32768);time.sleep(30)")
        self.assertIsNone(result['worker']);self.assertEqual(result['host_error']['category'],'value_error')
        self.assertTrue(result['cleanup_verified'],json.dumps({key:result.get(key) for key in
            ('host_error','cleanup_error','docker_exit_code','cleanup_verified')},sort_keys=True))

    def test_false_cleanup_verification_fails_and_still_rescues_owned_client(self):
        real_popen=subprocess.Popen;original=diagnostic.run_diagnostic;processes=[]
        def spawn(*args,**kwargs):
            process=real_popen(*args,**kwargs);processes.append(process);return process
        def falsely_verified(plan):
            result=original(plan);result['cleanup_verified']=True;return result
        with patch.object(diagnostic.subprocess,'Popen',side_effect=spawn), \
             patch.object(diagnostic,'run_diagnostic',side_effect=falsely_verified):
            with self.assertRaisesRegex(AssertionError,'Verified cleanup left owned client running'):
                self.run_mock_client("import os,time;os.write(1,b'x'*32768);time.sleep(30)",
                    stop_error=PermissionError(SECRET))
        self.assertEqual(len(processes),1)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)

    @unittest.skipUnless(hasattr(os,'fork'),'POSIX descendant-held pipe required')
    def test_descendant_held_stdout_timeout_kills_owned_session(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/'child.pid'
            code="import os,time;from pathlib import Path;pid=os.fork();\nif pid==0:\n Path("+repr(str(pidfile))+").write_text(str(os.getpid()));time.sleep(30)\n"
            result,_,_=self.run_mock_client(code,timeout=.4)
            self.assertEqual(result['host_error']['category'],'timeout')
            self.assertTrue(result['cleanup_verified'])
            pid=int(pidfile.read_text())
            # An adopted zombie is terminated; reaping by init is not owned here.
            state=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
            self.assertTrue(not state or state.startswith('Z'),state)

    def test_client_stop_failure_still_attempts_owner_cleanup(self):
        result,_,_=self.run_mock_client('print('+repr(SECRET)+')',stop_error=PermissionError(SECRET))
        self.assertEqual(result['host_error']['category'],'value_error')
        self.assertEqual(result['cleanup_error']['category'],'os_error')
        self.assertFalse(result['cleanup_verified'])

    def test_cleanup_failure_preserves_primary_error_without_private_text(self):
        result,_,_=self.run_mock_client('print('+repr(SECRET)+')',cleanup_error=ExecutionError(SECRET))
        self.assertEqual(result['host_error']['category'],'value_error')
        self.assertEqual(result['cleanup_error']['category'],'execution_error')
        self.assertFalse(result['cleanup_verified'])

    def test_client_wait_failure_closes_stdout_and_attempts_owner_cleanup(self):
        code="import json,sys;from hashlib import sha256;raw=sys.stdin.buffer.read();v="+repr(response())+";v['request_id']=sha256(raw).hexdigest();print(json.dumps(v))"
        result,_,_=self.run_mock_client(code,wait_error=subprocess.TimeoutExpired(SECRET,3))
        self.assertEqual(result['cleanup_error']['category'],'timeout')
        self.assertFalse(result['cleanup_verified'])

    def test_busy_slot_refuses_without_launch_or_foreign_cleanup(self):
        with patch.object(diagnostic.isolated,'client',return_value=nullcontext(['docker'])), \
             patch.object(diagnostic.isolated,'verify_daemon'), \
             patch.object(diagnostic.isolated,'_slot',return_value='42'*32), \
             patch.object(diagnostic.subprocess,'Popen') as launch, \
             patch.object(diagnostic.isolated,'_cleanup') as cleanup:
            with self.assertRaises(diagnostic.isolated.WorkerBusy):diagnostic.run_diagnostic(PLAN)
        launch.assert_not_called();cleanup.assert_not_called()


if __name__=='__main__':unittest.main()
