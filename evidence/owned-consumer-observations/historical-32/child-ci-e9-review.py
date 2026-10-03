"""Offline independent inspection of retained e9 CI evidence; no tests or services."""
import base64
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
Q = ROOT / '.quality/bounded-admission'
HEAD = 'e9d629e1e4bfdcefd678fe40387e4376b1374f3c'
BASE = 'cgr.dev/chainguard/python@sha256:89281daac77a3d91ef298d70ce3b7a6ccb2ebf268c084fa9a9bda1c92e71c64d'
hashes = {}
def digest(data): return hashlib.sha256(data).hexdigest()
def read(path):
    path = Path(path); data = path.read_bytes()
    hashes[str(path.relative_to(ROOT))] = digest(data)
    return data
def load(path): return json.loads(read(path))
def git(*args): return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()
def canon(x): return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
assert git('rev-parse', 'HEAD') == HEAD
tracked = git('ls-tree', '-r', '--name-only', HEAD).splitlines()
merge = load(Q/'ci-merge-e9.json')
assert merge['tree']['sha'] == git('rev-parse', HEAD+'^{tree}')
assert {p['sha'] for p in merge['parents']} == {HEAD, 'bd5527f71d3c561335e7786b6f4421572cd9aad6'}
checks = load(Q/'checks-e9-current.json')
assert checks['headRefOid'] == HEAD
expected_checks = {'quality', 'docs-links', 'evm', 'isolated', *(f'unit ({v})' for v in ['3.11','3.12','3.13','3.14'])}
assert {c['name'] for c in checks['statusCheckRollup']} == expected_checks
assert all(c['conclusion']=='SUCCESS' and c['status']=='COMPLETED' for c in checks['statusCheckRollup'])
metadata = {}
logs = {}
for name in ['quality','docs','isolated','evm','units']:
    m = load(Q/f'ci-{name}-e9-metadata.json'); metadata[name] = m
    assert m['headSha']==HEAD and m['conclusion']=='success' and m['event']=='pull_request'
    assert all(j['conclusion']=='success' and j['status']=='completed' for j in m['jobs'])
    logs[name] = read(Q/f'ci-{name}-e9.log').decode()
    assert merge['sha'] in logs[name]
    for j in m['jobs']:
        assert any(c['detailsUrl']==j['url'] and c['name']==j['name'] for c in checks['statusCheckRollup'])
policy = load(ROOT/'security-reviewed.json')
sources = {p:digest(read(ROOT/p)) for p in tracked if p.endswith('.py') and p.startswith(('src/','scripts/'))}
assert len(sources)==26 and sources==policy['source_sha256']
quality = Q/'ci-quality-e9/engine-quality-reports'
bandit = load(quality/'bandit.json')
assert set(bandit['metrics'])-{'_totals'}==set(sources) and not bandit['errors']
assert bandit['metrics']['_totals']['nosec']==0 and bandit['metrics']['_totals']['skipped_tests']==0
assert len(bandit['results'])==len(policy['findings'])==25
fingerprints = Counter((r['filename'].removeprefix('./'),r['test_id'],r['line_number'],digest(r['code'].encode())) for r in bandit['results'])
reviewed = Counter((r['file'],r['test_id'],r['line'],r['code_sha256']) for r in policy['findings'])
assert fingerprints==reviewed and all(len(r['reason'])>=40 for r in policy['findings'])
old_policy = json.loads(git('show','7b50af23e608ea219e08833c6ff23cf736c8563d:security-reviewed.json'))
assert old_policy['findings']==policy['findings'] and policy['scanner_version']=='1.9.4'
assert '26 files already formatted' in logs['quality'] and 'no issues found in 26 source files' in logs['quality']
research = read(quality/'aave-consumer-controls.log').decode(); assert re.search(r'Ran 33 tests in [\d.]+s\s+OK\s*$',research)
lock = read(ROOT/'requirements-quality.txt').decode()
normalize = lambda s: re.sub(r'[-_.]+','-',s.lower())
identities = Counter((normalize(n),v) for n,v in re.findall(r'^([\w.-]+)(?:\[[^\]]+\])?==([^\s\\]+)',lock,re.M))
advisories = load(quality/'dependencies.json')
assert len(identities)==42 and Counter((normalize(p['name']),p['version']) for p in advisories['dependencies'])==identities
assert not advisories['fixes'] and all(p.get('vulns')==[] for p in advisories['dependencies'])
scope = load(quality/'dependency-scope.json'); assert scope=={'runtime':[],'build':['setuptools==84.0.0'],'optional_runtime':{},'audited_locked_packages':42}
wheel = next((quality/'wheels').glob('*.whl')); read(wheel)
with zipfile.ZipFile(wheel) as z:
    modules = {p.removeprefix('src/'):h for p,h in sources.items() if p.startswith('src/')}
    assert len(modules)==21 and {n for n in z.namelist() if n.endswith('.py')}==set(modules)
    assert all(digest(z.read(n))==h for n,h in modules.items())
    assert not any(line.startswith('Requires-Dist:') for line in z.read('entrotter_engine-0.1.0.dist-info/METADATA').decode().splitlines())
