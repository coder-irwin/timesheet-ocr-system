"""Score a pipeline run against data/_sample50/truth.json (the 50-page hand-graded sample, D-045).
  python tools/eval_sample50.py                 # score the stored manifest (v32 baseline: 1076/1157, 10 silent)
  python tools/eval_sample50.py --run           # re-run the CURRENT code on the 38 readable images (~10 min), save, score
  python tools/eval_sample50.py --file X.json   # score a saved run
Reports strict, sheet-convention, silent wrong rows, missing, spurious, and per-page diffs vs the manifest."""
import json, sys, hashlib, time, collections
from pathlib import Path
sys.path.insert(0,'.')
T=json.load(open('data/_sample50/truth.json'))
def load_manifest():
    return {str(m['i']):{d['day']:d for d in m['days']} for m in json.load(open('data/_sample50/manifest.json'))}
def run_current(out):
    from app import pipeline
    if '--flags-off' in sys.argv:   # D-046 A/B: run the same harness with the v33 flags disabled
        from app import aarvi_form, vlm_header, rowconf
        aarvi_form.GRID_BOTTOM_FROM_DATES=False; pipeline.DROP_EMPTY_IMPOSSIBLE_DAYS=False
        vlm_header.VLM_CORROBORATE=False; rowconf.NO_DATE_COLUMN_CAPS_OK=False
    res={}; t0=time.time()
    for i,t in T.items():
        img=Path(t['img'])
        if '--normalise' in sys.argv:   # the product's real upload path (app/preprocess.normalise_page)
            from app import preprocess
            if '--no-median' in sys.argv: preprocess.ENHANCE_MEDIAN=False
            if '--no-clahe' in sys.argv: preprocess.ENHANCE_CLAHE=False
            if '--no-flatten' in sys.argv: preprocess.ENHANCE_FLATTEN=False
            dst=Path('data/_eval_tmp')/('n_'+img.name); dst.parent.mkdir(exist_ok=True); preprocess.normalise_page(img,dst); img=dst
        r=pipeline.process_page(img,hashlib.sha1(img.read_bytes()).hexdigest(),force=True)
        res[i]={d['day']:{k:d.get(k) for k in ('day','status','_review')} for d in r['record'].get('days') or []}
        print(f"  s{int(i):02d} {len(res[i])} rows ({time.time()-t0:.0f}s)",flush=True)
    json.dump({'version':pipeline.PIPELINE_VERSION,'pages':res},open(out,'w'),default=str)
    return res
def score(pages,label):
    R=RC=N=0; silent=missing=spur=0; per={}
    for i,t in T.items():
        got=pages.get(i,{}); got={int(k):v for k,v in got.items()}
        r=rc=s=ms=0
        for d,acc in t['days'].items():
            d=int(d); N+=1
            if d not in got: ms+=1; continue
            st=got[d].get('status') or ''
            if st==acc[0]: r+=1
            if st in acc: rc+=1
            elif got[d].get('_review')=='ok': s+=1
        sp=sum(1 for d in got if str(d) not in t['days'])
        R+=r; RC+=rc; silent+=s; missing+=ms; spur+=sp; per[i]=(r,t['N'],s,ms,sp)
    fl=collections.Counter(v.get('_review') for g in pages.values() for v in g.values())
    print(f"{label:<28} strict {R}/{N} = {100*R/N:.1f}%   conv {RC}/{N} = {100*RC/N:.1f}%   silent {silent}   missing {missing}   spurious {spur}   flags ok/review/must_fix {fl.get('ok',0)}/{fl.get('review',0)}/{fl.get('must_fix',0)}")
    return per
if __name__=='__main__':
    base=score(load_manifest(),'manifest (v32 baseline)')
    if '--run' in sys.argv or '--file' in sys.argv:
        if '--run' in sys.argv:
            out=Path('data/_sample50')/f"run_{time.strftime('%m%d_%H%M')}.json"; pages=run_current(out); print("saved",out)
        else:
            pages=json.load(open(sys.argv[sys.argv.index('--file')+1]))['pages']
        new=score(pages,'this run')
        for i in T:
            if base[i]!=new[i]: print(f"   s{int(i):02d}: right {base[i][0]}->{new[i][0]} /{base[i][1]}  silent {base[i][2]}->{new[i][2]}  missing {base[i][3]}->{new[i][3]}  spurious {base[i][4]}->{new[i][4]}")
