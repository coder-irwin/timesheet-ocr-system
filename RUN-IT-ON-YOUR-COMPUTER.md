# Running It On Your Computer

The fastest way to see the system working: on one machine, in your own browser,
reading real timesheets. About 20 minutes, mostly waiting for a download.

Everything you need to type is in a box. Click into your terminal, paste the
line, press Enter.

> **Opening a terminal.** Windows: Start → type `powershell` → Enter.
> macOS: `Cmd`+`Space` → type `terminal` → Enter. Linux: `Ctrl`+`Alt`+`T`.

---

## 1. Docker

The application ships as a container — a sealed package holding the app and
everything it depends on, including the handwriting-recognition models. That is
what lets it run identically on any machine, and with no internet connection
once built.

Install **Docker Desktop** from
[docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/),
then **open it and leave it running.** The whale icon in your menu bar or system
tray stops animating when it is ready.

```
docker --version
```

Expect something like `Docker version 29.9.3`. If you get `command not found`,
Docker Desktop is not running yet — give it a minute.

*On a Linux server instead of a desktop:* `curl -fsSL https://get.docker.com | sh`

---

## 2. Get the code

```
git clone https://github.com/coder-irwin/timesheet-ocr-system.git
cd timesheet-ocr-system/source-code
```

No `git`? Install it from [git-scm.com/downloads](https://git-scm.com/downloads),
then open a new terminal and retry.

> `cd` means "change directory" — it moves you into a folder. Every command
> from here on assumes you are inside `source-code`.

---

## 3. Build the container

```
docker build -t timesheet-app:local .
```

**5 to 10 minutes**, with a lot of text scrolling past. It is installing the
dependencies and baking the OCR models into the image, which is why the running
container never needs network access.

It worked if the last lines include:

```
baked OCR models: ['PP-OCRv6_det_small.onnx', ...]
app imports OK
naming to docker.io/library/timesheet-app:local done
```

Those two middle lines are deliberate self-checks in the Dockerfile — the build
fails rather than producing an image whose models are missing or whose code
does not import.

You only do this once.

---

## 4. Start it

```
mkdir -p data
docker run --rm -p 8077:8077 -v "$(pwd)/data:/data" timesheet-app:local
```

Windows PowerShell:

```
mkdir data
docker run --rm -p 8077:8077 -v "${PWD}/data:/data" timesheet-app:local
```

Startup messages fill the terminal and then it appears to hang. **That is it
running.** Leave the window open.

> `-p 8077:8077` publishes the container's port so your browser can reach it.
> `-v ./data:/data` mounts a folder from your machine, so the database,
> uploads and exports persist when the container stops.

---

## 5. Open it

**http://127.0.0.1:8077**

You should see *Timesheet Digitiser*. There is no login — the container is
bound to your own machine and nothing outside it can connect.

Worth checking:

```
curl -s http://127.0.0.1:8077/api/health
```

`"ocr_ready": true` means the recognition models loaded. `"pipeline"` tells you
which version is running.

---

## 6. Read a timesheet

1. **Upload** — a PDF, a scan, or a phone photo. A batch at once is fine.
2. Wait. Typed sheets take seconds; handwritten ones up to a minute or two.
3. Click the page. You get the original scan beside the grid that was read from
   it, with anything uncertain marked and a named reason.
4. **Export** — an Excel workbook with six sheets: day-by-day detail, a monthly
   attendance grid, invoice, payroll import, dashboard, and an audit record of
   who changed what.

> **Every page will be flagged the first time, and that is correct.** This
> download deliberately contains no employee data, so no name can be matched
> against the employee list and the system says so rather than guessing. Put
> `roster.csv` and `designations.csv` into `data/` and restart to fix it — see
> "Employee data" below.

---

## 7. Stop and start

Stop: click the terminal, press `Ctrl`+`C`.

Start again — no rebuild needed:

```
cd timesheet-ocr-system/source-code
docker run --rm -p 8077:8077 -v "$(pwd)/data:/data" timesheet-app:local
```

Everything you uploaded, corrected and exported is still in `data/`.

---

## Employee data

Two files make the difference between "reads the sheet" and "knows who it is
about":

| File | What it does |
|---|---|
| `roster.csv` | The employee list. Without it, no identity can be matched and every page is flagged |
| `designations.csv` | Job-title vocabulary, used to correct misread titles |

They are not in this repository — they are personal data about real people.
Obtain them from whoever owns the data and drop them into
`source-code/data/`, then restart.

The evaluation harnesses in `source-code/tools/` need test fixtures for the
same reason, so they will not run here either.

---

## Without Docker

If you would rather run it directly:

```
cd source-code
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run.sh
```

Python **3.11 or 3.12** is the verified combination; 3.14 also works. On
Windows: `python -m venv .venv`, then
`.venv\Scripts\pip install -r requirements.txt`, then `run.bat`.

There is a Makefile with the commands worth knowing:

```
make help     # list them
make run      # start the app
make fast     # score extraction against frozen OCR output, ~1 second
```

---

## When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| `docker: command not found` | Docker Desktop not installed or not started | Open it, wait for the whale to settle |
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Open it |
| `port is already allocated` | Something else holds 8077 | Use `-p 8078:8077`, open `http://127.0.0.1:8078` |
| Page will not load | Still starting | Wait 30 seconds, refresh |
| `ocr_ready: false` | Models failed to load | Rebuild; check the build output for the "baked OCR models" line |
| An uploaded page comes out empty | Scan is rotated 90° or 180° | Rotate and re-upload. There is an automatic recovery path, but it only triggers when extraction finds nothing at all |
| Everything says "needs review" | No employee list | See "Employee data" above |
| `ModuleNotFoundError: No module named 'app'` | Running from the wrong folder, or system Python | Run from `source-code`, using `.venv` |

---

## Next

| | |
|---|---|
| Make it reachable by colleagues | [`PUT-IT-ONLINE.md`](PUT-IT-ONLINE.md) |
| Understand what it does and why | [`01-WHAT-THIS-IS.md`](01-WHAT-THIS-IS.md), then [`02-HOW-IT-WORKS.md`](02-HOW-IT-WORKS.md) |
| Know what it cannot do | [`10-KNOWN-LIMITATIONS.md`](10-KNOWN-LIMITATIONS.md) — worth ten minutes before promising anything |
| Change the code | [`06-ACCURACY-AND-TESTING.md`](06-ACCURACY-AND-TESTING.md) first, then [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) |
