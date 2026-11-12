"""Temporary local status dashboard for the v33 end-to-end run.
   ./.venv/bin/python tools/dashboard.py   ->  http://127.0.0.1:8090
Read-only: reads logs and counters, computes rates/ETAs, never touches the pipeline."""
import json, subprocess, re, time, os, collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT = Path("."); os.chdir(ROOT)
EVAL_TOTAL, FULL_TOTAL = 1218, 7788
KOL_TOTAL = 1215
DEFAULT_RATE = {"eval": 3.8, "full": 12.0, "kol": 6.0}          # pages/min, measured 19 Sep
HIST = {"eval": collections.deque(maxlen=400), "full": collections.deque(maxlen=400), "kol": collections.deque(maxlen=400)}
LOGS = {"finisher": "data/finish_v33.log", "eval": "data/eval_corpus_v32.log", "supervisor": "data/eval_corpus_v32_supervisor.log",
        "watcher": "data/after_eval_v32.log", "full pass": "data/full_pass_v32.log", "demo server": "data/demo_server.log",
        "sample v33": "data/sample50_run_v33f.log", "dashboard": "data/dashboard.log"}
def sh(c):
    try: return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception: return ""
def tail(p, n=60):
    try: return [l.rstrip() for l in Path(p).read_text(errors="replace").splitlines()[-n:]]
    except Exception: return []
def count(p):
    try: return sum(1 for l in open(p) if l.strip())
    except Exception: return 0
HPATH = Path("data/dashboard_hist.json")
try:
    for k, v in json.load(open(HPATH)).items(): HIST[k].extend(tuple(x) for x in v)
except Exception: pass
def rate(key, n_now):
    # Rate over the longest window up to 45 min; "measured" only once >= 15 min of
    # samples exist, so a handful of slow pages cannot swing the ETA (history persists).
    h = HIST[key]; now = time.time()
    if not h or now - h[-1][0] >= 30: h.append((now, n_now))
    try: json.dump({k: list(v) for k, v in HIST.items()}, open(HPATH, "w"))
    except Exception: pass
    win = [s for s in h if 900 <= now - s[0] <= 2700]
    base = win[0] if win else None
    if base and n_now > base[1]:
        return (n_now - base[1]) / ((now - base[0]) / 60), "measured over %d min" % int((now - base[0]) / 60)
    return DEFAULT_RATE[key], "estimated"
def fmt_eta(mins):
    if mins is None: return "—"
    if mins < 1: return "under a minute"
    h, m = divmod(int(round(mins)), 60); return (f"{h} h {m} min" if h else f"{m} min")
