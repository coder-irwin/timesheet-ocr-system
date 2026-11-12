"""Resume the seeded 50-page sample from a given index (same seed/selection as tools/render_sample50.sh).
Pages whose PDF cannot be opened are recorded in the manifest with status 'source_unreadable'."""
import json, random, hashlib, sys, pickle, time
sys.path.insert(0,'.'); sys.path.insert(0,'tools')
from pathlib import Path
import pypdfium2 as pdfium
from app import pipeline
import eval_fast as ef
START=int(sys.argv[1]) if len(sys.argv)>1 else 0
seen=set()
for fz in (ef.FROZEN, ef.FROZEN.with_name('frozen_v2.pkl')):
    for f in pickle.loads(fz.read_bytes()): seen.add((f['pdf'].split('/')[-1], f['page']))
for m in json.load(open('data/_manual_verify/manifest.json')): seen.add((Path(m['src']).name, m['page']))
rows=[json.loads(l) for l in open('handwritten_corpus/records.jsonl') if l.strip()]
random.seed(2026)
def pick(pred,k):
    c=[r for r in rows if pred(r) and (Path(r['source']).name, r['page']) not in seen and r.get('verdict') in ('handwritten','typed')]
    random.shuffle(c); return c[:k]
hw=lambda r: r['verdict']=='handwritten' and (r.get('ink',{}).get('body_p25') or 1)<0.85
ty=lambda r: r['verdict']=='typed' or (r.get('ink',{}).get('body_p25') or 0)>=0.95
sample = pick(lambda r: r['dataset']=='Delhi' and hw(r),10)+pick(lambda r: r['dataset']=='Delhi' and ty(r),8) \
       + pick(lambda r: r['dataset']=='HO' and hw(r),8)+pick(lambda r: r['dataset']=='HO' and ty(r),8) \
       + pick(lambda r: r['dataset']=='Kolkata' and hw(r),8)+pick(lambda r: r['dataset']=='Kolkata' and ty(r),8)
out=Path('data/_sample50'); mp=out/'manifest.json'
man=json.load(open(mp)) if mp.exists() else []
# sanity: the selection must reproduce what is already in the manifest
for m in man:
    assert m['src']==str(Path(sample[m['i']]['source'])) and m['page']==sample[m['i']]['page'], f"selection drift at s{m['i']:02d}"
have={m['i'] for m in man}; t0=time.time()
for i,r in enumerate(sample):
    if i<START or i in have: continue
    src=Path(r['source'])
    if not src.exists(): continue
    img=out/f"s{i:02d}_{r['dataset'][:1]}_{r['verdict'][:2]}.png"
    try:
        pg=pdfium.PdfDocument(str(src))[r['page']-1]; w,h=pg.get_size()
        pg.render(scale=1600/max(w,h)).to_pil().save(img)
    except Exception as e:
        man.append({"i":i,"img":None,"src":str(src),"page":r['page'],"dataset":r['dataset'],"verdict":r['verdict'],
                    "status":"source_unreadable","error":str(e)[:200],"days":[],"row_summary":{}})
        print(f"  s{i:02d} {r['dataset']:<8} {r['verdict']:<12} SOURCE UNREADABLE: {e}", flush=True)
        json.dump(man,open(mp,'w'),indent=1,default=str); continue
    res=pipeline.process_page(img,hashlib.sha1(img.read_bytes()).hexdigest(),force=True,source_hint=str(src))
    rec=res['record']
    man.append({"i":i,"img":str(img),"src":str(src),"page":r['page'],"dataset":r['dataset'],"verdict":r['verdict'],
                "name":rec.get('employee_name'),"code":rec.get('employee_code'),"period":rec.get('period_label'),"status":res['status'],
                "summary":rec.get('summary'),"row_summary":rec.get('_row_summary'),
                "days":[{k:d.get(k) for k in ('day','status','in_time','out_time','normal_hours','remarks','_review')} for d in rec.get('days') or []]})
    print(f"  s{i:02d} {r['dataset']:<8} {r['verdict']:<12} days={len(man[-1]['days'])} status={res['status']}  ({time.time()-t0:.0f}s)", flush=True)
    json.dump(man,open(mp,'w'),indent=1,default=str)
print(f"SAMPLE READY: {len(man)} pages", flush=True)
