"""Application evidence on the unchanged A501 bitstream, with immutable inputs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import time

import detection_a5 as a5
from preamble_cases import CONFIG, make_cases
from signal_detection_reference import TEMPLATE, scan
from test_detection import oracle

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data/application_preamble'
REPORT = ROOT/'report/application_preamble'
BUILD = a5.BUILD


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare():
    if (DATA/'manifest.json').exists():
        raise RuntimeError('Frozen corpus already exists; verify it instead of overwriting it.')
    cases = make_cases()
    DATA.mkdir(parents=True,exist_ok=True)
    a5.dump(DATA/'config.json',CONFIG)
    raw = ''.join(json.dumps(c,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n' for c in cases).encode()
    (DATA/'cases.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
    a5.dump(DATA/'manifest.json',dict(status='FROZEN_BEFORE_EVALUATION',build_id=BUILD,
        timestamp=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        frames=len(cases),groups=dict(Counter(c['group'] for c in cases)),
        generator_sha256=sha(ROOT/'src/host/preamble_cases.py'),config_sha256=sha(DATA/'config.json'),
        corpus_sha256=sha(DATA/'cases.jsonl.gz'),
        a501_manifest_sha256=sha(ROOT/'build/firmware/0000a501/source_manifest.json'),
        template=list(TEMPLATE)))
    print('PASS: froze 1704 application inputs and criteria before evaluation')


def load_cases(regenerate=False):
    m=read(DATA/'manifest.json')
    assert m['build_id']==BUILD and m['status']=='FROZEN_BEFORE_EVALUATION'
    assert m['generator_sha256']==sha(ROOT/'src/host/preamble_cases.py')
    assert m['config_sha256']==sha(DATA/'config.json') and read(DATA/'config.json')==CONFIG
    assert m['corpus_sha256']==sha(DATA/'cases.jsonl.gz')
    assert m['a501_manifest_sha256']==sha(ROOT/'build/firmware/0000a501/source_manifest.json')
    assert m['template']==list(TEMPLATE)
    cases=[json.loads(line) for line in gzip.decompress((DATA/'cases.jsonl.gz').read_bytes()).decode().splitlines()]
    assert len(cases)==1704 and dict(Counter(c['group'] for c in cases))==m['groups']
    if regenerate: assert cases==make_cases(),'Frozen inputs differ from generator'
    return cases


def aggregate(pairs):
    result=dict(frames=len(pairs),targets=0,detections=0,hits=0,misses=0,extras=0,
                complete_frames=0,false_alarm_frames=0,clipped_frames=0,clipped_samples=0,
                weak_targets=0,weak_hits=0)
    for c,r in pairs:
        truth=set(c['expected_positions']); found={t['position'] for t in r['targets']}
        result['targets']+=len(truth);result['detections']+=len(found)
        result['hits']+=len(truth&found);result['misses']+=len(truth-found);result['extras']+=len(found-truth)
        result['complete_frames']+=truth==found;result['false_alarm_frames']+=bool(found-truth)
        result['clipped_frames']+=bool(c['clipped_samples']);result['clipped_samples']+=c['clipped_samples']
        weak={p['start'] for p in c['packets'] if p.get('role')=='weak_designated'}
        result['weak_targets']+=len(weak);result['weak_hits']+=len(weak&found)
    result['recall']=result['hits']/result['targets'] if result['targets'] else None
    result['precision']=result['hits']/result['detections'] if result['detections'] else None
    result['complete_frame_rate']=result['complete_frames']/result['frames'] if result['frames'] else None
    result['false_alarm_frame_rate']=result['false_alarm_frames']/result['frames'] if result['frames'] else None
    return result


def quality(records,cases):
    by_id={c['id']:c for c in cases}
    pairs=[(by_id[r['case_id']],r) for r in records if r['group']!='performance']
    families=[]
    for group in sorted({c['group'] for c,r in pairs}):
        families.append(dict(group=group,**aggregate([(c,r) for c,r in pairs if c['group']==group])))
    core=[]
    for count in range(1,5):
        for snr in [6,12]:
            subset=[(c,r) for c,r in pairs if c['group']=='core' and c['metadata']['count']==count and c['metadata']['snr_db']==snr]
            if subset: core.append(dict(count=count,snr_db=snr,**aggregate(subset)))
    stress=[]
    for kind in ['snr','dc','ratio','tone','impulse']:
        for level in range(5):
            subset=[(c,r) for c,r in pairs if c['group']=='stress_'+kind and c['metadata']['level']==level]
            if subset: stress.append(dict(kind=kind,level=level,value=subset[0][0]['metadata']['value'],**aggregate(subset)))
    negatives=aggregate([(c,r) for c,r in pairs if c['group'].startswith('negative_')])
    nominal=aggregate([(c,r) for c,r in pairs if c['group']=='core'])
    gates={
        'core_groups_present':len(core)==8 and all(x['frames']==60 for x in core),
        'core_each_recall':len(core)==8 and all(x['recall']>=CONFIG['gates']['core_each_group_recall_min'] for x in core),
        'core_each_precision':len(core)==8 and all(x['precision'] is not None and x['precision']>=CONFIG['gates']['core_each_group_precision_min'] for x in core),
        'negative_count':negatives['frames']==1000,
        'negative_false_alarm_rate':negatives['frames']==1000 and negatives['false_alarm_frame_rate']<=CONFIG['gates']['negative_frame_false_alarm_rate_max'],
    }
    return dict(groups=families,core_groups=core,stress=stress,core=nominal,negative=negatives,
                engineering_goals=gates,engineering_goals_met=all(gates.values()))


def offline():
    cases=load_cases(regenerate=True);records=[]
    for c in cases:
        stats=oracle(c['samples'])
        assert stats==scan(c['samples']),c['id']
        records.append(dict(case_id=c['id'],group=c['group'],targets=a5.select_targets(stats)))
    a5.dump(DATA/'reference_results.json',records)
    summary=dict(status='REFERENCE_CHECK_PASS',physical_board=False,frames=len(cases),
                 windows=sum(len(c['samples'])-63 for c in cases),**quality(records,cases))
    a5.dump(DATA/'reference_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))


def make_plan(phase,case_id=None):
    cases=load_cases();by_id={c['id']:c for c in cases};p=a5.Plan();p.add('start_info')
    if phase=='batch':
        for c in cases:
            p.detect(c['id'],c,8,group=c['group'],trace=c['id'] in CONFIG['trace_cases'],case_id=c['id'])
        c=by_id[CONFIG['performance_case']]
        for repeat in range(30):
            for command in ((8,9) if repeat%2==0 else (9,8)):
                p.detect(f'performance_{repeat}_{command}',c,command,group='performance',case_id=c['id'],repeat=repeat)
    elif phase=='demo':
        c=by_id[case_id]
        p.detect(c['id'],c,8,group='demo',trace=True,case_id=c['id'])
    elif phase!='probe':raise ValueError(phase)
    p.add('finish_info');return p.items


def verify_records(plan,rows):
    records,counts=a5.verify(plan,rows,False)
    items=[x for x in plan if x['kind']=='detect']
    for record,item in zip(records,items): record['case_id']=item['case_id']
    return records,counts


def performance(records):
    out=[]
    for mode in ['multi_verify','multi_fast']:
        group=[r for r in records if r['group']=='performance' and r['mode']==mode]
        if not group:continue
        assert len(group)==30
        row=dict(mode=mode,repeats=len(group),case_id=CONFIG['performance_case'])
        for key in ['software_cycles','hardware_total_cycles','core_cycles','host_ms']:
            values=[x[key] for x in group if x[key] is not None]
            if values:
                row[key+'_min']=min(values);row[key+'_median']=statistics.median(values);row[key+'_max']=max(values)
        baseline=[r['software_cycles'] for r in records if r['group']=='performance' and r['mode']=='multi_verify']
        row['software_baseline_ms']=statistics.median(baseline)/50000
        row['hardware_ms']=row['hardware_total_cycles_median']/50000
        row['core_ms']=row['core_cycles_median']/50000
        row['speedup']=row['software_baseline_ms']/row['hardware_ms']
        row['software_measured_in_request']=mode=='multi_verify'
        out.append(row)
    return out


def run(phase,port='COM9',case_id=None):
    lock=ROOT/'board/results/.detection_a3_serial.lock'
    with lock.open('x',encoding='utf-8') as f:
        f.write(json.dumps(dict(phase='application_'+phase,timestamp=datetime.now(timezone.utc).isoformat())))
    try:return run_locked(phase,port,case_id)
    finally:lock.unlink()


def run_locked(phase,port,case_id):
    plan=make_plan(phase,case_id);stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out=ROOT/'board/results'/f'application_preamble_{phase}_{stamp}';out.mkdir(parents=True)
    a5.dump(out/'plan.json',plan)
    summary=dict(status='FAIL',physical_board=True,phase=phase,case_id=case_id,build_id=BUILD,
        port=port,baud=115200,clock_hz=50000000,timestamp=datetime.now(timezone.utc).isoformat(),
        corpus_sha256=sha(DATA/'cases.jsonl.gz'),error=None)
    start=time.perf_counter();print(str(out),flush=True)
    try:
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'src/host/detection_transport.ps1'),
             '-Port',port,'-Plan',str(out/'plan.json'),'-OutputDirectory',str(out)]
        with (out/'transport_console.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            for line in process.stdout:
                log.write(line);log.flush()
                if not line.startswith('Transport:') or int(line.split()[1])%100==0:print(line.rstrip(),flush=True)
            if process.wait():raise RuntimeError('Physical transport failed; inspect transport.json')
        rows=[json.loads(line) for line in (out/'responses.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        records,counts=verify_records(plan,rows)
        a5.dump(out/'verified_cases.json',records);a5.write_csv(out/'measurements.csv',records)
        summary.update(status='PASS',implementation_status='PASS',**counts)
        if phase=='batch':
            assert counts['detection_frames']==1764 and counts['fast_frames']==30
            summary.update(**quality(records,load_cases()),performance=performance(records))
            a5.write_csv(out/'application_groups.csv',summary['groups'])
            a5.write_csv(out/'core_groups.csv',summary['core_groups'])
            a5.write_csv(out/'stress.csv',summary['stress'])
            a5.write_csv(out/'performance.csv',summary['performance'])
        elif phase=='demo':
            c=next(c for c in load_cases() if c['id']==case_id)
            stats=[]
            for item,row in zip(plan,rows):
                if item['kind']=='trace':
                    _,_,body=a5.parse_frame(bytes.fromhex(row['rx_hex']))
                    offset,count=struct.unpack_from('<HH',body)
                    assert offset==len(stats)
                    stats.extend([s,e] for s,e in struct.iter_unpack('<iI',body[4:]))
            assert len(stats)==len(c['samples'])-63
            a5.dump(out/'demo.json',dict(**c,result=records[0],statistics=stats,
                run_id=out.name,timestamp=summary['timestamp'],source='physical_board',build_id=BUILD,status='PASS'))
    except Exception as exc:
        summary['error']=str(exc)
        raise
    finally:
        summary['elapsed_seconds']=time.perf_counter()-start;a5.dump(out/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ['status','phase','detection_frames','transactions','elapsed_seconds']},ensure_ascii=False),flush=True)
    return out,summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','offline','probe','batch','demo'])
    p.add_argument('--port',default='COM9');p.add_argument('--case-id');args=p.parse_args()
    if args.phase=='prepare':prepare()
    elif args.phase=='offline':offline()
    else:run(args.phase,args.port,args.case_id)
