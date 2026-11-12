# Timesheet Digitiser -- the commands that matter, named.
#
# The accuracy loop is: change one thing -> `make fast` -> keep or revert.
# `make full` is for the number you quote to the client, not for iterating.
PY := .venv/bin/python

.PHONY: help run fast matrix freeze full demo clean-cache

help:
	@echo "run     start the web app on http://127.0.0.1:8077"
	@echo "fast    score extraction against frozen OCR      (~1s)  <- iterate with this"
	@echo "matrix  A/B the extraction switches              (~5s)"
	@echo "freeze  rebuild frozen OCR -- ONLY after an OCR/preprocess change (~8m)"
	@echo "full    full pipeline vs the client's Excel      (~10m) <- quote this"
	@echo "demo    stage the 10 best-reading pages in demo/ (needs 'full' first)"

run:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8077

fast:
	$(PY) tools/eval_fast.py

matrix:
	$(PY) tools/eval_fast.py --matrix

freeze:
	$(PY) tools/eval_fast.py --freeze

full:
	$(PY) tools/eval_100.py

demo:
	$(PY) tools/demo_pack.py 10

# Extraction results are keyed by page hash + PIPELINE_VERSION, so bumping the
# version is the normal way to invalidate. This is the blunt option.
clean-cache:
	rm -f data/cache/*.json
