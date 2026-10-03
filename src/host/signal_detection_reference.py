"""Integer reference for improvement A. This module does not communicate with an FPGA."""
from math import sqrt

TEMPLATE=(1,1,-1,1,1,1,1,1,-1,-1,-1,1,1,1,-1,-1,1,1,-1,-1,-1,-1,1,1,
          -1,1,1,1,-1,-1,-1,1,-1,1,1,-1,-1,1,-1,1,-1,1,-1,-1,1,-1,1,-1,
          1,-1,-1,1,-1,-1,1,-1,-1,1,1,1,-1,-1,-1,1)
WINDOW=64
MAX_LENGTH=1024
MIN_SAMPLE=-2048
MAX_SAMPLE=2047
THRESHOLD_NUMERATOR=7
THRESHOLD_DENOMINATOR=10


def check_input(samples):
    if not WINDOW<=len(samples)<=MAX_LENGTH:
        raise ValueError('Detection frame length must be 64..1024')
    if any(type(v) is not int or not MIN_SAMPLE<=v<=MAX_SAMPLE for v in samples):
        raise ValueError('Detection samples must be integers in -2048..2047')


def scan(samples):
    """Direct integer dot products and rolling energy; returns one (S,E) per valid start."""
    check_input(samples)
    energy=sum(v*v for v in samples[:WINDOW])
    statistics=[]
    for start in range(len(samples)-WINDOW+1):
        if start:
            energy+=samples[start+WINDOW-1]**2-samples[start-1]**2
        dot=sum(samples[start+i]*TEMPLATE[i] for i in range(WINDOW))
        statistics.append((dot,energy))
    return statistics


def decide(statistics):
    """Choose the earliest maximum squared correlation using exact integer products."""
    best=None
    best_dot=best_energy=0
    for position,(dot,energy) in enumerate(statistics):
        if not energy:
            continue
        if best is None or dot*dot*best_energy>best_dot*best_dot*energy:
            best=position
            best_dot,best_energy=dot,energy
    detected=best is not None and THRESHOLD_DENOMINATOR**2*best_dot**2>=THRESHOLD_NUMERATOR**2*WINDOW*best_energy
    return dict(detected=detected,position=best if detected else None,candidate_position=best,
                score=best_dot,window_energy=best_energy,
                polarity=(1 if best_dot>0 else -1 if best_dot<0 else 0),
                correlation_abs=abs(best_dot)/sqrt(WINDOW*best_energy) if best_energy else None)


def detect(samples):
    return decide(scan(samples))
