# 03 — Setup on a Laptop

Gets the system running on one machine, reading a real timesheet, in about
fifteen minutes. Everything in this document was run and verified on the
handover machine; the outputs shown are real, not illustrative.

> **Note for this public repository.** The employee roster, the designation
> vocabulary and the graded test fixtures are **not** published here — they are
> personal data about real workers. Steps 3 and 3b below therefore reference
> files you will not find in this repository; obtain them separately from the
> data owner. Everything else in this guide works as written, and the
> application runs fine without them (every page will simply be flagged for an
> unmatched identity).

Two routes. Pick one.

- **Route A — Python directly.** Best for development. You will be editing code.
- **Route B — Docker.** Best for "just show me it working". No Python setup.

---

## What you need

| | |
|---|---|
| Operating system | macOS, Linux, or Windows |
| Disk | 3 GB for the application. Much more if you keep the client data in this package |
| Memory | 8 GB minimum. 16 GB if you enable the handwritten-header model |
| Graphics card | **Not required.** Everything runs on the ordinary processor |
| Internet | Needed once, to install dependencies. Not needed to run |

---

# Route A — Python directly

### 1. Install Python

Version **3.11 or 3.12** is the verified combination. 3.14 also works — the
handover machine develops on it — but the shipped container uses 3.12 because
that is what was tested end to end.

Check what you have:

```bash
python3 --version
```

### 2. Create the environment and install

From inside `source-code/`:

```bash
cd source-code
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

This downloads about 400 MB, mostly the text-recognition runtime. It takes a
few minutes.

On Windows the paths differ: `python -m venv .venv` then
`.venv\Scripts\pip install -r requirements.txt`.

### 3. Put the reference data where the app expects it

The application reads the employee roster and the designation vocabulary from
its data directory:

```bash
mkdir -p data
cp ../reference-data/roster.csv       data/
cp ../reference-data/designations.csv data/
```

Without the roster the system still runs, but it cannot match a name to an
employee code, so every page will be flagged for that reason. It is not
optional in practice.

**Also copy the test fixtures.** The evaluation harnesses and the verification
step below look for them under `data/`, not under `reference-data/`:

```bash
cp -R ../reference-data/test-fixtures/testsets        data/
cp -R ../reference-data/test-fixtures/_sample50       data/
cp -R ../reference-data/test-fixtures/_manual_verify  data/
```

That is about 70 MB. If you skip it, the application still works perfectly —
but `guard.py` will fail its last check with a `FileNotFoundError`, because
that check reads a real sheet twice and has no sheet to read. The harnesses in
`tools/` will fail for the same reason.

(If you would rather not duplicate the files, symlink instead:
`ln -s ../reference-data/test-fixtures/testsets data/testsets` and the same for
the other two.)

### 3b. Optional — the client corpus

Only needed if you want to run the corpus-wide tools (`eval_corpus.py`,
`survey.py`, `classify_corpus.py`, `measure_accuracy.py` and the `probe_*`
scripts). Those expect the client folders at the top of the working directory,
alongside `data/`:

```bash
ln -s ../client-data/"Timesheet - Delhi 2026-2027"   .
ln -s ../client-data/"Timesheet - HO 2026-2027"      .
ln -s ../client-data/"Timesheet - KOLKATA 2026-2027" .
ln -s ../client-data/handwritten_corpus              .
```

Symlinks rather than copies, because that is 6.6 GB. Skip this entirely for
normal development — everything in `06-ACCURACY-AND-TESTING.md` except
`eval_corpus.py` works from the test fixtures alone.

### 4. Start it

```bash
./run.sh
```

On Windows, `run.bat`. Or directly:

```bash
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
```

Open **http://127.0.0.1:8077**. There is no login when running locally — the
login gate is part of the server deployment, not the application.

### 5. Verify it is correctly set up

This is the important step, and it takes two minutes:

```bash
./.venv/bin/python tools/guard.py --quick
```

Verified output on a correct installation:

```
GUARD · pipeline v52-no-silent-employee-loss  (--quick: structural only)

STRUCTURAL
  PASS      ocr_engine.OCR_USE_CLS is False  [D-073]
  PASS      pipeline.CLOCK_REPAIR is False  [D-072 measured worse]
  PASS      pipeline.UNIT_SUFFIX_HOURS is True  [D-076]
  PASS      pipeline.SPLIT_CELL_IS_UNREADABLE is True  [D-076]
  PASS      validate.UNCOMPUTABLE_IS_NOT_FAILED is True  [D-075]
  PASS      rowconf.CROWDED_CELL_REVIEW is True  [D-074]
  PASS      generic_grid.NUMERIC_CELL_IS_PRESENT is False  [D-086 measured no gain]
  PASS      hours parsing (10Hrs, 3 6, 85, 42, 1000, 10:00) all ok
  PASS      clock grammar (8:30 AM, 7:30 Pm, 00:60, 9 AM) all ok
  PASS      cache path returns the same page as a fresh read (3, 'needs_review', 93)

