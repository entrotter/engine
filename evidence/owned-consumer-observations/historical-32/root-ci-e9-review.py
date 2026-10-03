"""Review downloaded CI bytes against immutable e9; no execution or network."""
import hashlib,json,re,subprocess,sys,zipfile
from pathlib import Path
W=Path(__file__).resolve().parents[2];Q=Path(__file__).resolve().parent
H='e9d629e1e4bfdcefd678fe40387e4376b1374f3c'
sys.path[:0]=[str(W/'src'),str(W/'scripts')]
from check_security import evaluate as se
from check_image_security import evaluate as ie,IDENTITY,ISSUER
from check_native_security import evaluate as ne,verify_claims,statement
from entrotter_engine.trace import verify_trace
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
gb=lambda p:subprocess.check_output(['git','show',H+':'+p],cwd=W)
gs=lambda p:hashlib.sha256(gb(p)).hexdigest()
c=read(Q/'checks-e9-current.json')
assert c['headRefOid']==H and len(c['statusCheckRollup'])==8
assert all(x['conclusion']=='SUCCESS' and x['status']=='COMPLETED' for x in c['statusCheckRollup'])
for n in ('quality','docs','evm','units','isolated'):
 m=read(Q/f'ci-{n}-e9-metadata.json');assert m['headSha']==H and m['conclusion']=='success'
policy=json.loads(gb('security-reviewed.json'))
assert len(policy['source_sha256'])==26
for n,h in policy['source_sha256'].items():assert gs(n)==sha(W/n)==h,n
quality=Q/'ci-quality-e9/engine-quality-reports'
scan=read(quality/'bandit.json');assert se(scan,policy)==25
assert set(scan['metrics'])-{'_totals'}==set(policy['source_sha256'])
wheel=next((quality/'wheels').glob('*.whl'))
with zipfile.ZipFile(wheel) as z:
 names={n for n in z.namelist() if n.startswith('entrotter_engine/') and n.endswith('.py')}
 assert len(names)==21 and names=={n.removeprefix('src/') for n in policy['source_sha256'] if n.startswith('src/')}
 for n in names:assert z.read(n)==gb('src/'+n)
norm=lambda n:re.sub('[-_.]+','-',n).lower()
lock={norm(n):v for n,v in re.findall(r'^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s\\]+)',gb('requirements-quality.txt').decode(),re.M)}
audit=read(quality/'dependencies.json');assert len(audit['dependencies'])==len(lock)==42
assert {norm(r['name']):r['version'] for r in audit['dependencies']}==lock
assert all(not r['vulns'] for r in audit['dependencies'])
assert 'Ran 33 tests' in (quality/'aave-consumer-controls.log').read_text()
docs=read(Q/'ci-docs-e9/docs-links/report.json')
assert docs['passed'] and not docs['worktree_dirty'] and docs['lychee_exit_code']==0
assert len(docs['files'])==21 and docs['report']['total']==222
assert all(docs['report'][k]==0 for k in ('errors','timeouts','excludes','cached'))
for n,h in docs['files'].items():assert gs(n)==h,n
merge=read(Q/'ci-merge-e9.json');head=read(Q/'ci-head-e9.json')
assert merge['sha']==docs['source_commit'] and merge['tree']['sha']==head['tree']['sha']
assert H in [r['sha'] for r in merge['parents']]
B=Q/'ci-isolated-e9/worker-image-security';R=B/'.quality'
manifest=read(B/'worker-image.json');assert len(manifest['source_files'])==22
for n,h in manifest['source_files'].items():assert gs('container/Dockerfile' if n=='Dockerfile' else 'src/entrotter_engine/'+n)==h,n
assert hashlib.sha256(json.dumps(manifest['source_files'],sort_keys=True).encode()).hexdigest()==manifest['source_digest']
assert gb('container/Dockerfile').decode().splitlines()[0]=='FROM '+manifest['base_image']
image=read(R/'image-security/summary.json');native=read(R/'native-security/summary.json')
for d,s,a in [('image-security',image,'check_image_security.py'),('native-security',native,'check_native_security.py')]:
 assert s['status']=='passed' and s['vulnerability_count']==0
 assert s['image_id']==manifest['image_id'] and s['source_digest']==manifest['source_digest']
 assert s['auditor_sha256']==gs('scripts/'+a) and s['report_sha256']==sha(R/d/'packages.json')
