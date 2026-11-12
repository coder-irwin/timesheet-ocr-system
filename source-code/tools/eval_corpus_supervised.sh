#!/bin/zsh
# Relaunch the corpus eval after an OOM kill; it resumes from its checkpoint.
# Stops on a clean exit (0) or after 30 attempts. Pauses 120s between tries
# so a transient memory spike (another project's model load) can pass.
cd "$(cd "$(dirname "$0")/.." && pwd)"
for i in {1..30}; do
  echo "[$(date '+%H:%M:%S')] attempt $i  rows=$(wc -l < data/eval_corpus.jsonl | tr -d ' ')" >> data/eval_corpus_v32_supervisor.log
  ./.venv/bin/python tools/eval_corpus.py >> data/eval_corpus_v32.log 2>&1
  rc=$?
  echo "[$(date '+%H:%M:%S')] exit $rc" >> data/eval_corpus_v32_supervisor.log
  [ $rc -eq 0 ] && { echo "[$(date '+%H:%M:%S')] DONE" >> data/eval_corpus_v32_supervisor.log; exit 0; }
  sleep 120
done
echo "[$(date '+%H:%M:%S')] gave up after 30 attempts" >> data/eval_corpus_v32_supervisor.log
