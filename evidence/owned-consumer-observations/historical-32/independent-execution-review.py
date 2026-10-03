"""Offline review of one retained actual supported native CLI result."""
import hashlib
import json
from pathlib import Path
import re
import sys

Q = Path(__file__).resolve().parent
ROOT = Q.parents[1]
sys.path.insert(0, str(ROOT/'src'))
from entrotter_engine.consumer_observations import load_observed_trace, verify_observed_trace
from entrotter_engine.trace import verify_trace

hashes = {}
def digest(data): return hashlib.sha256(data).hexdigest()
def read(path):
    data=path.read_bytes(); hashes[str(path.relative_to(ROOT))]=digest(data); return data
def load(path): return json.loads(read(path))
def seal_id(report):
    body={k:v for k,v in report.items() if k!='artifact_id'}
    return digest(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode())
ready=load(Q/'readiness.json'); prelaunch=load(Q/'independent-prelaunch-final-review.json')
assert digest(read(Q/'readiness.json'))=='57d3359655a5964db816977d792085e26952c050a9e004a2a0ce613184152626'
assert digest(read(Q/'independent-prelaunch-final-review.json'))=='3df81f674f92639002321648d9ba63422e1d414c091f7ca7c35db3d15cdd3c84'
assert prelaunch['status']=='passed_no_remaining_actionable_prelaunch_findings'
assert len(ready['sources'])==31 and len(ready['inputs'])==5
for name,sha in ready['sources'].items(): assert digest(read(ROOT/name))==sha
for name,sha in ready['inputs'].items(): assert digest(read(Q/name))==sha
# Pinned binary is a local input, never copied into public evidence by this review.
assert digest(Path(ready['anvil_path']).read_bytes())==ready['anvil_sha256']
wrapper=load(Q/'observed-trace.json'); checked=load_observed_trace(Q/'observed-trace.json')
assert checked==wrapper and verify_observed_trace(wrapper)
assert wrapper['artifact_id']==seal_id(wrapper)
report=wrapper['trace_report']; assert verify_trace(report) and report['artifact_id']==seal_id(report)
assert wrapper['trace_artifact_id']==report['artifact_id']
prior=load(ROOT/'evidence/aave-consumer-price/native-006/report.json')
assert report['plan']==prior['plan']==load(Q/'plan.json')
assert report['source']==prior['source'] and report['baseline']==prior['baseline'] and report['candidate']==prior['candidate']
assert report['plan']['through_index']==31 and report['plan']['skip_indices']==[12]
assert report['plan']['source']['block_number']==18999892 and report['source']['block_transaction_count']==181
assert report['baseline_verified'] is True and report['baseline']['matches_original_receipts'] is True
inputs=report['source']['inputs']; baseline=report['baseline']['outcomes']; candidate=report['candidate']['outcomes']
assert len(inputs)==len(baseline)==len(candidate)==32
matches=0; shifts=0; gas_baseline=0; gas_candidate=0
for i,(original,b,c) in enumerate(zip(inputs,baseline,candidate)):
    assert original['index']==b['index']==c['index']==i and original['hash']==b['hash']==c['hash']
    assert b['receipt']==original['original_receipt'] and b['status']=='executed' and b['differing_fields']==[]
    gas_baseline+=int(b['receipt']['gasUsed'],16)
    if i==12: assert c['status']=='skipped' and 'receipt' not in c; continue
    assert c['status']=='executed'
    actual_diff={k for k,v in original['original_receipt'].items() if c['receipt'][k]!=v}
    assert set(c['differing_fields'])==actual_diff
    gas_candidate+=int(c['receipt']['gasUsed'],16)
    if i<12: assert not actual_diff; matches+=1
    else:
        assert actual_diff=={'transactionIndex','cumulativeGasUsed'}
        assert int(c['receipt']['transactionIndex'],16)==i-1
        assert int(c['receipt']['cumulativeGasUsed'],16)==int(b['receipt']['cumulativeGasUsed'],16)-336752
        shifts+=1