def clock(mins): return time.strftime("%a %H:%M", time.localtime(time.time() + mins * 60)) if mins is not None else "—"
import threading
MACH = {"hist": collections.deque(maxlen=200), "now": {}}
def _machine_sample():
    top = sh("top -l 2 -n 0 -s 1 | tail -n 12")
    m = re.search(r"CPU usage: ([\d.]+)% user, ([\d.]+)% sys, ([\d.]+)% idle", top)
    cpu = round(100 - float(m.group(3)), 1) if m else None
    pm = re.search(r"PhysMem: (\S+) used \((\S+) wired, (\S+) compressor\), (\S+) unused", top)
    gpu = sh("ioreg -r -c IOAccelerator | grep -o '\"Device Utilization %\"=[0-9]*' | head -1 | grep -o '[0-9]*$'")
    gmem = sh("ioreg -r -c IOAccelerator | grep -o '\"In use system memory\"=[0-9]*' | head -1 | grep -o '[0-9]*$'")
    free = sh("memory_pressure | grep -o 'free percentage: [0-9]*' | grep -o '[0-9]*'")
    swap = sh("sysctl -n vm.swapusage | awk '{print $6}'")
    therm = sh("pmset -g therm | grep -i CPU_Speed_Limit | grep -o '[0-9]*$'")
    load = sh("uptime | sed 's/.*averages: //'")
    per = sh("ps -Ao pcpu,rss,args -r | awk 'NR>1 && $1>2 {printf \"%s|%s|%s\\n\",$1,$2,substr($0,index($0,$3),400)}' | head -14")
    top_procs = []
    for l in per.splitlines():
        try:
            c, r, a = l.split("|", 2)
            n = ("OCR worker" if "multiprocessing" in a else "ollama VLM" if "ollama" in a else "full-pass parent" if "full_pass" in a else "demo server" if "uvicorn" in a else "corpus eval" if "eval_corpus" in a else "dashboard" if "dashboard.py" in a else "docker VM" if "Virtualization" in a else a.split("/")[-1][:28])
            top_procs.append({"name": n, "cpu": float(c), "mb": int(int(r) / 1024)})
        except Exception: pass
    agg = collections.defaultdict(lambda: [0.0, 0, 0])
    for t in top_procs: agg[t["name"]][0] += t["cpu"]; agg[t["name"]][1] += t["mb"]; agg[t["name"]][2] += 1
    now = {"cpu": cpu, "gpu": int(gpu) if gpu.isdigit() else None, "gpu_mem_gb": round(int(gmem) / 1e9, 1) if gmem.isdigit() else None,
           "mem_free_pct": int(free) if free.isdigit() else None, "mem_used": pm.group(1) if pm else "?", "mem_compressed": pm.group(3) if pm else "?",
           "swap_used": swap, "cpu_speed_limit": int(therm) if therm.isdigit() else 100, "load": load, "ncpu": 10,
           "procs": sorted([{"name": k, "cpu": round(v[0], 1), "mb": v[1], "n": v[2]} for k, v in agg.items()], key=lambda x: -x["cpu"])[:9],
           "t": time.strftime("%H:%M:%S")}
    MACH["now"] = now; MACH["hist"].append((time.time(), cpu, now["gpu"]))
def _machine_loop():
    while True:
        try: _machine_sample()
        except Exception: pass
        time.sleep(3)
threading.Thread(target=_machine_loop, daemon=True).start()