docs = load(Q/'ci-docs-e9/docs-links/report.json')
doc_paths = {p for p in tracked if p.endswith('.md')}
assert len(doc_paths)==21 and set(docs['files'])==doc_paths
assert all(digest(read(ROOT/p))==h for p,h in docs['files'].items())
assert docs['source_commit']==merge['sha'] and docs['passed'] and not docs['worktree_dirty'] and docs['lychee_exit_code']==0
assert docs['checker']=='lychee 0.24.2' and docs['checker_sha256']=='87e6e75195df5753f08c53b5c0a13694b8328edd8df009914ae9e29b5000162d'
dr=docs['report']; assert dr['total']==dr['successful']==222 and dr['unique']==214
assert all(dr[k]==0 for k in ['errors','timeouts','excludes','unknown','unsupported','cached'])
assert sum(len(v) for v in dr['success_map'].values())==222
assert 'docs-links@ea74aec66c5234edb935e4b12c14ec686dc73f80' in logs['docs']
def totals(log, expected, skips):
    runs=re.findall(r'Ran (\d+) tests in ([\d.]+)s',log)
    assert runs and all(int(n)==expected for n,s in runs)
    if skips: assert log.count(f'OK (skipped={skips})')==len(runs)
    else: assert len(re.findall(r'Z OK\s*$',log,re.M))==len(runs) and '... skipped ' not in log
    return [float(s) for n,s in runs]
native_times=totals(logs['evm'],356,0); unit_times=totals(logs['units'],356,40); isolated_times=totals(logs['isolated'],25,0)
assert len(native_times)==1 and len(unit_times)==4 and len(isolated_times)==1
image_root=Q/'ci-isolated-e9/worker-image-security'; report_root=image_root/'.quality'
manifest=load(image_root/'worker-image.json')
image_sources={p.removeprefix('src/entrotter_engine/'):h for p,h in sources.items() if p.startswith('src/')}
image_sources['Dockerfile']=digest(read(ROOT/'container/Dockerfile'))
assert len(image_sources)==22 and manifest['source_files']==image_sources
assert digest(json.dumps(image_sources,sort_keys=True).encode())==manifest['source_digest']
assert manifest['base_image']==BASE and read(ROOT/'container/Dockerfile').decode().splitlines()[0]=='FROM '+BASE
assert manifest['foundry_version']=='1.8.3' and manifest['architecture']=='amd64' and not manifest['published']
build=load(report_root/'build-output-docker.json'); assert build['status']=='passed' and build['scope'].endswith('owned probe image removed in finally')
summaries={}
for kind in ['image','native']:
    p=report_root/f'{kind}-security'; summary=load(p/'summary.json'); raw=load(p/'packages.json'); db=load(p/'database.json')
    summaries[kind]=summary
    assert summary['status']=='passed' and summary['vulnerability_count']==0
    assert summary['image_id']==manifest['image_id'] and summary['source_digest']==manifest['source_digest']
    assert summary['report_sha256']==digest(read(p/'packages.json'))
    # database_sha256 describes the unexported SQLite trivy.db, not metadata.json.
    assert re.fullmatch('[0-9a-f]{64}', summary['database_sha256'])
    assert raw['SchemaVersion']==2 and raw['Trivy']['Version']==summary['trivy_version']=='0.74.0'
    assert summary['trivy_archive_sha256']=='2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a'
    assert summary['cosign_version']=='3.1.3' and summary['cosign_binary_sha256']=='4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71'
    checked=datetime.fromisoformat(metadata['isolated']['jobs'][0]['completedAt'].replace('Z','+00:00'))
    updated=datetime.fromisoformat(db['UpdatedAt'].replace('Z','+00:00')); nxt=datetime.fromisoformat(db['NextUpdate'].replace('Z','+00:00'))
    assert db['Version']==2 and updated<=checked<nxt and checked-updated<timedelta(days=1)
    assert summary['database_updated_at']==db['UpdatedAt'] and summary['database_next_update']==db['NextUpdate']
    assert all(not result.get('Vulnerabilities',[]) for result in raw['Results'])
