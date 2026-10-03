"""Frozen input reader and independent NumPy integer correlation reference."""
import gzip
import json
from pathlib import Path
import numpy as np
from signal_detection_reference import TEMPLATE
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'data/detection_a1/run_20260925_142004_035903/input_frames.jsonl.gz'

def inputs():
    with gzip.open(DATA,'rt',encoding='utf-8') as f: return [json.loads(line) for line in f]

def oracle(x):
    a=np.asarray(x,dtype=np.int64)
    s=np.correlate(a,np.asarray(TEMPLATE,dtype=np.int64),'valid')
    e=np.convolve(a*a,np.ones(64,dtype=np.int64),'valid')
    return [(int(v),int(w)) for v,w in zip(s,e)]