img=ie(read(R/'image-security/packages.json'),manifest['image_id'],read(R/'image-security/database.json'))
for k,v in img.items():assert image[k]==v,k
assert image['verified_base_signer']==IDENTITY and image['verified_base_issuer']==ISSUER
sbom=read(R/'native-security/signed-inventory.json')
verify_claims(statement(read(R/'native-security/provenance-bundle.json')),statement(read(R/'native-security/sbom-bundle.json')),sbom,manifest)
inv=ne(sbom,read(R/'native-security/packages.json'),read(R/'native-security/database.json'))
for k,v in inv.items():assert native[k]==v,k
assert native['manifest_sha256']==sha(B/'worker-image.json')
assert native['signed_sbom_sha256']==sha(R/'native-security/signed-inventory.json')
assert native['shared_tool_helper_sha256']==gs('scripts/check_image_security.py')
assert native['archive_sha256']==manifest['foundry_archive_sha256'] and native['anvil_binary_sha256']==manifest['anvil_binary_sha256']
assert image['database_sha256']==native['database_sha256']
historical=[]
for n,count in [('mainnet-prefix.json',1),('mainnet-prefix-four.json',4)]:
 p=R/'trace-replay'/n;r=read(p)
 assert verify_trace(r) and r['baseline_verified'] and len(r['baseline']['outcomes'])==count
 for a,b in zip(r['source']['inputs'],r['baseline']['outcomes']):assert a['original_receipt']==b['receipt'] and b['status']=='executed' and not b['differing_fields']
 historical.append({'name':n,'sha256':sha(p),'runtime_seconds':r['runtime_seconds'],'baseline_original_receipts_equal':count,'candidate_statuses':[x['status'] for x in r['candidate']['outcomes']]})
nlog=(Q/'ci-evm-e9.log').read_text();nt=re.findall(r'Ran 356 tests in ([0-9.]+)s',nlog)
assert len(nt)==1 and re.search(r'Z OK\s*$',nlog,re.M) and 'OK (skipped=' not in nlog
ulog=(Q/'ci-units-e9.log').read_text();assert len(re.findall(r'Ran 356 tests',ulog))==4 and len(re.findall(r'OK \(skipped=40\)',ulog))==4
ilog=(Q/'ci-isolated-e9.log').read_text();it=re.findall(r'Ran 25 tests in ([0-9.]+)s',ilog);assert len(it)==1 and re.search(r'Z OK\s*$',ilog,re.M)
assert 'test_actual_image_protocol_replays_signed_oracle_update_and_adverse_omission' in ilog
out={'head':H,'status':'passed','required_checks':8,'production_sources':26,'retained_findings':25,'wheel_modules':21,'wheel_sha256':sha(wheel),'python_identities':42,'docs_files':21,'docs_links':222,'synthetic_merge_tree_equal':True,'native_tests':356,'native_seconds':float(nt[0]),'unit_tests_each':356,'unit_Anvil_skips_each':40,'isolated_tests':25,'isolated_seconds':float(it[0]),'worker_image_id':manifest['image_id'],'worker_inputs':22,'base_image':manifest['base_image'],'OS_packages':sum(x['packages'] for x in img['inventories']),'signed_Cargo_packages':inv['cargo_packages'],'outside_Cargo_inventory':len(inv['outside_cargo_inventory']),'reported_vulnerabilities':0,'default_worker_replays':historical,'limits':['Database binary digest is recorded in CI but binary not exported for local rehash.','Signed Foundry whole-checkout Cargo inventory is not exact linked feature inventory; 172 non-Cargo entries remain outside coverage.','CI signature verification logs and attestation claims reviewed, no new local signature or image execution.','Default Docker1/four tests do not prove original32 supported CLI.','Software review does not grant protected-main human approval.'],'artifacts_sha256':{str(p.relative_to(Q)):sha(p) for folder in ('ci-quality-e9','ci-docs-e9','ci-isolated-e9') for p in sorted((Q/folder).rglob('*')) if p.is_file()},'logs_sha256':{n:sha(Q/f'ci-{n}-e9.log') for n in ('quality','docs','isolated','evm','units')},'reviewer_sha256':sha(Path(__file__))}
(Q/'root-ci-e9-review.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ('artifacts_sha256','logs_sha256','limits','default_worker_replays')}))