im=summaries['image']; image_raw=load(report_root/'image-security/packages.json')
assert image_raw['ArtifactType']=='container_image' and image_raw['Metadata']['ImageID']==manifest['image_id']
os_packages=[p for r in image_raw['Results'] for p in r['Packages']]; assert len(os_packages)==31
assert all(r['Class']=='os-pkgs' and r['Type']=='wolfi' for r in image_raw['Results'])
assert {'python-3.14','python-3.14-base','glibc-2.44','libssl3','ca-certificates-bundle'}.issubset({p['Name'] for p in os_packages})
assert im['auditor_sha256']==sources['scripts/check_image_security.py'] and im['base_image']==BASE
signatures=load(report_root/'image-security/signature.json')
assert signatures and all(s['critical']['image']['docker-manifest-digest']==BASE.split('@')[1] for s in signatures)
assert all(s['optional']['1.3.6.1.4.1.57264.1.1']=='https://token.actions.githubusercontent.com' for s in signatures)
assert im['verified_base_signer']=='https://github.com/chainguard-images/images/.github/workflows/release.yaml@refs/heads/main'
assert 'code-signing certificate was verified' in read(report_root/'image-security/signature.log').decode()
nm=summaries['native']; p=report_root/'native-security'; sbom=load(p/'signed-inventory.json')
assert digest(read(p/'signed-inventory.json'))==nm['signed_sbom_sha256']=='8fb1fd40f45ff7eb97f40a6f020586e1e486ba701ae891e6ee6f63fff9ea6c7b'
def statement(bundle):
    e=bundle['dsseEnvelope']; assert e['payloadType']=='application/vnd.in-toto+json'
    x=json.loads(base64.b64decode(e['payload'],validate=True)); assert x['_type']=='https://in-toto.io/Statement/v1'; return x
attestations=load(p/'attestations.json')['attestations']; claims={}
for kind in ['provenance','sbom']:
    bundle=load(p/f'{kind}-bundle.json'); assert any(a['bundle']==bundle for a in attestations)
    claims[kind]=statement(bundle); assert read(p/f'{kind}-verification.log').decode().strip()=='Verified OK'
