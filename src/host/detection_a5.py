"""A5 physical hardware-peak measurements, immutable raw records and independent verification."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import struct
import subprocess
import time
import zlib
from test_detection import inputs, oracle
from signal_detection_reference import TEMPLATE, decide
from vector_protocol import frame, parse_frame, dot_payload, reference_dot, parse_dot

ROOT=Path(__file__).resolve().parents[2]
BUILD='0000A501'
LENGTHS=[64,128,256,512,1024]
SEED=0xA3010001
REPEATS=30
NONE=0xffffffff

def dump(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def select_targets(stats):
    # Independent integer oracle: exhaustive greedy search, strict earliest tie.
    remaining=list(range(len(stats)));found=[]
    for _ in range(4):
        best=None
        for k in remaining:
            s,e=stats[k]
            if e and (best is None or s*s*stats[best][1]>stats[best][0]**2*e):best=k
        if best is None:break
        s,e=stats[best]
        if 100*s*s<3136*e:break
        found.append(dict(position=best,score=s,window_energy=e,correlation_abs=abs(s)/math.sqrt(64*e)))
        remaining=[k for k in remaining if abs(k-best)>=64]
    return found

def signal_at(n,positions,snr=6,seed=1,signs=None,amplitudes=None,noise=True):
    rng=random.Random(seed);sigma=256/(10**(snr/20));clipped=0
    raw=[round(rng.gauss(0,sigma)) if noise else 0 for _ in range(n)]
    for j,k in enumerate(positions):
        amp=(amplitudes[j] if amplitudes else 256)*(signs[j] if signs else 1)
        for i,t in enumerate(TEMPLATE):raw[k+i]+=amp*t
    for i,v in enumerate(raw):
        raw[i]=max(-2048,min(2047,v));clipped+=raw[i]!=v
    return dict(samples=raw,expected_positions=positions,expected_position=positions[0] if len(positions)==1 else None,
                snr_db=snr,seed=seed,clipped_samples=clipped)

def make_signal(n=1024,position=128,snr=6,seed=1,mode='mixed',count=3):
    if type(n) is not int or n not in LENGTHS or type(count) is not int or not 1<=count<=4 or count*64>n:
        raise ValueError('Invalid length or target count')
    if type(position) is not int or not 0<=position<=n-count*64:raise ValueError('Invalid start')
    if snr not in [-6,-3,0,3,6,12] or type(seed) is not int or not 0<=seed<=NONE:raise ValueError('Invalid noise parameters')
    if mode not in ['target','inverted','mixed','noise','zero']:raise ValueError('Invalid mode')
    positions=[] if mode in ['noise','zero'] else [position] if count==1 else [position+i*(n-64-position)//(count-1) for i in range(count)]
    signs=[-1 if mode=='inverted' or (mode=='mixed' and i%2) else 1 for i in range(len(positions))]
    c=signal_at(n,positions,snr,seed,signs,noise=mode!='zero');c['mode']=mode
    return c

def performance_signal(n):return make_signal(n,0,6,SEED+n,'mixed',min(4,n//64))

def multi_inputs():
    cases=[]
    def add(name,c,group='multi_clean'):
        c.update(id=name,group=group);cases.append(c)
    for j,(n,p) in enumerate([(64,[]),(64,[0]),(128,[0,64]),(192,[0,64,128]),(256,[0,64,128,192]),
                              (256,[0,192]),(256,[1,65,129]),(256,[63,127,191]),(1024,[0,320,640,960]),
                              (1024,[0,64,128,192,256]),(1024,[]),(1024,[960])]):
        add(f'multi_edge_{j}',signal_at(n,p,noise=False,signs=[(-1)**i for i in range(len(p))]))
    # Every admissible first position with four touching targets, equal normalized peaks.
    for pos in range(129):add(f'multi_shift_{pos}',signal_at(384,[pos+64*i for i in range(4)],noise=False,amplitudes=[128,256,512,1024]),'multi_shift')
    rng=random.Random(0xA501)
    for i in range(80):
        count=1+i%4;n=1024
        cells=sorted(rng.sample(range(16),count));p=[64*x for x in cells]
        add(f'multi_noise6_{i}',signal_at(n,p,6,0xA510+i,signs=[rng.choice([-1,1]) for _ in p]),'multi_noise6')
    for i in range(40):
        add(f'multi_noise0_{i}',signal_at(1024,[0,256,640,960],0,0xA520+i),'multi_noise0')
        add(f'multi_negative_{i}',signal_at(1024,[],6,0xA530+i),'multi_negative')
    # Overlap is deliberately labelled outside the supported separable-target contract.
    for gap in [1,31,63,64,65]:
        add(f'multi_spacing_{gap}',signal_at(256,[0,gap],noise=False),'multi_spacing' if gap>=64 else 'multi_overlap_out_of_scope')
    return cases


class Plan:
    def __init__(self): self.items=[]
    def add(self,name,command=1,payload=b'',kind='info',reset_before=False,**meta):
        seq=(65000+len(self.items))&65535
        size=(224 if command in (8,9) else 112) if kind=='detect' else 40 if kind=='dot' else 8 if kind=='error' else 32 if kind=='info' else 4+8*meta['count']
        item=dict(name=name,kind=kind,command=command,seq=seq,tx_hex=frame(command,seq,payload).hex(),
                  response_bytes=size+16,reset_before=reset_before,**meta)
        self.items.append(item);return item
    def detect(self,name,case,command=6,group='correctness',trace=False,**meta):
        x=case['samples'];other={k:v for k,v in case.items() if k not in ('samples','id','group')}
        self.add(name,command,struct.pack('<HH',len(x),0)+struct.pack('<'+'h'*len(x),*x),'detect',group=group,**other,**meta)
        if trace:
            for k in range(0,len(x)-63,64):
                count=min(64,len(x)-63-k)
                self.add(f'{name}_trace_{k}',4,struct.pack('<HH',k,count),'trace',offset=k,count=count)
    def dot(self,name,a,b): self.add(name,2,dot_payload(a,b),'dot',a=a,b=b)
    def errors(self):
        for name,command,payload,code in [
            ('bad_n',3,struct.pack('<HH',63,0)+bytes(126),2),
            ('bad_flags',3,struct.pack('<HH',64,1)+bytes(128),2),
            ('bad_range',3,struct.pack('<HHh',64,0,2048)+bytes(126),9),
            ('legacy_bad_range',5,struct.pack('<HHh',64,0,-2049)+bytes(126),9),
            ('legacy_short',5,b'!',2),('unknown_command',0x71,b'',3),
            ('trace_count',4,struct.pack('<HH',0,65),2)]:
            self.add(name,command,payload,'error',error=code)
        q=self.add('bad_crc',3,struct.pack('<HH',64,0)+bytes(128),'error',error=1)
        raw=bytearray.fromhex(q['tx_hex']);raw[-1]^=1;q['tx_hex']=raw.hex()
        q=self.add('truncated_payload',3,struct.pack('<HH',64,0)+bytes(128),'error',error=5)
        q['tx_hex']=q['tx_hex'][:40]
        for command in (6,7,8,9):
            for label,payload,code in [('short',b'!',2),('range',struct.pack('<HHh',64,0,2048)+bytes(126),9)]:
                self.add(f'peak_{command}_{label}',command,payload,'error',error=code)
        self.add('after_errors')

def make_plan(phase,scenario=None):
    p=Plan();p.add('start_info')
    if phase=='all':
        c=performance_signal(1024)
        p.detect('cold_1024',c,group='cold');p.detect('reuse_1024',c,group='cold_reuse')
        for c in inputs(): p.detect(c['id'],c,group=c['group'])
        for c in multi_inputs(): p.detect(c['id'],c,8,group=c['group'])
        p.add('after_a1')
        rng=random.Random(SEED+1)
        lengths=[64,65,66,127,128,129,255,256,257,511,512,513,1023,1024]+[rng.randint(64,1024) for _ in range(128)]
        for i,n in enumerate(lengths):
            x=[rng.randint(-2048,2047) for _ in range(n)]
            if i%4==1: x=[-2048 if j%2 else 2047 for j in range(n)]
            if i%4==2: x=[0]*n
            p.detect(f'continuous_{i}',dict(samples=x),group='continuous')
        p.add('after_continuous')
        for n in LENGTHS:
            for mode in (6,8,9): p.detect(f'warmup_{n}_{mode}',performance_signal(n),mode,group='warmup')
        for repeat in range(REPEATS):
            order=LENGTHS.copy();rng.shuffle(order)
            for n in order:
                for mode in ((6,8,9) if repeat%2==0 else (9,8,6)):
                    p.detect(f'performance_{n}_{repeat}_{mode}',performance_signal(n),mode,group='performance',repeat=repeat)
        p.errors();p.detect('error_recovery',performance_signal(64),trace=True,group='recovery')
        p.dot('legacy_full_int16',[-32768]*1024,[32767]*1024)
    elif phase=='recovery':
        p.detect('cold_1024',performance_signal(1024),group='cold',trace=True)
        p.detect('reuse_1024',performance_signal(1024),group='cold_reuse')
        for c in inputs()[:11]: p.detect(c['id'],c,trace=True,group='recovery')
        p.detect('legacy_recovery',performance_signal(128),5,group='recovery',trace=True)
        p.detect('scanner_after_legacy',performance_signal(128),3,group='recovery')
        p.detect('fast_full_trace',performance_signal(1024),7,trace=True,group='recovery')
        p.detect('fast_zero_trace',dict(samples=[0]*64),7,trace=True,group='recovery')
        for c in multi_inputs()[:12]: p.detect(c['id'],c,8,trace=True,group='multi_recovery')
        p.detect('multi_fast_trace',performance_signal(1024),9,trace=True,group='multi_recovery')
        p.dot('legacy_extreme',[-32768]*1024,[-32768]*1024)
    elif phase=='sim':
        for c in inputs()[7:9]: p.detect(c['id'],c,trace=True)
        for n in (64,128):
            c=performance_signal(n)
            for command in (3,5,6,7): p.detect(f'mode_{command}_{n}',c,command,trace=True)
        p.detect('fast_zero',dict(samples=[0]*64),7,trace=True)
        for c in multi_inputs()[:8]: p.detect(c['id'],c,8,trace=True,group='multi_sim')
        p.detect('multi_fast',performance_signal(256),9,trace=True)
        p.detect('single_after_multi',performance_signal(128),6,trace=True)
        p.detect('multi_zero_fast',dict(samples=[0]*64),9,trace=True)
        p.errors();p.dot('legacy_dot',[-32768,32767],[-32768,32767])
        p.add('reset_info',reset_before=True)
        p.detect('reset_fast',performance_signal(64),7,trace=True)
        p.detect('verify_after_fast',performance_signal(128),6,trace=True)
    elif phase=='demo': p.detect('interactive',make_signal(**scenario),8,trace=True,group='demo')
    elif phase!='probe': raise ValueError(phase)
    p.add('finish_info');return p.items

def write_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:json.dumps(v,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows)

def verify(plan,rows,fresh=False):
    if len(rows)!=len(plan): raise AssertionError(f'Received {len(rows)}/{len(plan)} responses')
    records=[];last_stats=None;total=None;scans=None;dots=None;timeouts=None;windows=traced=errors=dot_count=0
    evaluated=0
    template_expected=None
    if fresh: total=scans=dots=timeouts=0;template_expected=1
    for item,row in zip(plan,rows):
        if item['reset_before']: total=scans=dots=timeouts=0;template_expected=1;last_stats=None
        assert not row.get('transport_error'),row
        assert row.get('name',item['name'])==item['name']
        cmd,seq,b=parse_frame(bytes.fromhex(row['rx_hex']));assert seq==item['seq'],item['name']
        if item['kind']=='info':
            assert cmd==0x81 and len(b)==32
            v=struct.unpack('<8I',b)
            assert v[:6]==(int(BUILD,16),50000000,0x52563031,0x444f5431,1024,15),v
            if dots is None: dots=v[6];timeouts=v[7]
            assert (v[6],v[7])==(dots,timeouts),(item['name'],v)
        elif item['kind']=='error':
            assert cmd==0xff and len(b)==8 and struct.unpack('<II',b)[0]==item['error'],(item['name'],b.hex())
            if item['error']==5:timeouts+=1
            errors+=1
        elif item['kind']=='dot':
            v=parse_dot(b);r=reference_dot(item['a'],item['b']);dots+=1;dot_count+=1
            assert cmd==0x82 and v['software']==v['hardware']==r and v['flags']==0
            assert v['n']==len(item['a']) and v['completed']==dots and v['accelerator_status']==2 and v['hardware_core_cycles']==len(item['a'])+2
        elif item['kind']=='trace':
            k=item['offset'];count=item['count'];assert last_stats is not None
            assert cmd==0x84 and struct.unpack_from('<HH',b)==(k,count)
            assert list(struct.iter_unpack('<iI',b[4:]))==last_stats[k:k+count],item['name']
            traced+=count
        else:
            command,_,raw=parse_frame(bytes.fromhex(item['tx_hex']));assert command in (3,5,6,7,8,9)
            fast=command in (7,9);multi=command in (8,9)
            n,flags=struct.unpack_from('<HH',raw);assert flags==0
            x=list(struct.unpack('<'+'h'*n,raw[4:]));stats=oracle(x);peak=decide(stats);w=n-63
            expected=[int(peak['detected']),peak['position'] if peak['position'] is not None else NONE,
                      peak['candidate_position'] if peak['candidate_position'] is not None else NONE,peak['score']&NONE,peak['window_energy']]
            assert cmd==command+0x80 and len(b)==(224 if multi else 112),(item['name'],b.hex())
            v=list(struct.unpack('<'+'I'*(len(b)//4),b));crc=zlib.crc32(b''.join(struct.pack('<iI',s,e) for s,e in stats))
            assert v[:3]==[n,w,NONE if fast else 0] and v[9:14]==expected,(item['name'],v[:14],expected)
            assert v[4:9]==([NONE]*5 if fast else expected)
            assert v[20:22]==([NONE]*2 if fast else [crc,crc])
            assert (v[14]==NONE if fast else 0<v[14]<NONE)
            targets=select_targets(stats) if multi else []
            passes=min(3,len(targets)) if multi else 0
            assert v[15]>v[16] and v[16]==66*w+(0 if command==5 else 4)+(6*w+1)*passes,(item['name'],'core',v[16],passes)
            if multi:
                slots=[]
                for k in range(4):
                    slots.extend([targets[k]['position'],targets[k]['score']&NONE,targets[k]['window_energy']] if k<len(targets) else [NONE,0,0])
                assert v[28:32]==[NONE if fast else len(targets),len(targets),4,0],(item['name'],v[28:32])
                assert v[32:44]==([NONE]*12 if fast else slots) and v[44:56]==slots,(item['name'],'target list',v[32:],slots)
            if total is None:total=v[22]-1
            total+=1;assert v[22:25]==[total,2,int(BUILD,16)]
            if command!=5:
                if scans is None:scans=v[27]-1
                scans+=1
                if template_expected is not None:assert v[3]==template_expected
                template_expected=0
                assert v[25:28]==[n,64,scans] and v[3] in [0,1]
            else:assert v[3]==1 and v[17:20]==[NONE]*3 and v[25:]==[64*w,64*w,w]
            result=dict(name=item['name'],group=item.get('group','correctness'),mode={3:'cpu_reduce',5:'legacy',6:'peak_verify',7:'peak_fast',8:'multi_verify',9:'multi_fast'}[command],
                n=n,windows=w,detected=peak['detected'],position=peak['position'],candidate_position=peak['candidate_position'],
                score=peak['score'],window_energy=peak['window_energy'],correlation_abs=peak['correlation_abs'],
                software_cycles=None if fast else v[14],hardware_total_cycles=v[15],core_cycles=v[16],template_transfer=v[3],
                template_phase_cycles=None if v[17]==NONE else v[17],frame_copy_cycles=None if v[18]==NONE else v[18],
                read_reduce_cycles=None if v[19]==NONE else v[19],frame_writes=v[25],template_writes=v[26],
                stats_crc=None if fast else crc,completed=v[22],host_ms=row.get('host_ms'),status='PASS')
            if multi:
                result['targets']=targets; result['target_count']=len(targets)
                if 'expected_positions' in item:
                    truth=item['expected_positions'];found=[t['position'] for t in targets]
                    result['expected_positions']=truth
                    result['target_hits']=len(set(truth)&set(found))
                    result['target_misses']=len(set(truth)-set(found))
                    result['target_false_alarms']=len(set(found)-set(truth))
            for k in ['expected_position','snr_db','clipped_samples','actual_window_snr_db','repeat']:
                if k in item: result[k]=item[k]
            records.append(result);last_stats=stats;windows+=w if not fast else 0;evaluated+=w
    return records,dict(transactions=len(rows),detection_frames=len(records),windows_compared=windows,windows_evaluated=evaluated,
        fast_frames=sum(x['mode'] in ('peak_fast','multi_fast') for x in records),traced_windows=traced,rejected_requests=errors,legacy_dots=dot_count,receive_timeouts=timeouts)

def summarize(records):
    negative=[x for x in records if x['group']=='noise_only'];positions=[x for x in records if x['group']=='positions']
    curve=[]
    for snr in [-6,-3,0,3,6,12]:
        group=[x for x in records if x['group']=='noisy_target' and x['snr_db']==snr]
        if group:
            hits=sum(x['detected'] and x['position']==x['expected_position'] for x in group)
            misses=sum(not x['detected'] for x in group)
            curve.append(dict(snr_db=snr,frames=len(group),exact_hits=hits,misses=misses,mislocalized=len(group)-hits-misses))
    performance=[]
    for n in LENGTHS:
        for mode in ['peak_verify','multi_verify','multi_fast']:
            group=[x for x in records if x['group']=='performance' and x['n']==n and x['mode']==mode]
            if group:
                assert len(group)==REPEATS
                item=dict(n=n,mode=mode,repeats=len(group))
                for key in ['software_cycles','hardware_total_cycles','core_cycles','host_ms']:
                    values=[x[key] for x in group if x[key] is not None]
                    if not values:continue
                    item[key+'_min']=min(values);item[key+'_median']=statistics.median(values);item[key+'_max']=max(values)
                if mode=='multi_fast':
                    reference=[x['software_cycles'] for x in records if x['group']=='performance' and x['n']==n and x['mode']=='multi_verify']
                    item['software_cycles_median']=statistics.median(reference)
                item['software_measured_in_request']=mode!='multi_fast'
                item['software_ms']=item['software_cycles_median']/50000
                item['hardware_ms']=item['hardware_total_cycles_median']/50000
                item['speedup_vs_cpu']=item['software_ms']/item['hardware_ms']
                # UART floor includes request and fixed response only; it excludes all computation.
                item['uart_wire_floor_ms']=(2*n+20+(240 if mode.startswith('multi') else 128))*10*1000/115200
                performance.append(item)
    multi_groups=[]
    for name in sorted({x['group'] for x in records if 'targets' in x and x['group'].startswith('multi_')}):
        g=[x for x in records if x['group']==name and 'target_hits' in x]
        if g: multi_groups.append(dict(group=name,frames=len(g),targets=sum(len(x['expected_positions']) for x in g),
            hits=sum(x['target_hits'] for x in g),misses=sum(x['target_misses'] for x in g),false_alarms=sum(x['target_false_alarms'] for x in g)))
    return dict(multi_groups=multi_groups,curve=curve,negative_frames=len(negative),false_alarms=sum(x['detected'] for x in negative),
        position_frames=len(positions),position_hits=sum(x['detected'] and x['position']==x['expected_position'] for x in positions),performance=performance)

def run(phase,port='COM9',scenario=None,fresh=False,label=None,quiet=False):
    lock=ROOT/'board/results/.detection_a3_serial.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(json.dumps(dict(phase=phase,timestamp=datetime.now(timezone.utc).isoformat())))
    except FileExistsError:raise RuntimeError('串口正在执行另一项评测，请稍后重试。')
    try:return run_unlocked(phase,port,scenario,fresh,label,quiet)
    finally:lock.unlink()

def run_unlocked(phase,port='COM9',scenario=None,fresh=False,label=None,quiet=False):
    plan=make_plan(phase,scenario);stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out=ROOT/'board/results'/f'detection_a5_{label or phase}_{stamp}';out.mkdir(parents=True)
    dump(out/'plan.json',plan)
    summary=dict(status='FAIL',physical_board=True,phase=phase,label=label,build_id=BUILD,port=port,baud=115200,
        clock_hz=50000000,timestamp=datetime.now(timezone.utc).isoformat(),fresh=fresh,error=None)
    start=time.perf_counter()
    if not quiet: print(str(out),flush=True)
    try:
        proc=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'src/host/detection_transport.ps1'),
            '-Port',port,'-Plan',str(out/'plan.json'),'-OutputDirectory',str(out)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace')
        (out/'transport_console.log').write_text(proc.stdout,encoding='utf-8')
        if proc.returncode: raise RuntimeError('Serial transport failed; inspect '+str(out/'transport.json'))
        rows=[json.loads(x) for x in (out/'responses.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        records,counts=verify(plan,rows,fresh);stats=summarize(records)
        if phase=='all':
            assert stats['negative_frames']==1000 and stats['false_alarms']<=10
            assert stats['position_frames']==stats['position_hits']==961
            assert all(x['exact_hits']>=198 for x in stats['curve'] if x['snr_db'] in (6,12))
        dump(out/'verified_cases.json',records);write_csv(out/'measurements.csv',records)
        write_csv(out/'performance.csv',stats['performance']);write_csv(out/'noise_curve.csv',stats['curve'])
        summary.update(status='PASS',**counts,**stats)
        if phase=='demo':
            c=make_signal(**scenario);r=records[0]
            board_statistics=[]
            for item,row in zip(plan,rows):
                if item['kind']=='trace':
                    _,_,body=parse_frame(bytes.fromhex(row['rx_hex']))
                    offset,count=struct.unpack_from('<HH',body)
                    assert offset==len(board_statistics) and len(body)==4+8*count
                    board_statistics.extend(struct.iter_unpack('<iI',body[4:]))
            assert len(board_statistics)==r['windows']
            payload=dict(**c,result=r,statistics=board_statistics,run_id=out.name,timestamp=summary['timestamp'],build_id=BUILD,
                         source='physical_board',status='PASS')
            dump(out/'demo.json',payload)
    except Exception as exc: summary['error']=str(exc);raise
    finally:
        summary['elapsed_seconds']=time.perf_counter()-start;dump(out/'summary.json',summary)
    if not quiet:print(json.dumps(summary,ensure_ascii=False),flush=True)
    return out,summary

def peak_words(stats):
    p=decide(stats)
    return [int(p['detected']),p['position'] if p['position'] is not None else NONE,
            p['candidate_position'] if p['candidate_position'] is not None else NONE,p['score']&NONE,p['window_energy']]


def prepare_unit():
    cases=[(0,c) for c in inputs()]+[(1,c) for c in multi_inputs()]
    rng=random.Random(0xA501)
    for n in [65,66,127,129,255,257,511,513,1023]:
        cases.append((1,dict(samples=[rng.randint(-2048,2047) for _ in range(n)])))
    work=ROOT/'sim/work/window_a5';work.mkdir(parents=True,exist_ok=True);windows=0
    with (work/'unit_vectors.txt').open('w',encoding='ascii') as f:
        f.write(str(len(cases))+'\n'+'\n'.join(map(str,TEMPLATE))+'\n')
        for multi,c in cases:
            x=c['samples'];stats=oracle(x);windows+=len(stats);targets=select_targets(stats)[:4 if multi else 1]
            f.write(f'{len(x)} {multi}\n'+'\n'.join(map(str,x))+'\n')
            f.writelines(f'{a} {b}\n' for a,b in stats)
            f.writelines(f'{v:08x}\n' for v in peak_words(stats))
            f.write(str(len(targets))+'\n')
            for i in range(4):
                values=[targets[i]['position'],targets[i]['score']&NONE,targets[i]['window_energy']] if i<len(targets) else [NONE,0,0]
                f.writelines(f'{v:08x}\n' for v in values)
    dump(work/'oracle.json',dict(frames=len(cases),windows=windows,a1_frames=3172,multi_frames=len(multi_inputs()),
        vectors_sha256=hashlib.sha256((work/'unit_vectors.txt').read_bytes()).hexdigest()))
    print('PASS: prepared A5 vectors',len(cases),windows)


def prepare_selector():
    # Legal-width arithmetic edges, including exact threshold and exact ratio ties.
    cases=[[(0,0)],[(0,1)],[(56,100)],[(55,100)],[(57,100)],
           [(10,100),(-20,400)],[(0,0),(-131072,268435456),(131072,268435456)],
           [(131071,268435456),(131072,268435456)],[(56,100),(0,0),(-57,100)]]
    rng=random.Random(0xA502)
    for _ in range(1000):
        stats=[]
        for _ in range(rng.randint(1,32)):
            energy=rng.randint(1,1<<28)
            maximum=min(1<<17,math.isqrt(64*energy))
            stats.append((rng.randint(-maximum,maximum),energy))
        cases.append(stats)
    work=ROOT/'sim/work/selector_a5';work.mkdir(parents=True,exist_ok=True)
    with (work/'selector_vectors.txt').open('w',encoding='ascii') as f:
        f.write(str(len(cases))+'\n')
        for stats in cases:
            f.write(str(len(stats))+'\n')
            f.writelines(f'{a} {b}\n' for a,b in stats)
            f.writelines(f'{v:08x}\n' for v in peak_words(stats))
    dump(work/'oracle.json',dict(cases=len(cases),statistics=sum(map(len,cases)),vectors_sha256=hashlib.sha256((work/'selector_vectors.txt').read_bytes()).hexdigest()))
    print('PASS: prepared A5 exact reducer vectors',len(cases))


def prepare_sim():
    work=ROOT/f'sim/work/detection_{BUILD}';work.mkdir(parents=True,exist_ok=True);plan=make_plan('sim');dump(work/'plan.json',plan)
    with (work/'stimulus.txt').open('w',encoding='ascii') as f:
        for p in plan:
            b=bytes.fromhex(p['tx_hex']);f.write(f"{len(b)} {p['response_bytes']} {int(p['reset_before'])}\n")
            f.writelines(f'{v:02x}\n' for v in b)
    print('PASS: A5 integrated stimulus',len(plan))

def verify_sim():
    work=ROOT/f'sim/work/detection_{BUILD}';plan=json.loads((work/'plan.json').read_text())
    rows=[json.loads(x) for x in (work/'responses.jsonl').read_text().splitlines()]
    records,counts=verify(plan,rows,True);dump(work/'verified_cases.json',records)
    dump(work/'summary.json',dict(status='PASS',physical_board=False,build_id=BUILD,**counts));print('PASS: A5 independent integrated verification',counts)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['all','recovery','probe','prepare-sim','verify-sim','prepare-unit','prepare-selector'])
    p.add_argument('--port',default='COM9');p.add_argument('--fresh',action='store_true');p.add_argument('--label');args=p.parse_args()
    if args.phase=='prepare-unit':prepare_unit()
    elif args.phase=='prepare-selector':prepare_selector()
    elif args.phase=='prepare-sim':prepare_sim()
    elif args.phase=='verify-sim':verify_sim()
    else:run(args.phase,args.port,fresh=args.fresh,label=args.label)
