# 04 — Deploy to Cloud

How to stand up a production instance on your own Google Cloud project.

Every step here was executed on 10 November 2026 against an empty project, and
the three defects that run uncovered are fixed in the scripts shipped in this
package. The timings are measured, not estimated.

---

## 1. What you are about to build

```
          internet
              │  HTTPS (443)
              ▼
    ┌──────────────────────┐
    │  Caddy               │  TLS certificate, obtained automatically
    │  (container)         │  Username/password gate
    │                      │  Passes the signed-in name to the app
    └──────────┬───────────┘
               │  plain HTTP, inside the machine only
               ▼
    ┌──────────────────────┐        ┌────────────────────────┐
    │  Application         │───────>│  Header model (Ollama) │
    │  (container)         │        │  on the host, local    │
    │  port 8077           │        │  address only          │
    └──────────┬───────────┘        └────────────────────────┘
               │
               ▼
      /data  (on the machine's disk, snapshotted nightly)
      database, uploads, page images, exports
```

One virtual machine. Two containers. Nothing else. No managed database, no
object storage, no load balancer — deliberately, because the whole thing has to
be able to run disconnected inside an office if required, and because a single
machine with a nightly snapshot is far easier for a small team to reason about.

---

## 2. Before you start

| | |
|---|---|
| A Google Cloud account with billing enabled | |
| `gcloud` installed and signed in | `gcloud auth login` |
| Docker installed locally | only to build the image |
| Your billing account ID | `gcloud billing accounts list` |
| A backup of any existing data | if you are replacing a running instance |

Decide two things first:

**Region.** The scripts default to `asia-south1` (Mumbai). Keep data in the
region where it legally and practically belongs.

**Machine size.** The default is `e2-standard-4` (4 processors, 16 GB). That
size is chosen because the 3.3 GB header model and two parallel readers have to
fit in memory together. Dropping to `e2-standard-2` halves the cost but will
not hold the header model — see `05-WHAT-IT-COSTS.md` for the trade.

---

## 3. Stage a deployable layout — do this first

The scripts in `deployment/` were written against the original working
directory (`gcp/` beside `timesheet-app/`). This repository is organised for
reading instead, so `deploy_gcp.sh` on its own resolves `APP_DIR` to a
directory that does not exist and every file it copies lives somewhere else.

One script bridges that:

```bash
./deployment/prepare-deploy.sh                 # stage only
./deployment/prepare-deploy.sh --build-image   # stage and build the image too
```

It creates `_deploy-staging/` containing exactly the layout the deploy script
expects: `timesheet-app/` with the compose file, `config.env`, the installer and
`data/` holding the roster and designation vocabulary; `gcp/` with the Caddy
config, the production compose file and all the deployment scripts; the
application `overlay/`; and a skeleton restore bundle.

Verified: after running it, every path `deploy_gcp.sh` reads resolves. The only
thing it cannot produce without Docker is the image, covered next.

Deploy from `_deploy-staging/gcp/`, not from `deployment/`.

## 4. Build the image

The deployment uploads a prebuilt image rather than building on the server, so
the server needs no build toolchain and the image is identical to the one you
tested.

```bash
cd source-code
docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 .
docker save timesheet-app:2.5.0-amd64 | gzip > timesheet-app-amd64.tar.gz
```

`--platform linux/amd64` matters if you are building on an Apple Silicon Mac.
The result is roughly 320 MB compressed.

---

## 5. Deploy

```bash
cd deployment
PROJ=your-project-id \
BILLING=XXXXXX-XXXXXX-XXXXXX \
ZONE=asia-south1-a \
TEAM_PASS='a-strong-password' \
CLIENT_PASS='another-strong-password' \
  ./deploy_gcp.sh
```

The script is idempotent: anything that already exists is skipped, so it is
safe to re-run after a failure. In eight steps it creates the project if
needed, reserves a static IP address, opens the firewall (only 80 and 443 to
the internet; administrative access goes through Google's own tunnel, not an
open SSH port), creates the machine, installs Docker and the header model, sets
up a nightly snapshot keeping seven days, uploads the image and configuration,
starts both containers, and sets a billing budget alert.

Measured timings from the 10 November run:

| Step | Time |
|---|---|
| Machine created and booted, Docker and the 3.3 GB model installed | 11 min 42 s |
| Image uploaded through the administrative tunnel | 10–20 min |
| Containers started, certificate obtained | ~2 min |

### The URL

The script prints it. It takes the form:

```
https://<your-static-ip>.nip.io
```

That looks odd but is correct and intentional. `nip.io` is a public DNS service
that resolves `1.2.3.4.nip.io` to `1.2.3.4`. Because it is a real hostname, the
certificate authority will issue a genuine certificate for it, so the site gets
proper HTTPS with no browser warning — without you having to own a domain.

If you do have a domain, point it at the static IP and pass `SITE=your.domain`
instead. Everything else is unchanged.

---

## 6. Restore data, and why this step is not optional

**`deploy_gcp.sh` on its own produces a machine that will not start.** This is
the most important thing in this document.

The production compose file bind-mounts thirteen application files from an
`overlay/` directory, and the Caddy configuration does `import users.caddy`.
The deploy script uploads neither. When a bind-mount's source path does not
exist, Docker does not raise an error — it **creates an empty directory** at
that path. The container then tries to import a directory where a code file
should be, and refuses to start. Caddy will not start at all without its user
file.

