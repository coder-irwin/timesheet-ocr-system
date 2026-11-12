# 12 — Operations Runbook

Day-to-day running of a deployed instance, and what to do when something is
wrong.

Commands assume the defaults `VM=timesheet-prod` and `ZONE=asia-south1-a`.
Adjust for your own project.

---

## 1. Daily checks

```bash
gcloud compute ssh timesheet-prod --zone=asia-south1-a --tunnel-through-iap
cd ~/timesheet-app
sudo docker compose ps                        # both containers up?
sudo docker compose logs -f timesheet         # application log
```

Or from anywhere, without logging in:

```bash
curl -su '<user>:<password>' https://<site>/api/health
```

A healthy response:

```json
{ "ocr_ready": true,
  "roster_loaded": true, "roster_size": 2575,
  "pipeline": "v52-no-silent-employee-loss",
  "workers": 2, "queue_depth": 0 }
```

What to look at:

| Field | Healthy | Meaning if wrong |
|---|---|---|
| `ocr_ready` | `true` | `false` means the recognition models failed to load — the app cannot read anything |
| `roster_loaded` | `true` | `false` means every page will be flagged for unmatched identity |
| `pipeline` | matches your source | A mismatch means the server is running different code than you think |
| `queue_depth` | 0 when idle | A number that never falls means work is stuck |

---

## 2. Normal operations

### Start and stop

```bash
gcloud compute instances stop  timesheet-prod --zone=asia-south1-a
./wake.sh        # starts the machine, brings containers up, waits for ready
```

Measured cold start from fully stopped: machine running at 13 s, OS booted at
43 s, containers up at 48 s, URL answering at 53 s, recognition ready at 56 s.

Compute is the overwhelming majority of the cost and stops the moment the
machine stops. See `05-WHAT-IT-COSTS.md`.

### Managing people

```bash
./user.sh add <name>              # generates a password, prints it ONCE
./user.sh add <name> <password>   # choose it yourself
./user.sh remove <name>
./user.sh list
```

Passwords are stored only as hashes, in `gcp/users.caddy` on the server.
Adding or removing restarts the login gate for about two seconds; the
application itself is untouched.

Every upload, edit and export is stamped with the person's name in the page
history and in the `Audit` worksheet of every export. Give each person their
own login — a shared one destroys the audit trail's value.

### Deploying new code

```bash
# build and ship the image
cd source-code
docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 .
docker save timesheet-app:2.5.0-amd64 | gzip > timesheet-app-amd64.tar.gz
gcloud compute scp timesheet-app-amd64.tar.gz timesheet-prod:~/timesheet-app/ \
  --zone=asia-south1-a --tunnel-through-iap

# on the server
sudo docker load -i timesheet-app-amd64.tar.gz
sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \
  --env-file config.env --env-file .env up -d
```

**If you are shipping a changed overlay file, copy it to the server BEFORE
adding or enabling its mount.** Docker turns a bind-mount with a missing source
path into an empty *directory*, and the container then tries to import a
directory where a module should be. This took the application down for four
minutes once.

Afterwards, confirm the container is serving what you think:

```bash
sudo docker exec timesheet-app sh -c \
  'for f in pipeline rowconf generic_grid ocr_engine clocks; do wc -c < /app/app/$f.py; done'
```

Those must be real file sizes. Then check `/api/health` reports the version you
just shipped — and remember the version string stays correct even when the code
behind it is wrong, which is exactly why the byte-size check exists.

Finally, verify properly:

```bash
./.venv/bin/python tools/e2e_prod_test.py --url https://<site>
```

Thirty-two checks. Do not announce a deployment until it passes.

---

## 3. Backups and restore

Nightly snapshots, seven kept, set up by the deploy script.

**Two things to know.** The first snapshot does not exist until the schedule
first fires, so immediately after a deploy you have no cloud-side backup. And a
snapshot protects against disk loss, not against a bad change.

Manual backup:

```bash
gcloud compute ssh timesheet-prod --zone=asia-south1-a --tunnel-through-iap \
  --command 'sudo tar -czf /tmp/backup.tgz -C ~ timesheet-app'
gcloud compute scp timesheet-prod:/tmp/backup.tgz ./ \
  --zone=asia-south1-a --tunnel-through-iap
```

**Always verify a backup before relying on it:**

```bash
shasum -a 256 backup.tgz           # compare against the source
tar -tzf backup.tgz | wc -l        # file count as expected?
mkdir x && tar -xzf backup.tgz -C x
sqlite3 x/timesheet-app/data/timesheets.db "PRAGMA integrity_check;"   # must say: ok
```

Restore onto a machine:

```bash
./restore.sh /path/to/backup.tgz
```

Before a clean shutdown, checkpoint the database so the write-ahead log is
folded into the main file:

```bash
sudo docker exec timesheet-app python3 -c \
  "import sqlite3; sqlite3.connect('/data/timesheets.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"
sudo docker compose stop
```

---

## 4. Troubleshooting

### The site does not respond at all

1. Is the machine running? `gcloud compute instances describe timesheet-prod --zone=asia-south1-a --format='value(status)'`
2. If `TERMINATED`, that is the answer — `./wake.sh`.
3. If `RUNNING`, check the containers: `sudo docker compose ps`.
4. If Caddy is not running, it is almost always a missing or malformed
   `gcp/users.caddy` — the Caddyfile does `import users.caddy` and will not
   start without it.

### A container refuses to start

Look for `not a directory` in the error. That is the bind-mount problem: an
overlay file is missing and Docker created a directory in its place.

```bash
ls -la ~/timesheet-app/overlay/app/      # directories where .py files should be?
```

Fix by removing them and restoring the real files — `./restore.sh` does both.

### The app is marked unhealthy during a large upload

Usually normal. In the first two to three minutes of a big batch the
recognition models are loading and the processors are saturated, so the health
check can time out. It recovers by itself. Docker may show `unhealthy` during
that window; the application is not down.

### Pages come out with no employee name

Expected for some layouts — 292 of 1,218 corpus pages, flagged not silent. See
`10-KNOWN-LIMITATIONS.md` §3. Check first whether the page is rotated 90 or
180 degrees.

### Pages are flagged that look fine

Check the reason on the page. The commonest is an identity not in the roster,
which means the roster needs updating rather than the code.

```bash
./.venv/bin/python tools/probe_false_alarms.py
```

answers "which validation rule blocks pages that were read perfectly?"

### A change seems to have had no effect

`PIPELINE_VERSION` was probably not bumped. Results are cached on page hash
plus pipeline version, so already-processed pages return their old answer.

### Accuracy has dropped

```bash
./.venv/bin/python tools/guard.py
```

It will name which floor broke. The most likely cause is a flipped flag — the
guard pins the seven that encode measured decisions.

### The header model is not working

```bash
ollama list                                        # is qwen3-vl:4b there?
systemctl is-active ollama
curl -sf http://127.0.0.1:11434/api/tags           # is it answering?
```

An empty `ollama list` with the service active means the model pull failed. The
symptom is subtle: the application works but name accuracy on handwritten
headers quietly drops. Fix with `ollama pull qwen3-vl:4b`.

---

## 5. Monthly routine

| When | Do |
|---|---|
| Before the processing window | Start the machine (`./wake.sh`), confirm `/api/health` |
| During | Watch `queue_depth`; clear flagged pages |
| After exporting | Take and **verify** a manual backup |
| Then | Stop the machine if it is not needed |
| Periodically | Update the roster as staff change; review the budget alert |

---

## 6. Things not to do

- **Do not edit a shell script while it is running.** The shell reads
  incrementally; it will execute garbage. This broke a live deploy.
- **Do not turn on the OCR angle classifier** (`TS_OCR_USE_CLS=1`) without
  running the full measurement suite. It costs about ten points on clock times.
- **Do not add an overlay mount before the file is on the server.**
- **Do not lower a floor in `guard.py`** to make a change pass.
- **Do not share one login between people.** It destroys the audit trail.
- **Do not delete the offline backup** until a cloud snapshot has actually
  been taken.