assert claims['sbom']['predicate']==sbom and claims['sbom']['predicateType']=='https://spdx.dev/Document/v2.3'
assert claims['provenance']['predicateType']=='https://slsa.dev/provenance/v1'
archive={'name':'foundry_v1.8.3_linux_amd64.tar.gz','digest':{'sha256':manifest['foundry_archive_sha256']}}
assert archive in claims['sbom']['subject'] and archive in claims['provenance']['subject']
assert {'name':'anvil','digest':{'sha256':manifest['anvil_binary_sha256']}} in claims['provenance']['subject']
assert manifest['foundry_archive_sha256']==nm['archive_sha256']=='7ca48e6ca3cac1bce1403ca67e5bc1dc3bc1fd818199c9957c7165079c228568'
assert nm['verified_signer']=='https://github.com/foundry-rs/foundry/.github/workflows/release.yml@refs/tags/v1.8.3' and nm['verified_issuer']=='https://token.actions.githubusercontent.com'
assert nm['database_sha256']==im['database_sha256'] and nm['shared_tool_helper_sha256']==sources['scripts/check_image_security.py']
assert nm['anvil_binary_sha256']==manifest['anvil_binary_sha256'] and nm['auditor_sha256']==sources['scripts/check_native_security.py']
assert nm['manifest_sha256']==digest(read(image_root/'worker-image.json'))
assert any(d.get('digest',{}).get('gitCommit')=='cae51ad458f6abb64852b7709eb784352429825d' and d.get('uri')=='git+https://github.com/foundry-rs/foundry@refs/tags/v1.8.3' for d in claims['provenance']['predicate']['buildDefinition']['resolvedDependencies'])
expected=Counter(); outside=0
for item in sbom['packages']:
    purls=[r['referenceLocator'] for r in item.get('externalRefs',[]) if r.get('referenceType')=='purl' and r['referenceLocator'].startswith('pkg:cargo/')]
    if purls: assert len(purls)==1; expected[(item['name'],item['versionInfo'],purls[0])]+=1
    else: outside+=1
native_raw=load(p/'packages.json'); observed=Counter((v['Name'],v['Version'],v['Identifier']['PURL']) for r in native_raw['Results'] for v in r['Packages'])
assert expected==observed and sum(expected.values())==nm['cargo_packages']==1126
assert len(sbom['packages'])==nm['signed_sbom_packages']==1298 and outside==len(nm['outside_cargo_inventory'])==172
assert native_raw['ArtifactType']=='spdx' and all(r['Class']=='lang-pkgs' and r['Type']=='cargo' for r in native_raw['Results'])
trace_facts=[]
for count,filename,plan_name in [(1,'mainnet-prefix.json','canonical-mainnet-prefix.json'),(4,'mainnet-prefix-four.json','canonical-mainnet-prefix-four.json')]:
    r=load(report_root/'trace-replay'/filename); body={k:v for k,v in r.items() if k!='artifact_id'}
    assert digest(canon(body))==r['artifact_id'] and r['trace_version']=='0.1.0' and r['baseline_verified'] is True
    assert r['plan']==load(ROOT/'tests/data'/plan_name) and r['baseline']['matches_original_receipts'] is True
    assert len(r['source']['inputs'])==len(r['baseline']['outcomes'])==len(r['candidate']['outcomes'])==count
    assert r['source']['parent']['block_number']==r['plan']['source']['block_number']-1 and r['source']['parent']['chain_id']==1
    for tx,o in zip(r['source']['inputs'],r['baseline']['outcomes']):
        assert o['status']=='executed' and o['receipt']==tx['original_receipt'] and o['index']==tx['index'] and o['hash']==tx['hash'] and not o['differing_fields']
    for tx,o in zip(r['source']['inputs'],r['candidate']['outcomes']):
        assert o['index']==tx['index'] and o['hash']==tx['hash']
        if o['status']=='executed': assert set(o['differing_fields'])=={k for k,v in tx['original_receipt'].items() if o['receipt'][k]!=v}
        else: assert 'receipt' not in o
    statuses=[o['status'] for o in r['candidate']['outcomes']]
    assert statuses==(['skipped'] if count==1 else ['skipped','executed','executed','nonce_conflict'])
    assert [int(o['receipt']['gasUsed'],16) for o in r['baseline']['outcomes']]==([208144] if count==1 else [208144,234720,175305,178980])
    assert [len(o['receipt']['logs']) for o in r['baseline']['outcomes']]==([8] if count==1 else [8,10,6,8])
    if count==4:
        assert [int(o['receipt']['gasUsed'],16) for o in r['candidate']['outcomes'][1:3]]==[245136,185721]
        assert r['candidate']['outcomes'][3]['expected_nonce']==5522 and r['candidate']['outcomes'][3]['original_nonce']==5523
    trace_facts.append({'prefix':count,'artifact_id':r['artifact_id'],'runtime_seconds':r['runtime_seconds'],'candidate_statuses':statuses,'full_baseline_receipts_equal_original':True})
