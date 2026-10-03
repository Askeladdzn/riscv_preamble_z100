"""Z100 example adapter. Generic audit.py remains independent of this project."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile


def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_root')
    args=parser.parse_args()
    root=Path(args.project_root).resolve()
    sys.path.insert(0,str(root/'src/host'))
    import application_preamble as app
    app.ROOT=root
    app.DATA=root/'data/application_preamble'
    # Parse archived raw UART, not a freshly generated mock measurement.
    run=root/'board/results/application_preamble_batch_20260925_174436_888233'
    plan=app.read(run/'plan.json')
    raw=[json.loads(x) for x in (run/'responses.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    observed,_=app.verify_records(plan,raw)
    cases=app.load_cases()
    reference=app.read(app.DATA/'reference_results.json')
    refs={x['case_id']:x for x in reference}
    raw_by_name={x['name']:x for x in raw}
    expected=[];actual=[];inputs={}
    def targets(items):
        return [dict(position=int(x['position']),score=int(x['score']),energy=int(x['window_energy'])) for x in items]
    for case in cases:
        cid=case['id']
        payload=dict(samples=case['samples'],template=list(app.TEMPLATE),threshold='7/10',capacity=4,separation=64)
        ih=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        inputs[cid]=ih
        expected.append(dict(case_id=cid,input_sha256=ih,result=targets(refs[cid]['targets'])))
        _,_,body=app.a5.parse_frame(bytes.fromhex(raw_by_name[cid]['rx_hex']))
        words=struct.unpack('<56I',body)
        measured=[]
        for k in range(words[29]):
            pos,score,energy=words[44+3*k:47+3*k]
            measured.append(dict(position=pos,score=score if score<2**31 else score-2**32,energy=energy))
        actual.append(dict(case_id=cid,input_sha256=ih,result=measured,build_id=f'{words[24]:08X}'))
    trials=[]
    for row in observed:
        if row['case_id']=='core_q4_s6_r00' and row['mode']=='multi_verify' and row['name']!=row['case_id']:
            for mode,key in [('cpu','software_cycles'),('accelerator','hardware_total_cycles')]:
                trials.append(dict(task='four_packet_preamble',case_id=row['case_id'],input_sha256=inputs[row['case_id']],
                                   build_id=app.BUILD,clock_hz=50000000,boundary='board_full_task',mode=mode,cycles=row[key]))
    if len(expected)!=1704 or len(trials)!=60:raise RuntimeError('corpus/timing sample count changed')
    audit=Path(__file__).with_name('audit.py')
    with tempfile.TemporaryDirectory(prefix='z100_skill_replay_') as temp:
        work=Path(temp)
        for name,rows in [('expected',expected),('observed',actual)]:
            (work/(name+'.jsonl')).write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8')
        dump(work/'timing.json',dict(trials=trials))
        checks=[]
        for params in [['compare',work/'expected.jsonl',work/'observed.jsonl','--build-id',app.BUILD],['timing',work/'timing.json']]:
            r=subprocess.run([sys.executable,'-B',str(audit),*map(str,params)],capture_output=True,text=True,encoding='utf-8')
            if r.returncode:raise RuntimeError(r.stdout+r.stderr)
            checks.append(json.loads(r.stdout))
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [run/'plan.json',run/'responses.jsonl',app.DATA/'cases.jsonl.gz',app.DATA/'reference_results.json']}
    print(json.dumps(dict(status='PASS',physical_board=False,source='replay of archived physical-board UART; no new board run',
                         build_id=app.BUILD,checks=checks,source_sha256=hashes),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
