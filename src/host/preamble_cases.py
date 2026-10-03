"""Frozen synthetic packet inputs. Generation does not call a detector."""
import hashlib
import math
import random
from signal_detection_reference import TEMPLATE

CONFIG = {
    'schema': 1, 'name': 'application_preamble_v1', 'build_id': '0000A501',
    'seed_namespace': 'a602_20260925_final_packets', 'length': 1024,
    'preamble_length': 64, 'payload_length': 128, 'threshold': '0.70', 'capacity': 4,
    'core_amplitudes': [128, 256, 512, 768], 'core_snr_db': [6, 12],
    'core_repeats_per_count_snr': 60,
    'tone_frequencies_cycles_per_sample': [1/64, 1/16, 1/8, 1/4, 3/8],
    'tone_amplitudes': [128, 256, 512, 1024, 1536],
    'tone_phases': [0, math.pi/2, math.pi, 3*math.pi/2],
    'negative_noise_sigmas': [32, 64, 128, 256, 512],
    'stress_snr_db': [-6, -3, 0, 3, 6],
    'stress_dc_ratios': [0, .25, .5, 1, 2],
    'stress_amplitude_ratios': [1, 2, 4, 6, 8],
    'stress_sir_db': [None, 12, 6, 0, -6],
    'stress_impulse_probabilities': [0, 1/256, 1/128, 1/64, 1/32],
    'performance_case': 'core_q4_s6_r00', 'performance_repeats': 30,
    'trace_cases': ['core_q1_s6_r00', 'core_q2_s6_r00', 'core_q3_s6_r00',
        'core_q4_s6_r00', 'negative_payload_000', 'negative_other_000',
        'negative_tone_000', 'negative_impulse_000', 'stress_snr_l0_r00',
        'stress_dc_l4_r00', 'stress_ratio_l4_r00', 'stress_tone_l4_r00',
        'stress_impulse_l4_r00', 'boundary_capacity_00', 'boundary_cross_0_0',
        'boundary_cross_0_1', 'boundary_overlap_00', 'boundary_similar_00'],
    'gates': {'core_each_group_recall_min': .98, 'core_each_group_precision_min': .99,
              'negative_frame_false_alarm_rate_max': .01},
    'snr_definition': 'Per-preamble clean component energy / AWGN energy before quantization and clipping; interference is reported separately.',
    'sample_model': 'One real sample per symbol after assumed timing/carrier recovery; no RF or continuous-stream claim.',
}


def seed(label):
    return int.from_bytes(hashlib.sha256((CONFIG['seed_namespace']+':'+label).encode()).digest()[:8], 'little')


def rng(label):
    return random.Random(seed(label))


def packets(label, count, amplitudes=None, positions=None, length=1024, preamble=None, payload_length=128):
    r = rng(label+':packet')
    total = 64+payload_length
    if positions is None:
        slack = length-total*count
        assert slack >= 0
        cuts = [0]+sorted(r.randrange(slack+1) for _ in range(count))+[slack]
        gaps = [b-a for a,b in zip(cuts,cuts[1:])]
        positions = []
        start = gaps[0]
        for j in range(count):
            positions.append(start)
            start += total+gaps[j+1]
    amps = amplitudes or [r.choice(CONFIG['core_amplitudes']) for _ in range(count)]
    clean = [0]*length
    events = []
    for j, (start, amp) in enumerate(zip(positions, amps)):
        sign = r.choice([-1,1])
        code = list(TEMPLATE if preamble is None else preamble)
        body = [r.choice([-1,1]) for _ in range(payload_length)]
        for k, v in enumerate(code+body):
            if 0 <= start+k < length:
                clean[start+k] += amp*sign*v
        events.append(dict(start=start, end=start+total, amplitude=amp, polarity=sign,
                           target=preamble is None, complete_preamble=0<=start<=length-64))
    return clean, events


def noise(label, sigma, length=1024):
    r = rng(label+':noise')
    return [r.gauss(0,1)*sigma for _ in range(length)]


