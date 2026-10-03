"""Actual no-network worker replay of public disposable synthetic signed inputs."""
import json
import os
from pathlib import Path
import unittest

import test_worker as harness
from entrotter_engine.trace import verify_trace

ROOT = Path(__file__).resolve().parents[1]


class BoundedCanonicalReplay(unittest.TestCase):
    probe = harness.IsolatedWorkerTests.probe

    @classmethod
    def setUpClass(cls):
        cls.image = os.environ['ENTROTTER_WORKER_IMAGE']

    def test_actual_observed_entrypoint_replays_and_preserves_unproven_prices(self):
        from entrotter_engine.consumer_observations import verify_observed_trace

        fixture = json.loads((ROOT / 'tests/data/canonical-local-inputs.json').read_text())
        code = '''import io,json,os,socket
from unittest.mock import patch
from urllib.parse import urlsplit
from entrotter_engine.evm import AnvilSession
from entrotter_engine.rpc import RPC
from entrotter_engine.worker_protocol import encode_observed_trace_request
from entrotter_engine._isolated_worker import main
fixture=FIXTURE
nodes=[]
def replay_node(*args,**kwargs):
    node=AnvilSession(*args,**kwargs);nodes.append(node);return node
with AnvilSession(trace=True) as source:
    rpc=source.rpc
    setup=RPC(rpc.url,local=True)
    setup.call('anvil_setBalance',[fixture['actor'],hex(int(fixture['actor_balance_wei']))])
    for address,bytecode in fixture['local_contracts'].items():setup.call('anvil_setCode',[address,bytecode])
    rpc.call('evm_setNextBlockTimestamp',[fixture['parent_timestamp']]);rpc.call('evm_mine')
    for raw in fixture['raw_transactions']:rpc.call('eth_sendRawTransaction',[raw])
    rpc.call('evm_setNextBlockTimestamp',[fixture['target_timestamp']]);rpc.call('evm_mine')
    block=rpc.call('eth_getBlockByNumber',['latest',False])
    plan={'trace_version':'0.1.0','source':{'chain_id':1,'block_number':int(block['number'],16),'block_hash':block['hash']},'through_index':2,'skip_indices':[0]}
    raw=encode_observed_trace_request(plan)
    os.environ['ENTROTTER_RPC_URL']=rpc.url
    output=io.BytesIO()
    stdout=io.TextIOWrapper(output,encoding='utf-8')
    with patch('sys.stdin',io.TextIOWrapper(io.BytesIO(raw))),patch('sys.stdout',stdout),patch('entrotter_engine.trace.AnvilSession',side_effect=replay_node):
        status=main()
    stdout.flush()
    result=json.loads(output.getvalue())
    if status!=0:raise RuntimeError('Observed entrypoint failed')
for node in nodes:
    assert node.process.poll() is not None
    with socket.socket() as connection:
        connection.settimeout(.2)
        assert connection.connect_ex(('127.0.0.1',urlsplit(node.rpc.url).port))!=0
    try:os.killpg(node.process.pid,0)
    except ProcessLookupError:pass
    else:raise AssertionError('Owned group remains')
print(json.dumps({'envelope':result,'request_id':__import__('hashlib').sha256(raw).hexdigest(),'closed_nodes':len(nodes)}))
'''.replace('FIXTURE', repr(fixture))
        result, _ = self.probe(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['envelope']['request_id'], output['request_id'])
        self.assertEqual(output['closed_nodes'], 2)
        observed = output['envelope']['report']
        self.assertTrue(verify_observed_trace(observed))
        self.assertTrue(observed['trace_report']['baseline_verified'])
        self.assertEqual([o['status'] for o in observed['trace_report']['candidate']['outcomes']], ['skipped', 'nonce_conflict', 'nonce_conflict'])
        self.assertEqual(len(observed['observations']), 4)
        self.assertFalse(observed['classification']['complete_price_views'])
        self.assertIsNone(observed['classification']['price_difference'])

    def test_actual_worker_reconstructs_original_receipts_and_nonce_conflicts(self):
        fixture=json.loads((ROOT/'tests/data/canonical-local-inputs.json').read_text())
        code='''import json,os
from entrotter_engine.evm import AnvilSession
from entrotter_engine.rpc import RPC
from entrotter_engine.worker_protocol import encode_trace_request,execute_request
fixture=FIXTURE
with AnvilSession(trace=True) as source:
    rpc=source.rpc
    setup=RPC(rpc.url,local=True)
    setup.call('anvil_setBalance',[fixture['actor'],hex(int(fixture['actor_balance_wei']))])
    for address,bytecode in fixture['local_contracts'].items(): setup.call('anvil_setCode',[address,bytecode])
    rpc.call('evm_setNextBlockTimestamp',[fixture['parent_timestamp']]);rpc.call('evm_mine')
    for raw in fixture['raw_transactions']:rpc.call('eth_sendRawTransaction',[raw])
    rpc.call('evm_setNextBlockTimestamp',[fixture['target_timestamp']]);rpc.call('evm_mine')
    block=rpc.call('eth_getBlockByNumber',['latest',False])
    plan={'trace_version':'0.1.0','source':{'chain_id':1,'block_number':int(block['number'],16),'block_hash':block['hash']},'through_index':2,'skip_indices':[0]}
    os.environ['ENTROTTER_RPC_URL']=rpc.url
    result=execute_request(encode_trace_request(plan))
print(json.dumps(result))
'''.replace('FIXTURE',repr(fixture))
        result,_=self.probe(code)
        self.assertEqual(result.returncode,0,result.stderr)
        envelope=json.loads(result.stdout);report=envelope['report']
        self.assertTrue(verify_trace(report))
        self.assertTrue(report['baseline_verified'])
        self.assertEqual([r['receipt']['status'] for r in report['baseline']['outcomes']],['0x1','0x0','0x1'])
        self.assertEqual([r['status'] for r in report['candidate']['outcomes']],['skipped','nonce_conflict','nonce_conflict'])
        self.assertTrue(all(not r['differing_fields'] for r in report['baseline']['outcomes']))

    def test_actual_image_protocol_retains_same_block_funding_and_unmined_omission(self):
        fixture=json.loads((ROOT/'tests/data/canonical-local-funding-inputs.json').read_text())
        code='''import json,os,subprocess
from unittest.mock import patch
from entrotter_engine.evm import AnvilSession
from entrotter_engine.worker_protocol import encode_trace_request,execute_request
fixture=FIXTURE
original_popen=subprocess.Popen
def fixture_start(command,*args,**kwargs):
    return original_popen([*command,'--fund-accounts',fixture['actor']+':'+fixture['actor_balance_eth']],*args,**kwargs)
source=AnvilSession(trace=True)
# Only the original synthetic source receives a startup allocation. Replay
# nodes fork its pinned parent without state overrides or signing material.
with patch('entrotter_engine.evm.subprocess.Popen',side_effect=fixture_start):
    source.__enter__()
try:
    rpc=source.rpc
    rpc.call('evm_setNextBlockTimestamp',[fixture['target_timestamp']])
    rpc.call('evm_setBlockGasLimit',['0xc350'])
    rpc.call('anvil_setNextBlockBaseFeePerGas',['0x3b9aca00'])
    rpc.call('anvil_setCoinbase',['0x'+'42'*20])
    rpc.call('anvil_setNextBlockPrevRandao',['0x'+'11'*32])
    for raw in fixture['raw_transactions']:rpc.call('eth_sendRawTransaction',[raw])
    rpc.call('evm_mine')
    block=rpc.call('eth_getBlockByNumber',['latest',False])
    if len(block['transactions'])!=2:raise RuntimeError('Original funding block did not execute')
    plan={'trace_version':'0.1.0','source':{'chain_id':1,'block_number':int(block['number'],16),'block_hash':block['hash']},'through_index':1,'skip_indices':[0]}
    os.environ['ENTROTTER_RPC_URL']=rpc.url
    result=execute_request(encode_trace_request(plan))
finally:
    source.__exit__(None,None,None)
print(json.dumps(result))
'''.replace('FIXTURE',repr(fixture))
        # This executes the worker protocol in the bounded image. It does not
        # replace the separate host default-client/lifecycle integration gates.
        result,_=self.probe(code)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)['report']
        self.assertTrue(verify_trace(report))
        self.assertTrue(report['baseline_verified'])
        baseline=report['baseline']['outcomes']
        self.assertEqual([o['receipt']['status'] for o in baseline],['0x1','0x1'])
        self.assertEqual([int(o['receipt']['gasUsed'],16) for o in baseline],[21000,21000])
        self.assertEqual([int(o['receipt']['cumulativeGasUsed'],16) for o in baseline],[21000,42000])
        self.assertEqual([o['receipt']['transactionIndex'] for o in baseline],['0x0','0x1'])
        self.assertTrue(all(not o['differing_fields'] for o in baseline))
        candidate=report['candidate']['outcomes']
        self.assertEqual([o['status'] for o in candidate],['skipped','not_mined'])
        self.assertNotIn('receipt',candidate[1])
        self.assertFalse(report['candidate']['matches_original_receipts'])

    def test_actual_image_protocol_replays_signed_oracle_update_and_adverse_omission(self):
        fixture=json.loads((ROOT/'tests/data/canonical-local-oracle-inputs.json').read_text())
        code='''import json,os,socket,subprocess
from unittest.mock import patch
from urllib.parse import urlsplit
from entrotter_engine.evm import AnvilSession
from entrotter_engine.worker_protocol import encode_trace_request,execute_request
fixture=FIXTURE
original_popen=subprocess.Popen
def fixture_start(command,*args,**kwargs):
    return original_popen([*command,'--fund-accounts',*[a+':'+fixture['actor_balance_eth'] for a in fixture['actors']]],*args,**kwargs)
source=AnvilSession(trace=True)
with patch('entrotter_engine.evm.subprocess.Popen',side_effect=fixture_start):
    source.__enter__()
nodes=[source]
def replay_node(*args,**kwargs):
    node=AnvilSession(*args,**kwargs);nodes.append(node);return node
try:
    rpc=source.rpc
    for raw,address,runtime in zip(fixture['deployment_transactions'],[fixture['oracle'],fixture['consumer']],[fixture['oracle_runtime'],fixture['consumer_runtime']]):
        h=rpc.call('eth_sendRawTransaction',[raw]);rpc.call('evm_mine')
        receipt=rpc.call('eth_getTransactionReceipt',[h])
        assert receipt['status']=='0x1' and receipt['contractAddress']==address
        assert rpc.call('eth_getCode',[address,'latest'])==runtime
    assert int(rpc.call('eth_call',[{'to':fixture['oracle'],'data':'0x'},'latest']),16)==10
    for raw in fixture['raw_transactions']:rpc.call('eth_sendRawTransaction',[raw])
    for method,value in [('evm_setNextBlockTimestamp',fixture['target_timestamp']),('evm_setBlockGasLimit',hex(fixture['gas_limit'])),('anvil_setNextBlockBaseFeePerGas',hex(fixture['base_fee'])),('anvil_setCoinbase',fixture['coinbase']),('anvil_setNextBlockPrevRandao',fixture['prevrandao'])]:rpc.call(method,[value])
    rpc.call('evm_mine')
    block=rpc.call('eth_getBlockByNumber',['latest',False]);assert len(block['transactions'])==2
    plan={'trace_version':'0.1.0','source':{'chain_id':1,'block_number':int(block['number'],16),'block_hash':block['hash']},'through_index':1,'skip_indices':[0]}
    os.environ['ENTROTTER_RPC_URL']=rpc.url
    with patch('entrotter_engine.trace.AnvilSession',side_effect=replay_node):
        result=execute_request(encode_trace_request(plan))
    assert int(rpc.call('eth_call',[{'to':fixture['oracle'],'data':'0x'},'latest']),16)==20
finally:
    source.__exit__(None,None,None)
    for node in nodes:
        assert node.process.poll()==0
        with socket.socket() as sock:
            sock.settimeout(.2)
            assert sock.connect_ex(('127.0.0.1',urlsplit(node.rpc.url).port))!=0
print(json.dumps(result))
'''.replace('FIXTURE',repr(fixture))
        # Direct bounded image/protocol proof; host default dispatch/lifecycle
        # and historical provider gates remain independently required.
        result,_=self.probe(code)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)['report']
        self.assertTrue(verify_trace(report));self.assertTrue(report['baseline_verified'])
        baseline=report['baseline']['outcomes']
        self.assertEqual([o['receipt']['status'] for o in baseline],['0x1','0x1'])
        self.assertEqual([int(o['receipt']['gasUsed'],16) for o in baseline],[26167,26438])
        self.assertEqual([int(o['receipt']['cumulativeGasUsed'],16) for o in baseline],[26167,52605])
        self.assertEqual([o['differing_fields'] for o in baseline],[[],[]])
        self.assertEqual(baseline[1]['receipt']['logs'][0]['data'],'0x'+(20).to_bytes(32,'big').hex())
        candidate=report['candidate']['outcomes']
        self.assertEqual([o['status'] for o in candidate],['skipped','executed'])
        self.assertEqual(candidate[1]['hash'],report['source']['inputs'][1]['hash'])
        self.assertEqual(candidate[1]['receipt']['status'],'0x0')
        self.assertEqual(int(candidate[1]['receipt']['gasUsed'],16),25808)
        self.assertEqual(candidate[1]['receipt']['logs'],[])
        self.assertEqual(set(candidate[1]['differing_fields']),{'status','gasUsed','cumulativeGasUsed','transactionIndex','logsBloom','logs'})
        self.assertFalse(report['candidate']['matches_original_receipts'])