assert matches==12 and shifts==19 and gas_baseline-gas_candidate==336752
rows=wrapper['observations']; assert len(rows)==4
expected_phases=[('baseline','before'),('baseline','after'),('candidate','before'),('candidate','after')]
prices=[]; feeds=[]; identities=[]
def words(raw,count):
    assert re.fullmatch('0x[0-9a-fA-F]{'+str(count*64)+'}',raw)
    return [int(raw[2+i*64:2+(i+1)*64],16) for i in range(count)]
def address(raw):
    value=words(raw,1)[0]; assert value<2**160; return '0x'+format(value,'040x')
for i,(row,phase) in enumerate(zip(rows,expected_phases)):
    assert (row['branch'],row['phase'])==phase and row['errors']==[]
    raw=row['raw']; assert set(raw)=={'source','price','base_currency','base_unit','aggregator','latest_round_data'}
    assert address(raw['source'])=='0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419'
    assert address(raw['aggregator'])=='0xe62b71cf983019bff55bc83b48601ce8419650cc'
    assert address(raw['base_currency'])=='0x'+'00'*20 and words(raw['base_unit'],1)==[100000000]
    price=words(raw['price'],1)[0]; feed=words(raw['latest_round_data'],5)
    assert feed[0]<2**80 and feed[4]<2**80 and feed[4]>=feed[0]>0 and 0<feed[1]<2**255
    assert feed[1]==price and feed[2]<=row['head']['timestamp'] and 0<feed[3]<=row['head']['timestamp']
    assert row['head']['number']==18999891+(i%2)
    if i%2: assert row['head']['timestamp']==report['source']['header']['timestamp']
    else: assert row['head']['hash']==report['source']['parent']['block_hash']
    assert set(row['code'])=={'oracle_code','source_code'}
    assert all(0<v['bytes']<=65536 and re.fullmatch('[0-9a-f]{64}',v['sha256']) for v in row['code'].values())
    prices.append(price); feeds.append(feed); identities.append(row['code'])
assert prices==[257082415000,256292441874,257082415000,257082415000]
assert all(c==identities[0] for c in identities)
assert rows[0]['head']==rows[2]['head'] and rows[0]['raw']==rows[2]['raw']
assert feeds[1][0]==feeds[0][0]+1 and feeds[2]==feeds[3]==feeds[0]
classification={'baseline_price':prices[1],'baseline_receipts_verified':True,'candidate_price':prices[3],'complete_price_views':True,'price_difference':prices[3]-prices[1],'unproven_reasons':[]}
assert wrapper['classification']==classification and classification['price_difference']==789973126
assert load(Q/'trace-report.json')==report
child=load(Q/'child-terminal.json'); host=load(Q/'host-terminal.json'); ledger=load(Q/'owned-ledger.json')
assert child['cli_code']==host['code']==0 and host['cause']=='completed'
assert child['primary'] is None and child['telemetry_errors']==host['host_cleanup_errors']==[]
assert host['cli_reaped'] and host['sources_unchanged'] and host['inputs_unchanged'] and host['no_signals_to_grandchild_identifiers']
assert 0<report['runtime_seconds']<=150 and report['runtime_seconds']<=child['command_seconds']<=host['host_seconds']<=190
assert host['original_product_cap_seconds']==150 and host['host_watchdog_seconds']==190
assert child['passive_profile_only'] and host['native_no_CPU_RSS_sandbox']
owned=child['owned']; assert len(owned)==len(ledger)==len(host['owned_host_observations'])==3
assert [r['kind'] for r in owned].count('AnvilSession')==2 and [r['kind'] for r in owned].count('ParentCache')==1
for row,l,h in zip(owned,ledger,host['owned_host_observations']):
    assert {k:row[k] for k in ['kind','pid','port']}==l=={k:h[k] for k in ['kind','pid','port']}
    assert row['owner_reaped'] and row['returncode']==0 and row['group_absent'] and row['port_closed'] and row['pipes_closed']
    assert h['host_group_absent'] and h['host_port_closed']