def finish(case_id, group, clean, events, awgn, interference=None, **meta):
    interference = interference or [0]*len(clean)
    raw = [round(a+b+c) for a,b,c in zip(clean,awgn,interference)]
    samples = [max(-2048,min(2047,v)) for v in raw]
    truth = sorted(e['start'] for e in events if e['target'] and e['complete_preamble'])
    for event in events:
        k = event['start']
        if event['complete_preamble']:
            en = sum(x*x for x in awgn[k:k+64])
            ei = sum(x*x for x in interference[k:k+64])
            signal = 64*event['amplitude']**2
            event['snr_db_actual'] = 10*math.log10(signal/en) if en else None
            event['sinr_db_actual'] = 10*math.log10(signal/(en+ei)) if en+ei else None
    return dict(id=case_id, group=group, samples=samples, expected_positions=truth,
                expected_position=truth[0] if len(truth)==1 else None, packets=events,
                clipped_samples=sum(a!=b for a,b in zip(raw,samples)), metadata=meta)


def make_cases():
    out = []
    for count in range(1,5):
        for snr in CONFIG['core_snr_db']:
            for rep in range(60):
                name = f'core_q{count}_s{snr}_r{rep:02d}'
                clean, events = packets(name,count)
                sigma = min(e['amplitude'] for e in events)/10**(snr/20)
                out.append(finish(name,'core',clean,events,noise(name,sigma),
                    count=count, snr_db=snr, sigma=sigma, support='complete_nonoverlapping_packets'))
    for i in range(200):
        name = f'negative_noise_{i:03d}'
        sigma = CONFIG['negative_noise_sigmas'][i%5]
        out.append(finish(name,'negative_noise',[0]*1024,[],noise(name,sigma),sigma=sigma))
    for i in range(400):
        name = f'negative_payload_{i:03d}'
        r = rng(name); amp = CONFIG['core_amplitudes'][i%4]
        clean = [amp*r.choice([-1,1]) for _ in range(1024)]
        burst = i%2 == 1
        if burst:
            clean = [v if (k//128)%2 else 0 for k,v in enumerate(clean)]
        out.append(finish(name,'negative_payload',clean,[],noise(name,128),amplitude=amp,burst=burst,sigma=128))
    for i in range(200):
        name = f'negative_other_{i:03d}'
        r = rng(name); other = [1]*32+[-1]*32
        while True:
            r.shuffle(other)
            if tuple(other) not in (TEMPLATE,tuple(-x for x in TEMPLATE)): break
        clean, events = packets(name,1+i%4,preamble=other)
        out.append(finish(name,'negative_other',clean,events,noise(name,128),other_preamble=other,sigma=128))
    i = 0
    for freq in CONFIG['tone_frequencies_cycles_per_sample']:
        for amp in CONFIG['tone_amplitudes']:
            for phase in CONFIG['tone_phases']:
                name = f'negative_tone_{i:03d}'; i += 1
                wave = [amp*math.sin(2*math.pi*freq*k+phase) for k in range(1024)]
                out.append(finish(name,'negative_tone',[0]*1024,[],noise(name,64),wave,
                                  frequency=freq,amplitude=amp,phase=phase,sigma=64))
    for i in range(100):
        name = f'negative_impulse_{i:03d}'; r = rng(name)
        amp = [128,256,512,1024,1800][i%5]; density = [1/512,1/256,1/128,1/64,1/32][(i//5)%5]
        uniform = [r.random() for _ in range(1024)]; signs = [r.choice([-1,1]) for _ in range(1024)]
        pulse = [amp*s if u<density else 0 for u,s in zip(uniform,signs)]
        clustered = i>=50
        if clustered:
            for k in range(1023,0,-1):
                if pulse[k-1] and not pulse[k]: pulse[k]=pulse[k-1]
        out.append(finish(name,'negative_impulse',[0]*1024,[],noise(name,64),pulse,
                          amplitude=amp,probability=density,clustered=clustered,sigma=64))
    levels = {'snr':CONFIG['stress_snr_db'], 'dc':CONFIG['stress_dc_ratios'],
              'ratio':CONFIG['stress_amplitude_ratios'], 'tone':CONFIG['stress_sir_db'],
              'impulse':CONFIG['stress_impulse_probabilities']}
    for kind, values in levels.items():
        for rep in range(8):
            base = f'stress_{kind}_paired_{rep}'
            for level, value in enumerate(values):
                name = f'stress_{kind}_l{level}_r{rep:02d}'
                amps = [768,768//value] if kind=='ratio' else [256]*3
                clean, events = packets(base,len(amps),amplitudes=amps)
                if kind=='ratio': events[1]['role']='weak_designated'
                sigma = 256/10**(value/20) if kind=='snr' else 128
                interference = [0]*1024; extra = {}
                if kind=='dc': interference = [256*value*(1 if rep%2==0 else -1)]*1024
                if kind=='tone':
                    amp = 0 if value is None else math.sqrt(2)*256/10**(value/20)
                    phase = rep*math.pi/4
                    interference = [amp*math.sin(2*math.pi*k/16+phase) for k in range(1024)]
                    extra = dict(frequency=1/16,phase=phase,amplitude=amp)
                if kind=='impulse':
                    r = rng(base+':impulse'); u=[r.random() for _ in range(1024)]; s=[r.choice([-1,1]) for _ in range(1024)]
                    interference = [1536*sign if v<value else 0 for v,sign in zip(u,s)]
                    extra = dict(amplitude=1536)
                out.append(finish(name,'stress_'+kind,clean,events,noise(base,sigma),interference,
                                  pair=base,level=level,value=value,sigma=sigma,**extra))
    for rep in range(6):
        name=f'boundary_capacity_{rep:02d}'
        clean,events=packets(name,5,amplitudes=[256]*5)
        out.append(finish(name,'boundary_capacity',clean,events,noise(name,64),support='five_targets_capacity_four'))
    for pair, start in enumerate([1008,992,976]):
        base=f'boundary_cross_pair_{pair}'
        clean,events=packets(base,1,amplitudes=[256],positions=[start],length=2048)
        awgn=noise(base,64,length=2048)
        for block in range(2):
            event=dict(events[0]);event['start']-=1024*block;event['end']-=1024*block
            event['complete_preamble']=0<=event['start']<=960
            out.append(finish(f'boundary_cross_{pair}_{block}','boundary_cross',clean[1024*block:1024*(block+1)],
                [event],awgn[1024*block:1024*(block+1)],pair=base,block=block,global_start=start,support='no_cross_block_buffer'))
    for rep,gap in enumerate([1,16,31,48,63,64]):
        name=f'boundary_overlap_{rep:02d}'
        clean,events=packets(name,2,amplitudes=[256,256],positions=[128,128+gap],payload_length=0)
        out.append(finish(name,'boundary_overlap',clean,events,[0]*1024,gap=gap,
                          support='overlapping_preambles' if gap<64 else 'nonoverlap_control'))
    for rep,flips in enumerate([8,9,10,16,55,56]):
        name=f'boundary_similar_{rep:02d}'; other=list(TEMPLATE)
        for k in rng(name).sample(range(64),flips):other[k]*=-1
        clean,events=packets(name,1,amplitudes=[256],positions=[128],preamble=other,payload_length=0)
        out.append(finish(name,'boundary_similar',clean,events,[0]*1024,flips=flips,
                          expected_window_abs_correlation=abs(64-2*flips)/64,support='similar_non_target'))
    assert len(out)==1704 and len({c['id'] for c in out})==1704
    assert sum(len(c['expected_positions']) for c in out if c['group']=='core')==1200
    for c in out:
        assert len(c['samples'])==1024 and all(type(x) is int and -2048<=x<=2047 for x in c['samples'])
        assert len(set(c['expected_positions']))==len(c['expected_positions'])
    return out
