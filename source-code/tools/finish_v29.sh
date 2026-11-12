#!/bin/zsh
# End-to-end finisher: wait for the corpus eval, finalize the report, build
# and package the release, refresh the snapshot. Logs to data/finish_v29.log.
cd "$(cd "$(dirname "$0")/.." && pwd)"
L=data/finish_v29.log
echo "[$(date '+%a %H:%M')] waiting for eval" >> $L
while ! grep -q "DONE" data/eval_corpus_v29_supervisor.log 2>/dev/null; do
  pgrep -f eval_corpus_supervised >/dev/null || { echo "[$(date '+%a %H:%M')] supervisor gone without DONE" >> $L; exit 1; }
  sleep 60
done
echo "[$(date '+%a %H:%M')] eval DONE -> finalize report" >> $L
./.venv/bin/python tools/finalize_report.py >> $L 2>&1
echo "[$(date '+%a %H:%M')] release" >> $L
./tools/release_v29.sh >> $L 2>&1 && echo "[$(date '+%a %H:%M')] release OK" >> $L || echo "[$(date '+%a %H:%M')] release FAILED" >> $L
cp docs/revamp/*.md versions/v29-revamp/ 2>/dev/null; cp data/eval_corpus.json versions/v29-revamp/eval_corpus_v29.json 2>/dev/null
echo "[$(date '+%a %H:%M')] ALL DONE" >> $L
