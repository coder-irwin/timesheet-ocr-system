#!/bin/zsh
cd "$(cd "$(dirname "$0")/.." && pwd)"; L=data/after_eval_v32.log
echo "[$(date '+%a %H:%M')] waiting for v32 eval" >> $L
while ! grep -q DONE data/eval_corpus_v32_supervisor.log 2>/dev/null; do pgrep -f eval_corpus_supervised >/dev/null || { echo "[$(date '+%a %H:%M')] eval supervisor gone" >> $L; exit 1; }; sleep 120; done
echo "[$(date '+%a %H:%M')] eval DONE -> full pass (3 workers, resumable)" >> $L
for i in {1..20}; do TS_WORKERS=8 TS_OCR_THREADS=2 ./.venv/bin/python tools/full_pass_v32.py >> data/full_pass_v32.log 2>&1 && break; echo "[$(date '+%a %H:%M')] full pass died, resuming" >> $L; sleep 120; done
echo "[$(date '+%a %H:%M')] FULL PASS DONE" >> $L
