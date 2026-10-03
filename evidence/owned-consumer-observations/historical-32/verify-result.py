"""Verify complete original32 inputs, receipts, four raw views and actual closure."""
import hashlib,json,sys
from pathlib import Path
Q=Path(__file__).resolve().parent;W=Q.parents[1]
sys.path.insert(0,str(W/'src'))
from entrotter_engine.consumer_observations import load_observed_trace,verify_observed_trace
from entrotter_engine.trace import verify_trace
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
wrapper=load_observed_trace(Q/'observed-trace.json');r=wrapper['trace_report']
assert verify_observed_trace(wrapper) and verify_trace(r)
prior=read(W/'evidence/aave-consumer-price/native-006/report.json')
assert r['plan']==prior['plan']==read(Q/'plan.json')
assert r['source']==prior['source']
assert r['source']['block_transaction_count']==181 and len(r['source']['inputs'])==32
assert r['baseline_verified'] and wrapper['classification']['baseline_receipts_verified']
assert r['baseline']==prior['baseline'] and r['candidate']==prior['candidate']
for original,outcome in zip(r['source']['inputs'],r['baseline']['outcomes']):
    assert outcome['receipt']==original['original_receipt'] and outcome['status']=='executed' and not outcome['differing_fields']
executed=[x for x in r['candidate']['outcomes'] if x['status']=='executed']
assert len(executed)==31 and r['candidate']['outcomes'][12]['status']=='skipped'
for i,outcome in enumerate(r['candidate']['outcomes']):
    if i<12:assert not outcome['differing_fields']
    if i>12:
        assert set(outcome['differing_fields'])=={'transactionIndex','cumulativeGasUsed'}
        old=r['source']['inputs'][i]['original_receipt'];actual=outcome['receipt']
        assert int(actual['transactionIndex'],16)==int(old['transactionIndex'],16)-1
        assert int(actual['cumulativeGasUsed'],16)==int(old['cumulativeGasUsed'],16)-336752
expected=[('baseline','before',257082415000),('baseline','after',256292441874),('candidate','before',257082415000),('candidate','after',257082415000)]
assert len(wrapper['observations'])==4
prices=[]
for row,(branch,phase,price) in zip(wrapper['observations'],expected):
    assert (row['branch'],row['phase'])==(branch,phase) and row['errors']==[]
    consumer=int(row['raw']['price'],16)
    producer=int(row['raw']['latest_round_data'][2+64:2+128],16)
    assert consumer==producer==price
    assert int(row['raw']['base_currency'],16)==0 and int(row['raw']['base_unit'],16)==100000000
    prices.append({'branch':branch,'phase':phase,'consumer_price':consumer,'producer_answer':producer,'head':row['head'],'code_identities':row['code']})
c=wrapper['classification'];assert c['complete_price_views'] and not c['unproven_reasons'] and c['price_difference']==789973126
child=read(Q/'child-terminal.json');host=read(Q/'host-terminal.json')
assert child['cli_code']==host['code']==0 and host['cause']=='completed' and host['cli_reaped']
assert child['primary'] is None and not child['telemetry_errors'] and not host['host_cleanup_errors']
assert host['sources_unchanged'] and host['inputs_unchanged'] and r['runtime_seconds']<=150
assert len(child['owned'])==3 and [x['kind'] for x in child['owned']].count('AnvilSession')==2
for row in child['owned']:assert row['owner_reaped'] and row['returncode']==0 and row['group_absent'] and row['port_closed'] and row['pipes_closed'],row
assert len(host['owned_host_observations'])==3 and all(x['host_group_absent'] and x['host_port_closed'] for x in host['owned_host_observations'])
cache=next(x['stats'] for x in child['owned'] if x['kind']=='ParentCache')
(Q/'trace-report.json').write_text(json.dumps(r,indent=2)+'\n')
out={'status':'passed','head':read(Q/'readiness.json')['head'],'wrapper_artifact_id':wrapper['artifact_id'],'wrapper_sha256':sha(Q/'observed-trace.json'),'trace_artifact_id':r['artifact_id'],'trace_report_sha256':sha(Q/'trace-report.json'),'original_inputs':32,'full_block_inputs':181,'baseline_complete_receipts_equal':32,'candidate_executed':31,'skipped_index':12,'later_structural_receipt_differences':19,'consumer_raw_price_equals_producer_all4':True,'prices':prices,'classification':c,'replay_seconds':r['runtime_seconds'],'command_seconds':child['command_seconds'],'host_seconds':host['host_seconds'],'original_replay_cap_seconds':150,'cache':cache,'owned_three_groups_ports_pipes_closed':True,'evidence_sha256':{n:sha(Q/n) for n in ('readiness.json','plan.json','cli-child.py','run.py','stdout.log','stderr.log','child-terminal.json','host-terminal.json','owned-ledger.json')},'limits':['Read-only Aave price dependence; no signed consumer action/strategy/profit.','Native explicit mode, not CPU/RSS sandbox or default Docker32.','Partial32 of181, no fullblock/root/opcode proof or provider authentication.','Passive Python lifecycle profile records ownership; no runtime function replacement or extra RPC, timing not a speed benchmark.','Cache aggregate errors, if any, retain unknown cause.']}
(Q/'verified-result.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ('prices','evidence_sha256','limits')}))