assert metadata['isolated']['jobs'][0]['steps'][6]['conclusion']=='success'  # step bodies checked in immutable workflow/logs
for path in tracked:
    if path.startswith('.github/workflows/'): read(ROOT/path)
read(Path(__file__))
review={'status':'passed_no_actionable_artifact_findings','reviewer':'review_cli_agent','head':HEAD,'synthetic_merge':{'sha':merge['sha'],'tree':merge['tree']['sha'],'entire_tree_equals_head':True},'checks':checks['statusCheckRollup'],'source_sha256':sources,'quality':{'sources':26,'retained_findings':25,'exact_prior_rationales':True,'nosec_skipped_errors':0,'wheel_modules':21,'python_locked_identities':42,'python_reported_advisories':0,'public_research_controls':33},'docs':{'files':21,'links':222,'unique':214,'errors_timeouts_exclusions':0,'all_git_document_bytes_match':True,'checker':docs['checker'],'checker_sha256':docs['checker_sha256']},'native':{'tests':356,'seconds':native_times,'skips':0},'units':{'versions':['3.11','3.12','3.13','3.14'],'tests_each':356,'skips_each':40,'seconds_in_log_order':unit_times},'isolated':{'tests':25,'seconds':isolated_times,'image_id':manifest['image_id'],'source_inputs':22,'source_digest':manifest['source_digest'],'base':BASE,'default_trace_reports':trace_facts},'audits':{'os_packages':31,'os_reported_findings':0,'cargo_identities':1126,'cargo_reported_findings':0,'signed_inventory_packages':1298,'outside_cargo':172,'database_updated_at':im['database_updated_at'],'database_next_update':im['database_next_update'],'trivy_version':im['trivy_version'],'cosign_version':im['cosign_version'],'retained_signature_verification_success_logs':True,'signed_source_binary_archive_sbom_claims_match':True},'evidence_sha256':hashes,'findings':[],'reviewer_corrections':['First offline verifier attempt wrongly compared summary.database_sha256 (the unexported SQLite trivy.db digest) to exported database.json metadata digest and stopped at line106. Corrected based on immutable auditor source; no product/artifact failure or scanner rerun. Both audit summaries agree on SQLite digest; metadata bytes are independently bound.'],'limits':['Offline independent inspection of retained current CI raw artifacts/logs/metadata. No tests/scanners/network/container/archive execution.','Signature verification success is evidenced by pinned CI verifier logs and source/bundle bindings; this review did not independently rerun cryptographic signature verification or export database/tool binaries.','Zero reported advisories covers detected31OS and signed1126Cargo identities at the recorded database time, not unknown vulnerabilities or complete binary dependencies.172 signed non-Cargo/workflow entries remain outside Cargo advisory coverage; signed SBOM represents whole Foundry workspace rather than exact linked Anvil target.','CI default1/four canonical receipt proofs remain distinct from historical32 new supported consumer-observation command, which was not exercised by those default gates. Provider/state authenticity, full-block roots/opcodes and economic benefit are not proven.','Protected-main GitHub human approval, merge/deployment/Pages/submission remain separate.']}
out=Q/'child-ci-e9-review.json'; out.write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'status':review['status'],'path':str(out),'sha256':digest(out.read_bytes()),'bound_files':len(hashes),'native_seconds':native_times,'isolated_seconds':isolated_times,'findings':0},indent=2))
