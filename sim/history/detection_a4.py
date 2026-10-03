"""Original A4 decoder and summary functions for retained timing evidence."""
import statistics
import struct
import zlib
from test_detection import oracle
from signal_detection_reference import decide
from vector_protocol import parse_frame, parse_dot, reference_dot
BUILD='0000A401'
LENGTHS=[64,128,256,512,1024]
REPEATS=30
NONE=0xffffffff

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
            command,_,raw=parse_frame(bytes.fromhex(item['tx_hex']));assert command in (3,5,6,7)
            n,flags=struct.unpack_from('<HH',raw);assert flags==0
            x=list(struct.unpack('<'+'h'*n,raw[4:]));stats=oracle(x);peak=decide(stats);w=n-63
            expected=[int(peak['detected']),peak['position'] if peak['position'] is not None else NONE,
                      peak['candidate_position'] if peak['candidate_position'] is not None else NONE,peak['score']&NONE,peak['window_energy']]
            assert cmd==command+0x80 and len(b)==112,(item['name'],b.hex())
            v=list(struct.unpack('<28I',b));crc=zlib.crc32(b''.join(struct.pack('<iI',s,e) for s,e in stats))
            assert v[:3]==[n,w,NONE if command==7 else 0] and v[9:14]==expected,(item['name'],v[:14],expected)
            assert v[4:9]==([NONE]*5 if command==7 else expected)
            assert v[20:22]==([NONE]*2 if command==7 else [crc,crc])
            assert (v[14]==NONE if command==7 else 0<v[14]<NONE)
            assert v[15]>v[16] and v[16]==66*w+(0 if command==5 else 4)
            if total is None:total=v[22]-1
            total+=1;assert v[22:25]==[total,2,int(BUILD,16)]
            if command!=5:
                if scans is None:scans=v[27]-1
                scans+=1
                if template_expected is not None:assert v[3]==template_expected
                template_expected=0
                assert v[25:]==[n,64,scans] and v[3] in [0,1]
            else:assert v[3]==1 and v[17:20]==[NONE]*3 and v[25:]==[64*w,64*w,w]
            result=dict(name=item['name'],group=item.get('group','correctness'),mode={3:'cpu_reduce',5:'legacy',6:'peak_verify',7:'peak_fast'}[command],
                n=n,windows=w,detected=peak['detected'],position=peak['position'],candidate_position=peak['candidate_position'],
                score=peak['score'],window_energy=peak['window_energy'],correlation_abs=peak['correlation_abs'],
                software_cycles=None if command==7 else v[14],hardware_total_cycles=v[15],core_cycles=v[16],template_transfer=v[3],
                template_phase_cycles=None if v[17]==NONE else v[17],frame_copy_cycles=None if v[18]==NONE else v[18],
                read_reduce_cycles=None if v[19]==NONE else v[19],frame_writes=v[25],template_writes=v[26],
                stats_crc=None if command==7 else crc,completed=v[22],host_ms=row.get('host_ms'),status='PASS')
            for k in ['expected_position','snr_db','clipped_samples','actual_window_snr_db','repeat']:
                if k in item: result[k]=item[k]
            records.append(result);last_stats=stats;windows+=w if command!=7 else 0;evaluated+=w
    return records,dict(transactions=len(rows),detection_frames=len(records),windows_compared=windows,windows_evaluated=evaluated,
        fast_frames=sum(x['mode']=='peak_fast' for x in records),traced_windows=traced,rejected_requests=errors,legacy_dots=dot_count,receive_timeouts=timeouts)

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
        for mode in ['cpu_reduce','peak_verify','peak_fast']:
            group=[x for x in records if x['group']=='performance' and x['n']==n and x['mode']==mode]
            if group:
                assert len(group)==REPEATS
                item=dict(n=n,mode=mode,repeats=len(group))
                for key in ['software_cycles','hardware_total_cycles','core_cycles','host_ms']:
                    values=[x[key] for x in group if x[key] is not None]
                    if not values:continue
                    item[key+'_min']=min(values);item[key+'_median']=statistics.median(values);item[key+'_max']=max(values)
                if mode=='peak_fast':
                    reference=[x['software_cycles'] for x in records if x['group']=='performance' and x['n']==n and x['mode']=='peak_verify']
                    item['software_cycles_median']=statistics.median(reference)
                item['software_measured_in_request']=mode!='peak_fast'
                item['software_ms']=item['software_cycles_median']/50000
                item['hardware_ms']=item['hardware_total_cycles_median']/50000
                item['speedup_vs_cpu']=item['software_ms']/item['hardware_ms']
                # UART floor includes request and fixed response only; it excludes all computation.
                item['uart_wire_floor_ms']=(2*n+20+128)*10*1000/115200
                performance.append(item)
    return dict(curve=curve,negative_frames=len(negative),false_alarms=sum(x['detected'] for x in negative),
        position_frames=len(positions),position_hits=sum(x['detected'] and x['position']==x['expected_position'] for x in positions),performance=performance)
