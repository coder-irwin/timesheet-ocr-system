# 14 — Verification Record

What was actually tested before this package was handed over, and the results.
Every figure here came from a command that was run; none is an estimate.

---

## 1. Clean-room installation

The most important check. A fresh directory was created containing **only**
what this package provides — `source-code/`, `reference-data/` and
`deployment/`, with nothing from the original development machine — and
`03-SETUP-ON-A-LAPTOP.md` was followed exactly as written.

| Step | Result |
|---|---|
| Create environment, install `requirements.txt` | Succeeded, Python 3.14.5 |
| Copy reference data | Succeeded |
| `tools/guard.py --quick` | **FAILED** on first attempt |
| After correcting the guide, re-run | **PASSED, 10/10** |

### The defect this found, and the correction

`guard.py`'s final check reads a real sheet twice, and expects the test
fixtures under `data/`. The setup guide originally said only to copy
`roster.csv` and `designations.csv`, so the check failed with a
`FileNotFoundError`.

A developer following the guide would have hit this on their first day and
reasonably concluded the package was broken. The guide now includes the fixture
copy as step 3, and documents exactly what happens if you skip it.

This is recorded rather than quietly fixed because it is the clearest evidence
that the clean-room test was worth doing: the package was wrong, and only
following it from scratch revealed it.

---

## 2. Accuracy reproduced from the package alone

In the same clean room, `tools/eval_isgec.py`:

```
TOTAL  employees produced 12/12 · days 366/366 = 100.0% · wrong 0 · missing 0 · silent 0
```

**366 of 366 day cells, 100.0%** — matching the figure quoted in
`06-ACCURACY-AND-TESTING.md` exactly. Ground truth for that run comes from the
PDFs' own embedded text layers, not from any stored pipeline output, so this is
a genuine independent reproduction.

This means a new team can verify the accuracy claims themselves rather than
taking them on trust. That was the point.

---

## 3. Structural checks

`tools/guard.py --quick`, 10 of 10 passed, in the clean room and on the
development machine:

- All seven measured-decision flags at their correct values
- Hours parsing: `10Hrs`, `3 6`, `85`, `42`, `1000`, `10:00`
- Clock grammar: `8:30 AM`, `7:30 Pm`, `00:60` (correctly rejected), `9 AM`
- The cache path returns an identical result to a fresh read: 3 employee
  records, status `needs_review`, 93 day cells

---

## 4. Live deployment verification

Before this handover the system was deployed to a cloud project and tested over
HTTPS with `tools/e2e_prod_test.py`:

**32 of 32 checks passed.** Covering: anonymous requests refused; both logins
working; the version running in the container matching source; a real upload
read correctly; the multi-employee sheet split into one record per person;
per-row confidence on every row; the Excel export; page locking; and audit
attribution.

Measured accuracy on the live deployment:

| | |
|---|---|
| Horizontal multi-employee sheet | 93/93 day cells, 100%, names 3/3 |
| Statuses surviving into the Excel | 93/93 |
| 19 handwritten pages | 533/583 = 91.4%, **0 wrong and unflagged** |
| Same 19 pages, no header model | 522/583 = 89.5% |

That last pair is why the header model is on in production.

A measured cold start from a stopped machine: URL answering at 53 seconds,
text recognition ready at 56 seconds.

---

## 5. Package integrity

| Check | Result |
|---|---|
| Documentation path references | **330 checked, all resolve** |
| Python files parse | 103 of 103 |
| Shell scripts parse | 18 of 18 |
| Credential files present | None |
| Database files present | None |
| Hardcoded personal paths | None — 25 files were corrected to resolve paths relative to the project |
| Live environment values (addresses, billing ids, passwords) | None |

Deployment scripts are templated: the billing account, static address, project
number and SSH user are placeholders that must be supplied. Project, zone and
machine name are overridable environment variables with sensible defaults.

---

## 6. What was NOT verified

Stated plainly, because an incomplete verification presented as complete is
worse than none.

- **`deploy_gcp.sh` has not been run against a *different* cloud project.** It
  was run against the original project on 10 November 2026 and succeeded after
  the two defects described in `04-DEPLOY-TO-CLOUD.md` §7 were fixed. The
  templating applied afterwards is a mechanical substitution that has not been
  executed end to end. **Expect to debug the first deploy**, and read §5 of
  that document before starting.
- **The full `guard.py` run (~25 minutes) was not re-run in the clean room.**
  Only the two-minute structural subset, plus the ISGEC harness. The full
  figures in `06-ACCURACY-AND-TESTING.md` come from runs on the development
  machine.
- **The corpus-wide harness was not re-run.** The 89.5% figure is from an
  earlier run under pipeline v49, and is labelled as such.
- **Windows was not tested.** `run.bat` and the `.bat` helpers are shipped and
  were written alongside their shell equivalents, but the verification above was
  done on macOS. The Docker route avoids the question entirely.
- **No load or concurrency testing** was done as part of this handover. The
  throughput figures come from earlier measurements recorded in
  `engineering-history/SCALE-AND-DEPLOYMENT.md`.
- **The Excel designs were not checked against AARVI's payroll templates**, as
  noted in `10-KNOWN-LIMITATIONS.md` §9.

---

## 7. How to repeat this verification

```bash
cd source-code
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

mkdir -p data
cp ../reference-data/roster.csv ../reference-data/designations.csv data/
cp -R ../reference-data/test-fixtures/testsets       data/
cp -R ../reference-data/test-fixtures/_sample50      data/
cp -R ../reference-data/test-fixtures/_manual_verify data/

./.venv/bin/python tools/guard.py --quick     # expect 10/10 PASS
./.venv/bin/python tools/eval_isgec.py        # expect 366/366 = 100.0%
./.venv/bin/python tools/guard.py             # the full floor, ~25 min
```

If the first two do not produce those results, something is wrong with the
environment rather than the code — and the third is the real gate before
shipping any change.
