#!/usr/bin/env python3
"""
Check numeric claims in thesis_contributions.md against the committed experiment
JSONs that each entry references.

    .venv/bin/python3 scripts/verify_contributions.py 29 30 33 34
    .venv/bin/python3 scripts/verify_contributions.py $(seq 29 67)

For each contribution it pools every number appearing anywhere in that entry's
experiment JSONs, then checks each table cell and each bold figure against the
pool at 1.2% tolerance, also trying common unit shifts (x100, x1e4, /24, ...).

Read the output as a screen, not a proof. Unmatched values are frequently
legitimate: derived quantities (differences, standard deviations, ratios), date
fragments parsed as negative numbers, and cross-references to experiments the
entry does not list. A large unmatched count on an entry whose numbers should
all be primary is the signal worth chasing -- that is how C34 was caught
quoting a superseded pre-engine-fix table.
"""
import re,glob,os,json,sys
from collections import defaultdict

body=open('thesis_contributions.md').read()
parts=re.split(r'\n## (?:C(\d+) — |(\d+)\. )',body)
ent={}
for i in range(1,len(parts),3):
    n=int(parts[i] or parts[i+1]); ent[n]=parts[i+2]

def nums_in_json(obj,out):
    if isinstance(obj,dict):
        for v in obj.values(): nums_in_json(v,out)
    elif isinstance(obj,list):
        for v in obj: nums_in_json(v,out)
    elif isinstance(obj,(int,float)) and obj==obj:
        out.add(abs(float(obj)))

def data_nums(exps):
    out=set()
    for e in exps:
        for d in glob.glob(f'experiments/{e}_*')+glob.glob(f'experiments/{e.zfill(2)}_*'):
            for f in glob.glob(os.path.join(d,'**','*.json'),recursive=True):
                if os.path.getsize(f)>8_000_000: continue
                try: nums_in_json(json.load(open(f)),out)
                except Exception: pass
    return out

def claim_nums(text):
    """numbers appearing in bold or in markdown tables -- the load-bearing ones"""
    cands=set()
    for line in text.split('\n'):
        if line.strip().startswith('|'):
            for m in re.findall(r'[-+]?\$?\d[\d,]*\.?\d*',line):
                cands.add(m)
    for m in re.findall(r'\*\*([-+]?\$?\d[\d,]*\.?\d*)[%a-zA-Z]*\*\*',text):
        cands.add(m)
    out=set()
    for c in cands:
        try: v=abs(float(c.replace('$','').replace(',','').replace('+','')))
        except ValueError: continue
        if v==0 or v>1e7: continue
        out.add((c,v))
    return out

def matches(v,pool):
    for p in pool:
        if p==0: continue
        if abs(v-p)<=max(1e-9,0.012*abs(v)): return True          # 1.2% tolerance
        for s in (100.0,1e4,0.01,1e-4,1000.0,0.001,24.0,1/24):     # unit/scale shifts
            if abs(v-p*s)<=max(1e-9,0.012*abs(v)): return True
    return False

targets=[int(a) for a in sys.argv[1:]]
for n in targets:
    t=ent.get(n,'')
    exps=sorted(set(re.findall(r'exps?\s+(\d+)',t))|set(re.findall(r'experiments/(\d+)_',t)),key=int)
    pool=data_nums(exps)
    if not pool:
        print(f"C{n}: NO DATA ({exps})"); continue
    cl=claim_nums(t)
    miss=[c for c,v in sorted(cl,key=lambda x:-x[1]) if not matches(v,pool)]
    hit=len(cl)-len(miss)
    flag="OK " if not miss else ("CHECK" if len(miss)<=max(2,0.25*len(cl)) else "**MISMATCH**")
    print(f"C{n:<3} exps={','.join(exps):<18} pool={len(pool):<5} claims={len(cl):<3} matched={hit:<3} {flag}")
    if miss: print(f"      unmatched: {', '.join(miss[:14])}")
