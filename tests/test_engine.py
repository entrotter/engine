from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch, MagicMock
from entrotter_engine.runner import run_native as run
from entrotter_engine.artifact import seal, verify, canonical
from entrotter_engine.models import validate, ValidationError, number
from entrotter_engine.rpc import RPC, RPCError
from entrotter_engine.evm import resolve_source, AnvilSession, ExecutionError
from entrotter_engine.fixture import Observation, CircuitBreaker

DATA = Path(__file__).parent / 'data'
def fixture(): return json.loads((DATA/'fixture.json').read_text())
def evm(): return json.loads((DATA/'local.json').read_text())
def fork(): return json.loads((DATA/'fork.json').read_text())

class FixtureTests(unittest.TestCase):
    def test_deterministic(self): self.assertEqual(run(fixture()), run(fixture()))
    def test_integrity(self): self.assertTrue(verify(run(fixture())))
    def test_tamper(self):
        r=run(fixture());r['candidate']['metrics']['final_equity']='123';self.assertFalse(verify(r))
    def test_order_independent_hash(self): self.assertEqual(seal({'a':1,'b':2}),seal({'b':2,'a':1}))
    def test_missing_hash(self): self.assertFalse(verify({'schema_version':'0.1.0'}))
    def test_wrong_version(self): self.assertFalse(verify(seal({'schema_version':'7'})))
    def test_nonfinite_hash(self): self.assertFalse(verify({'schema_version':'0.1.0','artifact_id':'a'*64,'x':float('nan')}))
    def test_hold_value(self): self.assertEqual(run(fixture())['baseline']['metrics']['final_equity'], '5800')
    def test_cost_accounting(self):
        r=run(fixture());self.assertEqual(Decimal(r['candidate']['metrics']['final_equity']),Decimal('86')*100*Decimal('.998')*Decimal('.997'))
    def test_breaker_sells_once(self): self.assertEqual(run(fixture())['candidate']['metrics']['trades'],1)
    def test_sell_after_observed_drop(self):
        actions=[r['action'] for r in run(fixture())['candidate']['trace']];self.assertEqual(actions.index('sell_all'),4)
    def test_no_future_lookahead(self):
        a=fixture();b=deepcopy(a);b['market']['prices'][6:]=['1000','2000','3000']
        self.assertEqual(run(a)['candidate']['trace'][:6],run(b)['candidate']['trace'][:6])
    def test_shorter_prefix_same_actions(self):
        a=fixture();b=deepcopy(a);b['market']['prices']=b['market']['prices'][:5]
        self.assertEqual(run(a)['candidate']['trace'][:5],run(b)['candidate']['trace'])
    def test_recovery_can_lose(self):
        f=fixture();f['market']['prices']=['100','80','200'];r=run(f)
        self.assertLess(Decimal(r['comparison']['final_equity_delta']),0)
    def test_same_policy_same_result(self):
        f=fixture();f['candidate']={'type':'hold'};r=run(f);self.assertEqual(r['baseline'],r['candidate'])
    def test_drawdown(self):
        f=fixture();f['market']['prices']=['100','50','75'];r=run(f)
        self.assertEqual(Decimal(r['baseline']['metrics']['max_drawdown_pct']),50)
    def test_flat_has_zero_drawdown(self):
        f=fixture();f['market']['prices']=['100','100'];self.assertEqual(Decimal(run(f)['baseline']['metrics']['max_drawdown_pct']),0)
    def test_zero_units_cash_only(self):
        f=fixture();f['market']['initial_units']='0';f['market']['initial_cash']='500'
        self.assertEqual(run(f)['candidate']['metrics']['final_equity'],'500')
    def test_input_unchanged(self):
        f=fixture();copy=deepcopy(f);run(f);self.assertEqual(f,copy)
    def test_policy_only_receives_observation(self):
        o=Observation(3,Decimal('80'),Decimal('100'),Decimal('0'),Decimal('1'))
        self.assertEqual(CircuitBreaker('.1').observe(o),'sell_all')
        self.assertFalse(hasattr(o,'future_prices'))
    def test_assumptions_visible(self): self.assertIn('Synthetic',run(fixture())['assumptions'][0])

