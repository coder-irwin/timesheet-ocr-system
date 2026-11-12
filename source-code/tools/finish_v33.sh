#!/bin/zsh
# End-to-end finisher for v33: eval DONE -> summarise accuracy; FULL PASS DONE -> summarise flags;
# then build the 2.4.0 release when the machine is quiet. Keeps the supervisor/watcher chain alive.
export PATH=/opt/homebrew/bin:$PATH
cd "$(cd "$(dirname "$0")/.." && pwd)"; L=data/finish_v33.log
log(){ echo "[$(date '+%a %H:%M')] $*" >> $L; }
freegb(){ vm_stat | awk '/Pages free/{f=$3}/Pages inactive/{i=$3}END{gsub(/\./,"",f);gsub(/\./,"",i);printf "%.1f",(f+i)*16384/1e9}'; }
log "finisher started; eval rows=$(wc -l < data/eval_corpus.jsonl | tr -d ' ')"
# 1. eval
while ! grep -q DONE data/eval_corpus_v32_supervisor.log; do
  if ! pgrep -f eval_corpus_supervised >/dev/null; then log "supervisor gone -> relaunch"; nohup ./tools/eval_corpus_supervised.sh >/dev/null 2>&1 & fi
  if ! pgrep -f after_eval_v32.sh >/dev/null; then log "watcher gone -> relaunch"; nohup ./tools/after_eval_v32.sh >/dev/null 2>&1 & fi
  sleep 300
done
log "eval DONE rows=$(wc -l < data/eval_corpus.jsonl | tr -d ' ')"
./.venv/bin/python tools/summarize_v33.py >> $L 2>&1; log "accuracy summary written (docs/revamp/02-V33-CORPUS-RESULTS.md)"
# 2. full pass
while ! grep -q "FULL PASS DONE" data/after_eval_v32.log; do
  if ! pgrep -f after_eval_v32.sh >/dev/null; then log "watcher gone -> relaunch"; nohup ./tools/after_eval_v32.sh >/dev/null 2>&1 & fi
  sleep 300
done
log "full pass DONE pages=$(wc -l < data/full_pass_v32.jsonl | tr -d ' ')"
./.venv/bin/python tools/summarize_v33.py >> $L 2>&1; log "full-pass summary written"
# 3. release when quiet
for i in {1..48}; do
  if ! pgrep -f "tools/eval_corpus.py|full_pass_v32.py|eval_sample50.py" >/dev/null && [ $(freegb | cut -d. -f1) -ge 3 ]; then
    log "building 2.4.0 (free $(freegb) GB)"; ./tools/release_v33.sh >> $L 2>&1 && log "RELEASE OK" || log "RELEASE FAILED (see log)"; break
  fi
  log "release waiting: free $(freegb) GB"; sleep 600
done
log "FINISHER DONE"
