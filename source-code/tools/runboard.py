"""Local dashboard for the corpus accuracy run.

    ./.venv/bin/python tools/runboard.py        ->  http://127.0.0.1:8099

Read-only. It polls data/corpus_run_state.json, which the run rewrites after
every page, and renders it. It never touches the pipeline, the checkpoint or
the log, so it cannot slow the run down or corrupt it, and it can be started,
stopped and restarted at any point while the run continues.

Works with no internet: no fonts, scripts or styles are fetched from anywhere.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
os.chdir(ROOT)
STATE = ROOT / "data" / "corpus_run_state.json"
RUNLOG = ROOT / "data" / "corpus_run.log"
PORT = int(os.getenv("TS_RUNBOARD_PORT", "8099"))

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Timesheet corpus run</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
body{margin:0;background:#0f1420;color:#e8edf7;
     font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:22px}
h1{font-size:20px;margin:0 0 2px}
.sub{color:#8b97ad;font-size:13px;margin:0 0 18px}
.card{background:#171d2b;border:1px solid #242c3e;border-radius:12px;padding:16px 18px;margin-bottom:14px}
.row{display:flex;gap:14px;flex-wrap:wrap}
.row>.card{flex:1;min-width:210px}
.k{color:#8b97ad;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.v{font-size:27px;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.v.sm{font-size:19px}
.ok{color:#4ade80}.warn{color:#fbbf24}.bad{color:#f87171}.mut{color:#8b97ad}
.bar{height:12px;background:#0b0f18;border-radius:7px;overflow:hidden;margin-top:12px;
     border:1px solid #242c3e}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,#22d3ee);width:0;
       transition:width .6s ease}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #242c3e}
th{color:#8b97ad;font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px}
td.n{text-align:right;font-variant-numeric:tabular-nums}
pre{background:#0b0f18;border:1px solid #242c3e;border-radius:9px;padding:12px;
    max-height:360px;overflow:auto;font-size:12px;line-height:1.55;margin:8px 0 0;
    white-space:pre-wrap;word-break:break-word}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px}
.live{background:#4ade80;animation:p 1.6s infinite}
@keyframes p{50%{opacity:.25}}
.note{color:#8b97ad;font-size:12.5px;margin-top:9px;line-height:1.5}
</style></head><body><div class="wrap">
<h1><span class="dot live" id="dot"></span>Timesheet corpus accuracy run</h1>
<p class="sub" id="hdr">connecting…</p>

<div class="card">
  <div class="row" style="justify-content:space-between;align-items:baseline">
    <div><span class="k">Progress</span><div class="v" id="pct">—</div></div>
    <div style="text-align:right"><span class="k">Time left</span><div class="v sm" id="eta">—</div></div>
  </div>
  <div class="bar"><i id="bar"></i></div>
  <div class="note" id="prog">—</div>
</div>

<div class="card" style="border-color:#2b3purple">
  <div class="k">What this run replaces</div>
  <div class="note" style="margin-top:6px">
    The previous corpus figure was <b>77.2%</b>, measured before two fixes: pages were
    being compared against the wrong date range (sixteen perfectly-read pages scored
    zero), and the hours column on some layouts parsed as nothing. That figure
    <b>understates</b> the system and should not be quoted. This run replaces it.
  </div>
</div>

<div class="row">
  <div class="card"><span class="k">Days read correctly</span>
      <div class="v ok" id="acc">—</div><div class="note" id="accn">—</div></div>
  <div class="card"><span class="k">Employee name correct</span>
      <div class="v" id="nm">—</div><div class="note" id="nmn">—</div></div>
  <div class="card"><span class="k">Wrong pages that were flagged</span>
      <div class="v ok" id="caught">—</div><div class="note">should be 100%</div></div>
  <div class="card"><span class="k">Wrong pages NOT flagged</span>
      <div class="v" id="esc">—</div><div class="note">should be 0 — these are the
      ones a person would never be asked to check</div></div>
</div>

<div class="card"><span class="k">Pages scored vs pages skipped</span>
  <div class="note" style="margin-top:6px" id="cov">—</div></div>

<div class="card"><span class="k">By site</span><div id="ds"></div></div>
<div class="card"><span class="k">Pages with no matching record in the employee list</span>
  <div id="rs"></div>
  <div class="note">These are not reading mistakes. The page was read, but it could not be
  tied to a row in the ground-truth list — usually the same name appears for several
  months, so the check refuses to guess which one it is.</div></div>
<div class="card"><span class="k">Live log</span><pre id="log">waiting…</pre></div>
</div>
<script>
function hms(m){ if(m===null||m===undefined) return '—';
  if(m<1) return 'under a minute';
  const h=Math.floor(m/60), mm=Math.round(m%60);
  return h? h+'h '+mm+'m' : mm+'m'; }
function pc(x){ return x===null||x===undefined?'—':x.toFixed(1)+'%'; }
async function tick(){
  let s; try{ s=await (await fetch('/state?'+Date.now())).json(); }
  catch(e){ document.getElementById('hdr').textContent='no run state yet — start the run'; return; }
  if(s.error){ document.getElementById('hdr').textContent=s.error; return; }
  const stale=(Date.now()/1000-s.updated)>180;
  document.getElementById('dot').className='dot '+(stale?'':'live');
  document.getElementById('dot').style.background=stale?'#8b97ad':'#4ade80';
  document.getElementById('hdr').textContent =
    s.label+' · pipeline '+s.pipeline+' · running '+hms(s.elapsed_minutes)
    + (stale?' · NO UPDATE IN 3 MIN — the run may have stopped':'');
  document.getElementById('pct').textContent=s.pct.toFixed(1)+'%';
  document.getElementById('bar').style.width=Math.min(s.pct,100)+'%';
  document.getElementById('eta').textContent=hms(s.eta_minutes);
  document.getElementById('prog').textContent =
    s.done+' of '+s.total_pages+' pages · '+s.left+' to go · '
    +s.rate_per_min+' pages/min ('+s.rate_quality+')';
  const a=s.accuracy;
  document.getElementById('acc').textContent=pc(a.day_status_pct);
  document.getElementById('accn').textContent=a.days_ok+' of '+a.days_compared+' days checked against the paper records';
  document.getElementById('nm').textContent=pc(a.name_pct);
  document.getElementById('nmn').textContent=a.name_ok+' of '+a.name_compared+' pages';
  const sf=s.safety;
  document.getElementById('caught').textContent=pc(sf.caught_pct);
  const e=sf.pages_with_a_wrong_day_NOT_flagged;
  const el=document.getElementById('esc');
  el.textContent=e; el.className='v '+(e===0?'ok':'bad');
  let h='<table><tr><th>Site</th><th class="n">Pages</th><th class="n">Checked</th>'
       +'<th class="n">Days right</th><th class="n">Not flagged</th></tr>';
  for(const [k,v] of Object.entries(s.per_dataset)){
    const p=v.days_cmp?(100*v.days_ok/v.days_cmp):null;
    h+='<tr><td>'+k+'</td><td class="n">'+(v.pages||0)+'</td><td class="n">'+(v.matched||0)
      +'</td><td class="n">'+(p===null?'—':p.toFixed(1)+'%')+'</td><td class="n">'
      +(v.escaped||0)+'</td></tr>';
  }
  document.getElementById('ds').innerHTML=h+'</table>';
  const un=s.unmatched_reasons||{};
  const tot=Object.values(un).reduce((a,b)=>a+b,0);
  document.getElementById('cov').innerHTML =
    '<b>'+(s.matched_pages||0)+'</b> pages were scored against the client records. '
    +'<b>'+tot+'</b> could not be — they were read, but could not be tied to a row to '
    +'check against. That is a limit of the records, not of the reading.';
  let r='<table><tr><th>Reason</th><th class="n">Pages</th></tr>';
  for(const [k,v] of Object.entries(s.unmatched_reasons||{}))
  {
    const EXPLAIN={
      'below threshold':'the name read does not match any row in the client records closely enough',
      'no name':'no employee name could be read from the page',
      'ambiguous name':'the same name appears for several months with different attendance — the check refuses to guess',
      'no date overlap':'the page and the client record cover different days (e.g. page has 24–31, record has 1–23), so there is nothing to compare',
      'page error':'the page could not be processed'};
    r+='<tr><td>'+k.replace(/_/g,' ')+'<div class="note" style="margin:2px 0 0">'
      +(EXPLAIN[k.replace(/_/g,' ')]||'')+'</div></td><td class="n">'+v+'</td></tr>';
  }
  document.getElementById('rs').innerHTML=r+'</table>';
  document.getElementById('log').textContent=(s.recent_log||[]).join('\\n');
}
tick(); setInterval(tick,3000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the terminal clean for the run
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            try:
                body = STATE.read_bytes()
            except Exception:                                   # noqa: BLE001
                body = json.dumps({"error": "no run state yet — start the run"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())


if __name__ == "__main__":
    print(f"dashboard on http://127.0.0.1:{PORT}   (Ctrl-C to stop; the run is unaffected)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