class ValidationTests(unittest.TestCase):
    def test_float_money_rejected(self):
        f=fixture();f['market']['initial_cash']=1.1
        with self.assertRaises(ValidationError): validate(f)
    def test_negative_money(self):
        with self.assertRaises(ValidationError): number('-1','x')
    def test_nan(self):
        with self.assertRaises(ValidationError): number('NaN','x')
    def test_infinity(self):
        with self.assertRaises(ValidationError): number('Infinity','x')
    def test_precision_limit(self):
        with self.assertRaises(ValidationError): number('0.0000000000000000001','x')
    def test_zero_price(self):
        f=fixture();f['market']['prices'][0]='0'
        with self.assertRaises(ValidationError): validate(f)
    def test_empty_wallet(self):
        f=fixture();f['market']['initial_units']='0'
        with self.assertRaises(ValidationError): validate(f)
    def test_unknown_policy(self):
        f=fixture();f['candidate']={'type':'shell'}
        with self.assertRaises(ValidationError): validate(f)
    def test_unknown_field(self):
        f=fixture();f['command']='rm -rf /'
        with self.assertRaises(ValidationError): validate(f)
    def test_missing_provenance(self):
        f=fixture();del f['provenance']
        with self.assertRaises(ValidationError): validate(f)
    def test_fake_historical_fixture(self):
        f=fixture();f['provenance']['kind']='historical'
        with self.assertRaises(ValidationError): validate(f)
    def test_bool_not_integer(self):
        f=fixture();f['market']['fee_bps']=True
        with self.assertRaises(ValidationError): validate(f)
    def test_fixture_rejects_evm_fields(self):
        f=fixture();f['actor']='0x'+'1'*40
        with self.assertRaises(ValidationError): validate(f)
    def test_local_scenario(self): self.assertEqual(validate(evm())['mode'],'evm-local')
    def test_fork_scenario(self): self.assertEqual(validate(fork())['mode'],'evm-fork')
    def test_bad_address(self):
        f=evm();f['actor']='not-an-address'
        with self.assertRaises(ValidationError): validate(f)
    def test_target_allowlist(self):
        f=evm();f['steps'][0]['candidate']['to']='0x'+'f'*40
        with self.assertRaises(ValidationError): validate(f)
    def test_action_cannot_supply_from(self):
        f=evm();f['steps'][0]['candidate']['from']=f['actor']
        with self.assertRaises(ValidationError): validate(f)
    def test_oversized_gas(self):
        f=evm();f['steps'][0]['candidate']['gas']=10000000
        with self.assertRaises(ValidationError): validate(f)
    def test_odd_hex(self):
        f=evm();f['steps'][0]['candidate']['data']='0xabc'
        with self.assertRaises(ValidationError): validate(f)
    def test_fork_rejects_code_override(self):
        f=fork();f['local_contracts']={f['allowed_targets'][0]:'0x00'}
        with self.assertRaises(ValidationError): validate(f)
    def test_decimal_wei_rejected(self):
        f=evm();f['actor_balance_wei']='1.2'
        with self.assertRaises(ValidationError): validate(f)
    def test_excessive_steps(self):
        f=evm();f['steps']*=20
        with self.assertRaises(ValidationError): validate(f)

class SafetyTests(unittest.TestCase):
    def test_no_upstream_transaction_submission(self):
        rpc=RPC('https://rpc.example.test')
        for method in ['eth_sendTransaction','eth_sendRawTransaction','anvil_setBalance','debug_traceCall']:
            with self.subTest(method=method),self.assertRaises(RPCError): rpc.call(method,[])
    def test_local_client_rejects_remote(self):
        with self.assertRaises(RPCError): RPC('https://rpc.example.test',local=True)
    def test_local_cannot_submit_raw(self):
        with self.assertRaises(RPCError): RPC('http://127.0.0.1:54321',local=True).call('eth_sendRawTransaction',[])
    def test_no_url_userinfo(self):
        with self.assertRaises(RPCError): RPC('https://secret:password@rpc.example.test')
    def test_missing_rpc_not_fake_success(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ExecutionError): resolve_source(fork())
    def test_missing_anvil_not_fake_success(self):
        with patch('entrotter_engine.evm.shutil.which',return_value=None),self.assertRaises(ExecutionError):
            with AnvilSession(): pass
    def test_source_chain_mismatch(self):
        with patch.dict(os.environ,{'ENTROTTER_RPC_URL':'https://secret.invalid'}),patch('entrotter_engine.evm.RPC') as mock:
            mock.return_value.call.return_value='0x2'
            with self.assertRaises(ExecutionError): resolve_source(fork())
    def test_pinned_block_mismatch(self):
        f=fork();f['source']['block_hash']='0x'+'a'*64
        with patch.dict(os.environ,{'ENTROTTER_RPC_URL':'https://secret.invalid'}),patch('entrotter_engine.evm.RPC') as mock:
            mock.return_value.call.side_effect=['0x1',{'number':hex(19000000),'hash':'0x'+'b'*64,'timestamp':'0x1'}]
            with self.assertRaises(ExecutionError): resolve_source(f)
    def test_resolved_source_excludes_rpc_secret(self):
        with patch.dict(os.environ,{'ENTROTTER_RPC_URL':'https://secret.invalid/api-key'}),patch('entrotter_engine.evm.RPC') as mock:
            mock.return_value.call.side_effect=['0x1',{'number':hex(19000000),'hash':'0x'+'a'*64,'timestamp':'0x1'}]
            source,url=resolve_source(fork());self.assertNotIn('secret',json.dumps(source))

class ActualAnvilTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('anvil'),'Anvil binary unavailable; genuine EVM execution not tested')
    def test_native_transfer_and_revert(self):
        r=run(evm());self.assertTrue(verify(r))
        self.assertEqual(r['candidate']['trace'][0]['status'],'success')
        self.assertEqual(r['candidate']['trace'][1]['status'],'reverted')
        self.assertEqual(r['candidate']['metrics']['reverted_transactions'],1)
        self.assertEqual(r['baseline']['metrics']['final_balance_wei'],'10000000000000000000')
        self.assertLess(int(r['candidate']['metrics']['final_balance_wei']),9000000000000000000)

if __name__=='__main__': unittest.main()
