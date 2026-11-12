# Troubleshooting

Work down this page in order. The first section solves most problems.

---

## The one command that tells you what is wrong

**Windows:** double-click `logs.bat`
**Linux / Mac:** run `./logs.sh`

This shows what the application is reporting, live. It only reads — it cannot
break anything. Press **Ctrl+C** to stop watching.

Also useful, to see whether the application is running at all:

```
docker compose --env-file config.env ps
```

- `Up (healthy)` — running correctly.
- `Up (unhealthy)` — running but not answering. See "It starts then stops".
- `Exited` — it stopped. The logs will say why.
- Nothing listed — it was never started. Run the installer.

---

## Messages from the installer

### "Docker is not installed on this server."
Docker was never installed. Go back to **Step 2** in `START-HERE.md`.

### "Docker is installed but is not running."
- **Windows / Mac:** open **Docker Desktop** and wait for "Engine running",
  then run the installer again.
- **Linux:** run `sudo systemctl start docker`.
- **Linux, and it says "permission denied":** your user is not allowed to use
  Docker yet. Run `sudo usermod -aG docker $USER`, then **log out and log back
  in**. Logging back in is required — it does not take effect otherwise.

### "unrecognised processor type"
This package contains Intel/AMD and ARM versions, which covers every normal
server. Seeing this means the machine is something unusual. Send the output of
`uname -m` to whoever supports this application.

### "timesheet-app-amd64.tar.gz is missing from this folder."
The package is incomplete — most often because only some files were copied to
the server. Copy the **whole folder** again, and check the file list at the
bottom of this page.

### "data/roster.csv is missing"
Only a warning; the application still runs. It just cannot match employee names
until someone uploads a roster through the web page.

---

## The web page will not open

**1. Is it actually running?**
```
docker compose --env-file config.env ps
```
If nothing is listed, run the installer (`install.bat` / `./install.sh`).

**2. Are you using the right address?**
From the server itself: `http://localhost:8077`
From another computer: `http://<server-address>:8077` — the `http://` and the
`:8077` both matter. Note it is **http**, not https.

**3. Is a firewall blocking it?**
This is the most common cause when it works on the server but not from another
computer.

- **Windows:** Windows Defender Firewall → Advanced Settings → Inbound Rules →
  New Rule → Port → TCP → 8077 → Allow.
- **Linux:** `sudo ufw allow 8077`

**4. Is something else using port 8077?**
Open `config.env`, change `TS_PORT=8077` to something else such as
`TS_PORT=8090`, save, and restart. Then use the new number in the address.

---

## It starts, then stops again

Run `logs.bat` / `./logs.sh` and look at the last lines.

**"exec format error"** — the package is built for a different processor than
this server. See the ARM message above.

**"port is already allocated"** — something else on the server already uses
port 8077. Change `TS_PORT` in `config.env` and restart.

**"no space left on device"** — the server's disk is full. The application
needs room for uploaded documents and images. Free up space, or move the
`data` folder to a bigger disk.

**Killed / "out of memory"** — the server does not have enough memory. This
needs 8 GB minimum. If other heavy software runs on the same machine, it may
need more.

---

## It runs, but reading is poor

**Every sheet is flagged for review.** Check that the employee roster loaded:
open `http://<server>:8077/api/health` in a browser and look for
`"roster_loaded":true` and a sensible `roster_size`. If it says `false` or `0`,
upload the roster again through the web page.

**Names match the wrong person.** Raise `TS_ROSTER_MIN_SCORE` in `config.env`
(try 88), then restart. Higher means the system refuses to guess and asks a
person instead.

**Too many sheets flagged over small hour differences.** The monthly total is
being compared strictly against the daily entries. Slightly raise
`TS_SUM_TOLERANCE_PCT` (for example 0.03 for 3%), then restart.

**Faint pencil is being missed.** Raise `TS_PAGE_LONG_EDGE` to 2000 in
`config.env` and restart. This makes processing noticeably slower and use more
memory. Change nothing else at the same time, or you will not know what helped.

**Everything is slower than expected.** Expect roughly **5 seconds per page**.
If it is far slower, check that the optional AI fallback was not switched on —
`TS_VLM_HEADER` should be `0` in `config.env`.

---

## Upload fails on a very large batch

Uploading many files at once can make the browser give up waiting, even though
the server is still working through them correctly.

**Upload in batches of 50–100 files.** The result is identical and you get
feedback sooner.

---

## Starting over from scratch

This removes the application but **keeps all your data**:

```
docker compose --env-file config.env down
docker image rm timesheet-app:1.0.0
```

Then run the installer again.

> To also erase all documents, corrections and exports, delete the `data`
> folder — but **back it up first**. That folder is the only copy.

---

## Checking the package is complete

The folder you were given should contain all of these:

```
START-HERE.md                 the installation guide -- read this first
TROUBLESHOOTING.md            this file
VERIFICATION.md               the test results from before this was packaged
config.env                    all settings, in plain English
docker-compose.yml            how the application is run
timesheet-app-amd64.tar.gz    the application, for Intel/AMD servers
timesheet-app-arm64.tar.gz    the application, for ARM servers
install.sh / install.bat      one-time setup (picks the right one for you)
start / stop / restart / logs  (.sh and .bat)  day-to-day control
data/roster.csv               the employee list (1,863 employees)
demo/                         10 sample timesheets for testing
source/                       the full source code, for your developers
```

Both processor versions are included on purpose. The installer loads only the
one your server needs; the other is simply ignored and can be deleted if you
want to save disk space.

If anything is missing, ask for the package again rather than trying to work
around it.

---

## Still stuck

Send whoever supports this application:

1. The output of `logs.bat` / `./logs.sh`
2. The output of `docker compose --env-file config.env ps`
3. What you typed into the browser, and what it showed
4. The server's operating system, and the result of `uname -m` (Linux/Mac) or
   `echo %PROCESSOR_ARCHITECTURE%` (Windows)

Those four things are almost always enough to identify the problem.
