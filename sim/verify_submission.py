"""Read-only verification of the compact submission; never accesses hardware."""
from pathlib import Path
import argparse, hashlib, json, re, statistics, struct, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/host'),str(ROOT/'sim/history')]
import application_preamble as app
import detection_a5 as a5
import detection_a3 as a3
import detection_a4 as a4
from vector_protocol import parse_frame,parse_dot,reference_dot,dot_payload

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def rows(p):return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def equal_summary(actual,summary):
    for k,v in actual.items():assert summary[k]==v,(k,summary.get(k),v)

def inventory():
    expected={'readme.md','src','sim','build','board','data','skill','report'}
    assert {x.name for x in ROOT.iterdir() if x.name!='.git'}==expected,'Unexpected root entry'
    manifest=read(ROOT/'report/package_manifest.json')
    files={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p.relative_to(ROOT).parts[0]!='.git'}
    assert files==set(manifest['sha256'])|{'report/package_manifest.json'},'Unexpected or missing packaged file'
    for name,digest in manifest['sha256'].items():
        assert re.fullmatch(r'[a-z0-9_./-]+',name),name
        assert sha(ROOT/name)==digest,name
    p=read(ROOT/'report/packaging_provenance.json')
    for name,entry in p['preserved_files'].items():assert sha(ROOT/name)==entry['sha256'],name
    print('PASS: exact seven-directory inventory and file hashes',len(files),flush=True)

def baselines():
    for tag,module in [('v1',None),('a3',a3),('a4',a4)]:
        folder=ROOT/'board/results'/('baseline_'+tag)
        plan=read(folder/'plan.json');raw=rows(folder/'responses.jsonl');provenance=read(folder/'provenance.json')
        assert len(plan)==len(raw)==provenance['selected_records']
        results=[];completed_base=None
        for item,row in zip(plan,raw):
            assert item['group']=='performance'
            if module:
                decoded,_=module.verify([item],[row],False);assert decoded[0]['n']==1024
                results.extend(decoded)
            else:
                command,seq,payload=parse_frame(bytes.fromhex(item['tx_hex']))
                assert command==2 and payload==dot_payload(item['a'],item['b'])
                cmd,rseq,body=parse_frame(bytes.fromhex(row['rx_hex']))
                value=parse_dot(body)
                assert cmd==0x82 and seq==rseq==item['seq']
                assert value['n']==1024 and value['flags']==0 and value['accelerator_status']==2
                assert value['software']==value['hardware']==reference_dot(item['a'],item['b'])
                if completed_base is None:completed_base=value['completed']-item['expected_completed']
                assert value['completed']==completed_base+item['expected_completed'] and value['hardware_core_cycles']==1026
                results.append(value)
        if tag=='v1':
            assert len(results)==30
            for k,v in [('software_cycles',95308),('hardware_total_cycles',53484),('hardware_core_cycles',1026)]:
                assert statistics.median(x[k] for x in results)==v,k
        else:
            summary=module.summarize(results)['performance']
            expected={'reuse':697988,'legacy':4634027} if tag=='a3' else {'cpu_reduce':702121,'peak_verify':93526,'peak_fast':93526}
            for x in summary:
                assert x['repeats']==30
                # FAST may differ in setup overhead; the report quotes VERIFY.
                if x['mode'] in expected and x['mode']!='peak_fast':assert x['hardware_total_cycles_median']==expected[x['mode']],x
            if tag=='a3':assert statistics.median(x['read_reduce_cycles'] for x in results if x['mode']=='reuse')==604533
        print('PASS: original',tag,'N=1024 timing pairs',len(results),flush=True)

def final_evidence():
    for name in ['detection_a5_all_20260925_165051_873902','detection_a5_button_20260925_171123_025947','detection_a5_clean_reprogram_20260925_171217_332944']:
        folder=ROOT/'board/results'/name;s=read(folder/'summary.json');plan=read(folder/'plan.json')
        actual,counts=a5.verify(plan,rows(folder/'responses.jsonl'),s['fresh'])
        assert s['status']=='PASS' and s['physical_board'] and s['build_id']==app.BUILD
        equal_summary(counts,s);equal_summary(a5.summarize(actual),s)
        t=read(folder/'transport.json');assert t['status']=='PASS' and t['responses']==len(plan) and t['error'] is None
        if s['phase']=='recovery':assert s['fresh'] and counts['detection_frames']==30
        print('PASS: final board archive',name,counts['detection_frames'],flush=True)
    folder=ROOT/'sim/results/detection_a5_system'
    actual,counts=a5.verify(read(folder/'plan.json'),rows(folder/'responses.jsonl'),True)
    equal_summary(counts,read(folder/'summary.json'));assert counts['transactions']==94
    for mode in ['selector','unit','system']:
        log=(ROOT/f'sim/results/detection_a5_{mode}.log').read_text(encoding='utf-8-sig')
        assert 'PASS:' in log and 'FAIL:' not in log,mode
    assert read(ROOT/'sim/results/detection_a5_unit/oracle.json')['frames']==3487
    print('PASS: final RTL logs and 94 production-firmware simulation transactions',flush=True)

def application():
    cases=app.load_cases(regenerate=True)
    reference=[dict(case_id=c['id'],group=c['group'],targets=a5.select_targets(app.oracle(c['samples']))) for c in cases]
    assert reference==app.read(app.DATA/'reference_results.json')
    equal_summary(app.quality(reference,cases),app.read(app.DATA/'reference_summary.json'))
    folder=ROOT/'board/results/application_preamble_batch_20260925_174436_888233'
    plan=read(folder/'plan.json');assert plan==app.make_plan('batch')
    actual,counts=app.verify_records(plan,rows(folder/'responses.jsonl'));s=read(folder/'summary.json')
    assert s['physical_board'] and s['status']==s['implementation_status']=='PASS'
    assert s['build_id']==app.BUILD and s['corpus_sha256']==sha(app.DATA/'cases.jsonl.gz')
    equal_summary(counts,s);equal_summary(app.quality(actual,cases),s)
    assert s['performance']==app.performance(actual)
    assert counts['detection_frames']==1764 and counts['transactions']==2054 and counts['fast_frames']==30
    metrics=read(ROOT/'report/application_preamble/metrics.json');equal_summary(s,metrics)
    t=read(folder/'transport.json');assert t['status']=='PASS' and t['error'] is None and t['responses']==len(plan)
    print('PASS: 1704 frozen application inputs, 60 timing calls and 2054 original UART transactions',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence-only',action='store_true');args=p.parse_args()
    if sys.flags.optimize:raise SystemExit('Do not use -O; verification requires assertions.')
    if not args.evidence_only:inventory()
    baselines();final_evidence();application()
    if not args.evidence_only:
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'sim/verify_materials.py')],cwd=ROOT)
        if r.returncode:raise SystemExit(r.returncode)
    print('PASS: compact submission replay. Historical data replay only; no new board measurement.',flush=True)
if __name__=='__main__':main()