`restore.sh` exists to handle this correctly:

```bash
./restore.sh /path/to/your-backup.tgz
```

In six steps it uploads the bundle, stops the containers, **clears every
overlay mount point** (removing whatever empty directory Docker left), extracts
the data, verifies every required file is present *before* starting anything,
starts the containers, and then confirms the running container is actually
serving the overlay by checking file sizes from inside it — rather than
trusting the version string, which stays correct even when the code is wrong.

The bundle it expects is a gzipped tar containing:

```
data/timesheets.db          the database
data/uploads/               original uploaded files
data/pages/                 rendered page images
data/exports/               generated workbooks
data/roster.csv
data/designations.csv
overlay/app/*.py            the application overlay
overlay/*.html
gcp/users.caddy             the login file
```

For a fresh install with no prior data, build a bundle with just `overlay/`,
`gcp/users.caddy` and the two CSVs.

### The login file

`users.caddy` holds one line per person: a username and a hashed password.
A template is at `deployment/users.caddy.example`. Generate a hash with:

```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'the-password'
```

Or manage people with the helper, which generates a password, prints it once,
and restarts only the login gate:

```bash
./user.sh add <name>
./user.sh remove <name>
./user.sh list
```

Every upload, edit and export is then stamped with that person's name in the
page history and in the `Audit` sheet of every export.

---

## 7. Verify before you give anyone the URL

```bash
cd source-code
./.venv/bin/python tools/e2e_prod_test.py --url https://<your-site>
```

Thirty-two checks against the live server over HTTPS: that anonymous requests
are refused, that the login works, that the version actually running matches
your source, that an upload is read correctly against independent ground truth,
that per-row confidence is attached, that the statuses survive into the Excel,
that page locking works, and that the audit trail attributes to the right
person.

It ends in one of two ways:

```
E2E PASSED — 32/32 checks. Safe to share.
```

or a list of failures and `Do not share the URL until these pass.`

It leaves a test batch behind and tells you its id. Delete it before anyone
sees the home screen.

Note the test reads credentials from a local file and never prints them.

---

## 8. Three defects this process uncovered

All three are fixed in the scripts here. They are documented because each one
failed **silently**, and silent failures are the ones that reach production.

**Billing re-link.** `gcloud billing projects link` against a project that is
already linked fails with `FAILED_PRECONDITION: Cloud billing quota exceeded`.
Billing was entirely fine; the no-op call aborted the deploy. Now guarded by a
check of the current state first.

**The header model never installed.** The startup script ran `ollama pull`
after a bare `sleep 5`, lost the race against the service starting, ignored the
failure, and marked the machine as provisioned anyway. The machine came up
looking healthy with no header model — and the only symptom would have been
quietly worse name accuracy. It now waits for the service to answer, retries
three times, and only marks provisioning complete if the model is genuinely
present, so a failure stops the deploy loudly.

**Never edit a shell script while it is running.** The shell reads a script
incrementally, so editing one mid-run makes it execute garbage from a shifted
file offset. This broke a live deploy during this very exercise.

---

## 9. Turning it off

Compute is the overwhelming majority of the cost, and it stops the moment the
machine stops.

```bash
gcloud compute instances stop timesheet-prod --zone=asia-south1-a   # stop
./wake.sh                                                           # start again
```

`wake.sh` starts the machine, brings the containers up, and polls until the
application reports ready. A measured cold start from fully stopped:

| | |
|---|---|
| Machine running | 13 s |
| Operating system booted | 43 s |
| Containers up | 48 s |
| Public URL answering | 53 s |
| Text recognition ready | 56 s |

There is also `autosleep.sh`, a scheduled job that stops the machine after
three hours of genuine idleness. It checks three things first: no work in
flight, no human action in the audit trail, and the application answering. It
ships **disabled** — a machine that sleeps looks like a broken application to
someone clicking a link, so only enable it once usage is predictable.

**One architectural limitation to understand.** The URL is the machine's own IP
address. With the machine stopped, nothing exists to receive a request and wake
it up. Automatic wake-on-request would need a second always-on component
holding the address. For a system with scheduled monthly use, stopping and
starting deliberately is simpler and cheaper.

---

## 10. Backups

The deploy sets up nightly snapshots with seven days kept. Two things to know:

- The **first** snapshot does not exist until the schedule first fires. Until
  then you have no cloud-side backup, so keep an offline copy.
- A snapshot protects against disk loss, not against a bad change. For
  anything significant, take your own copy of `/data` first.

To take one by hand:

```bash
gcloud compute ssh timesheet-prod --zone=asia-south1-a --tunnel-through-iap \
  --command 'sudo tar -czf /tmp/backup.tgz -C ~ timesheet-app'
gcloud compute scp timesheet-prod:/tmp/backup.tgz ./ --zone=asia-south1-a --tunnel-through-iap
```

Verify any backup before relying on it: check the archive extracts, and run
`PRAGMA integrity_check` against the database inside it.

---

## Next

- The money: `05-WHAT-IT-COSTS.md`
- Running it day to day: `12-OPERATIONS-RUNBOOK.md`