cache=next(r['stats'] for r in owned if r['kind']=='ParentCache')
assert cache=={'requests':1879,'upstream':970,'hits':903,'entries':964,'bytes':2647997,'uncached':6,'errors':6,'refused_handlers':0}
output=json.loads(read(Q/'stdout.log')); assert output['artifact_id']==wrapper['artifact_id'] and output['trace_artifact_id']==report['artifact_id'] and output['complete_price_views'] is True
assert read(Q/'stderr.log')==b''
environment=load(Q/'environment.json'); assert environment['source_head']==ready['head'] and environment['model_calls']==environment['mainnet_writes']==0
rootproof=load(Q/'verified-result.json'); assert rootproof['wrapper_sha256']==digest(read(Q/'observed-trace.json')) and rootproof['trace_report_sha256']==digest(read(Q/'trace-report.json'))
assert rootproof['wrapper_artifact_id']==wrapper['artifact_id'] and rootproof['trace_artifact_id']==report['artifact_id']
read(Path(__file__))
review={'status':'passed_no_actionable_outcome_findings','reviewer':'review_cli_agent','head':ready['head'],'wrapper_sha256':digest(read(Q/'observed-trace.json')),'wrapper_artifact_id':wrapper['artifact_id'],'trace_file_sha256':digest(read(Q/'trace-report.json')),'trace_artifact_id':report['artifact_id'],'raw_source_baseline_candidate_exactly_native006':True,'receipts':{'original_inputs':32,'whole_block_inputs':181,'baseline_complete_matches':32,'candidate_executed':31,'omitted_index':12,'identical_candidate_rows':12,'structural_only_rows':19,'execution_field_changes':0,'gas_difference_only_omitted_transaction':336752},'consumer':{'profile':wrapper['profile'],'raw_prices':prices,'unit':100000000,'raw_candidate_minus_baseline_price':789973126,'four_complete_ABI_views':True,'same_parent_heads_raw_initial_views':True,'all_code_identities_stable':identities[0],'all_source_proxy_and_aggregator_addresses_stable':True,'feed_round_update_observed_baseline_only':True},'timing':{'replay_seconds':report['runtime_seconds'],'native_command_seconds':child['command_seconds'],'host_seconds':host['host_seconds'],'original_replay_cap':150,'host_watchdog':190},'owned_closure':{'two_anvil_one_cache':True,'actual_child_owned_Popen_reaped_group_port_pipes_closed':True,'separate_host_same_groups_ports_closed':True,'telemetry_cleanup_errors':[],'reviewer_fresh_OS_probes':False},'cache':cache,'bindings':hashes,'findings':[],'scope':['Independent offline rehash, strict supported wrapper reader/contract evaluation and manual fixed ABI/source/head/receipt/declaration comparison against actual raw records. No RPC/archive/process/test/signature/scanner/network re-execution.','31 current source and5 input hashes unchanged; readiness57d335 and prelaunch3df81 exact. Successful actual run is instrumented native CLI via unchanged runpy module and passive lifecycle profile.'],'limits':['Profile adds I/O/timing overhead; timing is not a speed benchmark or proof that earlier failures were caused by serialization.','Native mode does not attest CPU/RSS/cgroup sandbox; standard default Docker1/4 CI and actual native supported32 are separate.','Only32-of181 transactions and projected receipts; no full-block/state-root/opcode or all downstream contract state proof.','Read-only Aave WETH consumer price dependence only; no signed consumer action, lending/liquidation/trading strategy, economic benefit/profit or deployment/provider/code authenticity.','Code hash/length identities are retained observations; original bytecode bytes are not in the supported wrapper. No max-age freshness policy beyond recorded round/time consistency.','Six aggregate cache errors have unknown causes; no transport/provider-error causal claim inferred.','Closure is independently cross-checked between recorded actual child Popen/group/port/pipes and host group/port probes; no fresh OS probe repeated by reviewer.','Protected-main human approval, merge/deployment/Pages/submission remain separate.']}
out=Q/'independent-execution-review.json'; out.write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'path':str(out),'sha256':digest(out.read_bytes()),'bound_files':len(hashes),'status':review['status'],'findings':0},indent=2))