def status():
    procs = {k: bool(sh(f"pgrep -f '{pat}'")) for k, pat in {
        "corpus eval": "tools/eval_corpus.py", "eval supervisor": "eval_corpus_supervised", "after-eval watcher": "after_eval_v32.sh",
        "finisher": "finish_v33.sh", "full pass": "full_pass_v32.py", "release build": "release_v33.sh", "demo server (8077)": "uvicorn app.main"}.items()}
    try: health = json.loads(sh("curl -s -m 3 http://127.0.0.1:8077/api/health"))
    except Exception: health = {}
    free = sh("vm_stat | awk '/Pages free/{f=$3}/Pages inactive/{i=$3}END{gsub(/\\./,\"\",f);gsub(/\\./,\"\",i);printf \"%.2f\",(f+i)*16384/1e9}'")
    oll = sh("ps -o rss= -p $(pgrep -x ollama | head -1) 2>/dev/null | awk '{printf \"%.2f\",$1/1e6}'") or "0"
    sup = tail(LOGS["supervisor"], 80); wat = tail(LOGS["watcher"], 80); fin = tail(LOGS["finisher"], 80)
    eval_done = any("DONE" in l for l in sup); full_done = any("FULL PASS DONE" in l for l in wat); kol_done = any("KOLKATA PASS DONE" in l for l in wat)
    rel_ok = any("RELEASE OK" in l for l in fin); rel_fail = any("RELEASE FAILED" in l for l in fin); rel_run = procs["release build"]
    ev = count("data/eval_corpus.jsonl"); fp = count("data/full_pass_v32.jsonl")
    global FULL_TOTAL
    # A resumed run logs only its REMAINING jobs ("50/4366"); the true total is
    # the largest denominator ever logged (7788 on the first run).
    kol = 0; dh = 0
    try:
        for l in open("data/full_pass_v32.jsonl"):
            if '"dataset": "Kolkata"' in l: kol += 1
            elif l.strip(): dh += 1
    except Exception: pass
    fp = dh
    er, ek = rate("eval", ev); fr, fk = rate("full", fp)
    eval_left = 0 if eval_done else max(EVAL_TOTAL - ev, 0) / max(er, 0.1)
    full_left = 0 if full_done else max(FULL_TOTAL - fp, 0) / max(fr, 0.1)
    kr, kk = rate("kol", kol)
    kol_left = 0 if kol_done else max(KOL_TOTAL - kol, 0) / max(kr, 0.1)
    rel_left = 0 if rel_ok else 25
    total_left = eval_left + full_left + rel_left + kol_left
    live = {}
    for l in tail(LOGS["eval"], 60):
        m = re.search(r"(Delhi|HO|Kolkata): (\d+) pages, (\d+) matched, day (\d+)/(\d+)", l)
        if m: live[m.group(1)] = {"pages": int(m.group(2)), "matched": int(m.group(3)), "ok": int(m.group(4)), "cmp": int(m.group(5)), "pct": round(100*int(m.group(4))/max(int(m.group(5)),1), 1)}
    flags = collections.Counter(); st = collections.Counter(); byds = collections.Counter()
    if fp:
        for l in open("data/full_pass_v32.jsonl"):
            try: r = json.loads(l)
            except Exception: continue
            for k in ("ok", "review", "must_fix"): flags[k] += r.get(k, 0) or 0
            st[r.get("status") or "?"] += 1; byds[r.get("dataset")] += 1
    steps = [
        {"name": "1 · Corpus accuracy eval", "sub": f"{ev} / {EVAL_TOTAL} truth-matched pages", "pct": 100 if eval_done else round(100*ev/EVAL_TOTAL, 1),
         "state": "done" if eval_done else ("running" if procs["corpus eval"] else "stalled"), "eta": fmt_eta(eval_left), "at": clock(eval_left), "rate": f"{er:.1f} pages/min ({ek})"},
        {"name": "2 · Full product pass", "sub": f"{fp} / {FULL_TOTAL} openable pages (of 9,271 listed)", "pct": 100 if full_done else round(100*fp/FULL_TOTAL, 1),
         "state": "done" if full_done else ("running" if procs["full pass"] else ("queued" if not eval_done else "stalled")), "eta": fmt_eta(eval_left + full_left), "at": clock(eval_left + full_left), "rate": f"{fr:.1f} pages/min ({fk})"},
        {"name": "3 · Kolkata product pass (skipped by a case-sensitive folder match; run separately)", "sub": f"{kol} / {KOL_TOTAL} openable pages (of 1,317 listed), 8 workers", "pct": 100 if kol_done else round(100*kol/KOL_TOTAL, 1),
         "state": "done" if kol_done else ("running" if procs["full pass"] else "queued"), "eta": fmt_eta(kol_left), "at": clock(kol_left), "rate": f"{kr:.1f} pages/min ({kk})"},
        {"name": "4 · Build 2.4.0 release ZIP", "sub": "arm64 + amd64 images, models baked", "pct": 100 if rel_ok else (50 if rel_run else 0),
         "state": "done" if rel_ok else ("failed" if rel_fail else ("running" if rel_run else "queued")), "eta": fmt_eta(total_left), "at": clock(total_left), "rate": "~25 min when the machine is quiet"},
    ]
    zips = sorted(Path("dist").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    results = Path("docs/revamp/02-V33-CORPUS-RESULTS.md")
    logs = {k: "\n".join(tail(p, 120)) for k, p in LOGS.items()}
    return {"time": time.strftime("%a %d %b %H:%M:%S"), "procs": procs, "server": health.get("pipeline"), "queue": health.get("queue_depth"),
            "free_gb": free, "ollama_gb": oll, "steps": steps, "overall_pct": round((min(ev, EVAL_TOTAL) + min(fp, FULL_TOTAL) + min(kol, KOL_TOTAL)) / (EVAL_TOTAL + FULL_TOTAL + KOL_TOTAL) * 100, 1),
            "total_eta": fmt_eta(total_left), "total_at": clock(total_left), "all_done": rel_ok and kol_done,
            "live": live, "full": {"flags": dict(flags), "status": dict(st), "by": dict(byds)},
            "results_md": results.read_text() if results.exists() else "", "logs": logs,
            "latest_zip": (zips[-1].name + f"  ({zips[-1].stat().st_size//1048576} MB, {time.strftime('%d %b %H:%M', time.localtime(zips[-1].stat().st_mtime))})") if zips else "none",
            "machine": MACH["now"], "machine_hist": [(round(c or 0), g or 0) for _, c, g in list(MACH["hist"])],
            "sample": {"v33": "1106 / 1157 = 95.6% strict · 96.6% convention · 8 silent · 0 missing · 2 spurious", "v32": "1075 / 1157 = 92.9% · 10 silent · 10 missing · 7 spurious"},
            "harness": "guard 876/934 (93.8%) · frozen_v2 1293/1456 strict (88.8%) · 1349 conv (92.7%)"}
HTML = r"""<!doctype html><html><head><meta charset=utf-8><title>v33 run · live status</title>
<style>
:root{--bg:#0b0e14;--card:#131826;--line:#1f2637;--tx:#e8ecf3;--mu:#8b93a7;--ac:#4f8cff;--ok:#39d98a;--warn:#ffb454;--bad:#ff5c5c}
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,Inter,Helvetica,Arial;margin:0;background:var(--bg);color:var(--tx)}
header{padding:22px 28px 10px;display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px}
h1{font-size:22px;margin:0}.mu{color:var(--mu)}main{padding:0 28px 40px}
.banner{background:linear-gradient(90deg,#16203a,#131826);border:1px solid var(--line);border-radius:14px;padding:18px 22px;display:flex;gap:28px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
.banner .big{font-size:34px;font-weight:700;letter-spacing:-.5px}.banner .lab{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mu)}
.obar{flex:1;min-width:260px}.bar{height:14px;background:#0b0e14;border:1px solid var(--line);border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,#3b6fe0,#4f8cff);transition:width .6s}
.bar.g i{background:linear-gradient(90deg,#1fb06c,#39d98a)}.bar.w i{background:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mu);margin:0 0 10px}
.step{display:grid;grid-template-columns:1fr auto;gap:4px 14px;padding:12px 0;border-top:1px solid var(--line)}.step:first-of-type{border-top:0}
.step .n{font-weight:600}.step .s{color:var(--mu);font-size:12px}.pill{font-size:11px;padding:2px 9px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;align-self:start}
.pill.done{color:var(--ok);border-color:#1f5b3c}.pill.running{color:var(--ac);border-color:#2b4a8a}.pill.queued{color:var(--mu)}.pill.stalled,.pill.failed{color:var(--bad);border-color:#7a2a2a}
.step .bar{grid-column:1/3;margin-top:4px}.step .eta{grid-column:1/3;font-size:12px;color:var(--mu)}
table{border-collapse:collapse;width:100%}td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}th{color:var(--mu);font-weight:500}
.ok{color:var(--ok)}.bad{color:var(--bad)}.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}.kv b{font-weight:600}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:22px 0 8px}.tab{padding:6px 12px;border:1px solid var(--line);border-radius:8px;cursor:pointer;color:var(--mu);font-size:13px;background:var(--card)}.tab.on{color:var(--tx);border-color:var(--ac)}
pre{background:#080a10;border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow:auto;font-size:12px;line-height:1.45;max-height:420px;margin:0;white-space:pre-wrap}
.done-banner{background:#123524;border-color:#1f5b3c}
.gauges{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.g .big{font-size:26px;font-weight:700}.g canvas{width:100%;height:44px;margin-top:6px;display:block}.bar.hot i{background:linear-gradient(90deg,#ff9a3c,#ff5c5c)}
</style></head><body>
<header><div><h1>Timesheet OCR · v33 end-to-end run</h1><div class=mu>eval → Delhi+HO pass → Kolkata pass → 2.4.0 release · refreshes every 5 s · read-only</div></div><div class=mu id=t>loading…</div></header>
<main>
<div class=banner id=banner><div><div class=lab>Overall progress</div><div class=big id=opct>—</div></div>
<div class=obar><div class=bar id=obarw><i style="width:0"></i></div><div class=mu id=osub></div></div>
<div><div class=lab>Everything done in</div><div class=big id=oeta>—</div><div class=mu id=oat></div></div></div>
<div class=grid>
<div class=card><h2>Pipeline steps</h2><div id=steps></div></div>
<div class=card><h2>Running accuracy vs client Excel (step 1)</h2><table id=live></table><div class=mu style="margin-top:8px">Convention-bounded number (LEAVE A/L, worked Sunday W/P). Not the per-row number against the paper.</div>
<h2 style="margin-top:16px">Full pass row flags (step 2)</h2><div id=flags class=mu>starts automatically after step 1</div></div>
<div class=card><h2>Measured already · 50-page hand-graded sample</h2><div class=kv><span>v33</span><b id=s33></b><span>v32</span><span id=s32 class=mu></span><span>harnesses</span><span id=hn class=mu></span><span>latest ZIP</span><span id=zip class=mu></span></div></div>
<div class=card><h2>Jobs</h2><table id=procs></table><div class=mu id=mach style="margin-top:8px"></div></div>
</div>
<div class=card style="margin-top:14px"><h2>Machine · live (every 3 s)</h2>
<div class=gauges>
<div class=g><div class=lab>CPU (10 cores)</div><div class=big id=gcpu>—</div><div class=bar><i id=gcpub style="width:0"></i></div><canvas id=spc width=260 height=44></canvas></div>
<div class=g><div class=lab>GPU (Metal)</div><div class=big id=ggpu>—</div><div class=bar><i id=ggpub style="width:0"></i></div><canvas id=spg width=260 height=44></canvas><div class=mu id=ggmem></div></div>
<div class=g><div class=lab>Memory</div><div class=big id=gmem>—</div><div class=bar><i id=gmemb style="width:0"></i></div><div class=mu id=gmemd></div></div>
<div class=g><div class=lab>Thermal / load</div><div class=big id=gth>—</div><div class=mu id=gload></div></div>
</div>
<table id=ptab style="margin-top:10px"></table></div>
<div class=tabs id=tabs></div><pre id=log>(select a log)</pre>
<h2 style="margin-top:22px">Results document (written when step 1 finishes, extended after step 2)</h2><pre id=res>(not yet)</pre>
</main>
<script>
let cur='finisher',D=null;
function pill(s){return '<span class="pill '+s+'">'+s+'</span>'}
function render(d){D=d;
document.getElementById('t').textContent='updated '+d.time;
document.getElementById('opct').textContent=d.overall_pct+'%';document.getElementById('obarw').firstElementChild.style.width=d.overall_pct+'%';
document.getElementById('osub').textContent='weighted over '+(1218+7788+1215).toLocaleString()+' page-runs';
document.getElementById('oeta').textContent=d.all_done?'DONE':d.total_eta;document.getElementById('oat').textContent=d.all_done?'release built, all passes complete':'expected '+d.total_at;
document.getElementById('banner').className='banner'+(d.all_done?' done-banner':'');
document.getElementById('steps').innerHTML=d.steps.map(s=>'<div class=step><div><div class=n>'+s.name+'</div><div class=s>'+s.sub+' · '+s.rate+'</div></div>'+pill(s.state)+'<div class="bar '+(s.state=='done'?'g':(s.state=='stalled'||s.state=='failed'?'w':''))+'"><i style="width:'+s.pct+'%"></i></div><div class=eta>'+s.pct+'% · '+(s.state=='done'?'finished':'ETA '+s.eta+' → '+s.at)+'</div></div>').join('');
let l='<tr><th>dataset</th><th>pages</th><th>matched</th><th>day rows</th><th>day %</th></tr>';for(const k in d.live){const v=d.live[k];l+='<tr><td>'+k+'</td><td>'+v.pages+'</td><td>'+v.matched+'</td><td>'+v.ok+'/'+v.cmp+'</td><td><b>'+v.pct+'%</b></td></tr>'}
document.getElementById('live').innerHTML=l;
const f=d.full;if(f.status&&Object.keys(f.status).length){document.getElementById('flags').innerHTML='rows: <b class=ok>ok '+(f.flags.ok||0).toLocaleString()+'</b> · review '+(f.flags.review||0).toLocaleString()+' · must_fix '+(f.flags.must_fix||0).toLocaleString()+'<br>pages: '+Object.entries(f.status).map(e=>e[0]+' '+e[1]).join(' · ')+'<br>by dataset: '+Object.entries(f.by).map(e=>e[0]+' '+e[1]).join(' · ')}
document.getElementById('s33').textContent=d.sample.v33;document.getElementById('s32').textContent=d.sample.v32;document.getElementById('hn').textContent=d.harness;document.getElementById('zip').textContent=d.latest_zip;
document.getElementById('procs').innerHTML=Object.entries(d.procs).map(e=>'<tr><td>'+e[0]+'</td><td class='+(e[1]?'ok':'mu')+'>'+(e[1]?'● running':'○ idle')+'</td></tr>').join('');
document.getElementById('mach').textContent='free memory '+d.free_gb+' GB · ollama '+d.ollama_gb+' GB · demo server pipeline '+d.server+' · queue '+d.queue;
document.getElementById('tabs').innerHTML=Object.keys(d.logs).map(k=>'<span class="tab'+(k==cur?' on':'')+'" onclick="cur=\''+k+'\';render(D)">'+k+'</span>').join('');
const pre=document.getElementById('log');const atBottom=pre.scrollHeight-pre.scrollTop-pre.clientHeight<40;pre.textContent=d.logs[cur]||'(empty)';if(atBottom)pre.scrollTop=pre.scrollHeight;
document.getElementById('res').textContent=d.results_md||'(not yet)';
const M=d.machine||{};if(M.cpu!=null){document.getElementById('gcpu').textContent=M.cpu+'%';const cb=document.getElementById('gcpub');cb.style.width=M.cpu+'%';cb.parentElement.className='bar'+(M.cpu>85?' hot':'')}
if(M.gpu!=null){document.getElementById('ggpu').textContent=M.gpu+'%';const gb=document.getElementById('ggpub');gb.style.width=M.gpu+'%';gb.parentElement.className='bar'+(M.gpu>85?' hot':'');document.getElementById('ggmem').textContent='GPU memory in use '+M.gpu_mem_gb+' GB (VLM lives here)'}
if(M.mem_free_pct!=null){const used=100-M.mem_free_pct;document.getElementById('gmem').textContent=used+'% used';const mb=document.getElementById('gmemb');mb.style.width=used+'%';mb.parentElement.className='bar'+(M.mem_free_pct<15?' hot':'');document.getElementById('gmemd').textContent='used '+M.mem_used+' · compressed '+M.mem_compressed+' · swap '+M.swap_used+' · free '+M.mem_free_pct+'%'}
document.getElementById('gth').innerHTML=(M.cpu_speed_limit>=100?'<span class=ok>no throttling</span>':'<span class=bad>CPU limited to '+M.cpu_speed_limit+'%</span>');document.getElementById('gload').textContent='load avg '+(M.load||'')+' · sampled '+(M.t||'');
document.getElementById('ptab').innerHTML='<tr><th>process</th><th>CPU %</th><th>memory</th><th>count</th></tr>'+(M.procs||[]).map(p=>'<tr><td>'+p.name+'</td><td>'+p.cpu+'</td><td>'+p.mb+' MB</td><td>'+p.n+'</td></tr>').join('');
spark('spc',(d.machine_hist||[]).map(x=>x[0]),'#4f8cff');spark('spg',(d.machine_hist||[]).map(x=>x[1]),'#39d98a');}
function spark(id,vals,col){const c=document.getElementById(id);if(!c)return;const ctx=c.getContext('2d');const W=c.width,H=c.height;ctx.clearRect(0,0,W,H);if(vals.length<2)return;ctx.strokeStyle='#1f2637';ctx.beginPath();for(const y of [0.25,0.5,0.75]){ctx.moveTo(0,H*y);ctx.lineTo(W,H*y)}ctx.stroke();ctx.strokeStyle=col;ctx.lineWidth=1.6;ctx.beginPath();vals.forEach((v,i)=>{const x=i/(vals.length-1)*W,y=H-(Math.max(0,Math.min(100,v))/100)*(H-2)-1;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.fillStyle=col+'33';ctx.lineTo(W,H);ctx.lineTo(0,H);ctx.closePath();ctx.fill()}
async function go(){try{const r=await fetch('/api/status');render(await r.json())}catch(e){document.getElementById('t').textContent='dashboard unreachable'}}
go();setInterval(go,5000);
</script></body></html>"""
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/api/status"): b, ct = json.dumps(status()).encode(), "application/json"
        else: b, ct = HTML.encode(), "text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
if __name__ == "__main__":
    print("dashboard on http://127.0.0.1:8090", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