GUARD PASSED — safe to ship.
```

Ten checks. If any line says `**FAIL**`, stop and fix it before going further
— `06-ACCURACY-AND-TESTING.md` explains what each one protects.

The last check is doing more than it looks. It reads a real sheet twice, once
fresh and once from cache, and requires an identical result: 3 employee
records, status `needs_review`, 93 day cells filled. That one line would have
caught a defect that previously shipped through seven releases.

### 6. Read a real sheet

In the browser: **Upload**, then pick a file from this package, for example

```
reference-data/test-fixtures/testsets/horizontal-multi-employee/sheets/ISG MAY 2026.pdf
```

This sheet carries three workers. Expect three records, each with 31 days, and
every page marked `needs_review` — those workers are not in the roster that
ships here, which the system correctly notices and flags.

Then click **Export** and open the workbook. The `Attendance` sheet should show
a row per worker with 31 day columns.

---

# Route B — Docker

No Python needed.

```bash
cd source-code
docker build -t timesheet-app:local .
```

The build takes five to ten minutes and deliberately does extra work: it
downloads the text-recognition models and bakes them into the image, so the
running container never needs network access. The build fails rather than
produce a broken image if the models are missing or the application does not
import.

Run it:

```bash
mkdir -p data
cp ../reference-data/roster.csv ../reference-data/designations.csv data/
docker run --rm -p 8077:8077 -v "$PWD/data:/data" timesheet-app:local
```

Open **http://127.0.0.1:8077**.

There is also a packaged compose setup in `source-code/deploy/` with helper
scripts (`start.sh`, `stop.sh`, `logs.sh`, `restart.sh`, and `.bat` equivalents)
that was built for handing to a non-technical operator. `deploy/START-HERE.md`
and `deploy/TROUBLESHOOTING.md` are written for that audience.

---

## Optional — the handwritten-header model

Off by default. It improves name reading on the hardest handwritten headers and
costs one to two minutes on such a page.

```bash
# install Ollama (ollama.com), then:
ollama pull qwen3-vl:4b          # about 3.3 GB
```

Then set in the environment:

```
TS_VLM_HEADER=1
TS_OLLAMA_URL=http://127.0.0.1:11434
TS_VLM_MODEL=qwen3-vl:4b
```

It needs roughly 16 GB of memory to sit alongside the rest. The address is
local-only; nothing leaves the machine.

This is not a nicety. A measurement on 10 November 2026 compared the same 19
handwritten pages on a server with this model running against a machine
without it: **91.4% against 89.5%**. Better header reading gives a better month
inference, which gives a better day axis, which gives more correct day cells.

---

## Day-to-day commands

From `source-code/`, using the Makefile:

```bash
make help     # list these
make run      # start the web app
make fast     # score extraction against frozen text, about 1 second
make matrix   # A/B the extraction switches
make full     # full pipeline against the client's own spreadsheets, ~10 min
```

`make fast` is the one to iterate with. It reuses previously captured OCR
output, so it measures extraction logic alone and returns in about a second.
**It is only valid if you have not changed OCR or preprocessing** — if you
have, run `make freeze` first (about eight minutes) to recapture.

---

## If something goes wrong

**`ModuleNotFoundError: No module named 'app'`** — you are not in
`source-code/`, or you are using the system Python instead of `.venv`. Scripts
must be run from the `source-code` directory.

**`libxcb.so.1: cannot open shared object file`** (Docker/Linux) — two versions
of the image library are installed and the wrong one won. The Dockerfile
already handles this; if you are installing by hand, remove both and reinstall
only `opencv-python-headless`. The comment in the Dockerfile explains why.

**The app reports no roster** — step 3 was skipped.

**A page comes out completely empty** — most often the page is rotated 90 or
180 degrees. The system has an orientation rescue for this, but it only
triggers when extraction finds nothing; check the page image first.

**Port 8077 already in use** — change it with `TS_PORT`.

More in `source-code/deploy/TROUBLESHOOTING.md`.

---

## Next

- Deploy it for real: `04-DEPLOY-TO-CLOUD.md`
- Before changing extraction code: `06-ACCURACY-AND-TESTING.md`
