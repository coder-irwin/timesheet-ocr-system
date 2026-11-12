# Timesheet Extraction & Validation — Installation Guide

**Read this first. You do not need to be a programmer to follow it.**

---

## What this application does

Staff photograph or scan handwritten timesheets and upload them to a web page.
The application reads each sheet, checks the numbers add up, matches the name
against your employee list, and produces an Excel file.

Sheets it is confident about pass straight through. Sheets it is unsure about
are **flagged for a person to check** — with the original image side by side
with what was read, so corrections take seconds.

Everything runs on your own server. **No data leaves your network**, no
internet connection is required, and there are no per-page fees.

---

## What you need before you start

| | |
|---|---|
| **A server** | Windows, Linux or Mac. At least **8 GB of memory** (16 GB recommended) and **10 GB of free disk space**. |
| **Docker** | Free software that runs the application. Installation is covered in Step 2 below. |
| **This folder** | Everything else is already inside it. Nothing needs downloading. |

**Time required:** about 15 minutes.

---

## You do not need to know what processor your server has

Computers come in two processor families, and software built for one does not
run on the other. **This package contains both versions**, and the installer
detects which one your server needs and uses it automatically.

There is nothing for you to choose or configure.

---

## Step 1 — Copy this folder onto the server

Copy the whole folder to the server, for example to:

- **Windows:** `C:\timesheet-app`
- **Linux / Mac:** `/opt/timesheet-app`

Keep all the files together in one folder. Do not rearrange them.

---

## Step 2 — Install Docker (skip if already installed)

**Windows**
1. Download **Docker Desktop** from https://www.docker.com/products/docker-desktop
2. Run the installer and accept the defaults.
3. Restart the machine if it asks.
4. Open **Docker Desktop** from the Start Menu and wait until it says
   **"Engine running"** in the bottom-left corner.

**Linux (Ubuntu / Debian)**

Open a terminal and run these two lines:

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Then **log out and log back in** (this is what lets you use Docker without
typing `sudo` every time).

**Mac**

Download **Docker Desktop** from the link above and open it once installed.

> Docker needs an internet connection to *install itself*. After that, this
> application never needs the internet again.

---

## Step 3 — Run the installer

**Windows:** double-click **`install.bat`**

**Linux / Mac:** open a terminal in this folder and run:

```
./install.sh
```

The installer checks that Docker is working, loads the application, starts it,
and waits until it confirms the application is actually responding. It prints
its progress as it goes.

When it finishes you will see:

```
===============================================================
 SUCCESS -- the application is running.
===============================================================
```

If you see a `PROBLEM:` message instead, it tells you exactly what is wrong.
`TROUBLESHOOTING.md` covers every message it can produce.

---

## Step 4 — Open the application

On the server itself, open a web browser and go to:

```
http://localhost:8077
```

From any other computer on the same network, replace `localhost` with the
server's address, for example:

```
http://192.168.1.50:8077
```

> **Don't know the server's address?**
> Windows: type `ipconfig` in Command Prompt and look for "IPv4 Address".
> Linux/Mac: type `hostname -I` (Linux) or `ipconfig getifaddr en0` (Mac).

---

## Step 5 — Check it actually works

The package includes **10 real sample timesheets** so you can prove the
installation is good before trusting it with live documents.

1. In the web page, click **Upload**.
2. Select all 10 PDF files from the **`demo`** folder.
3. Wait for them to process — roughly **5 seconds per page**.
4. You should see the employee names read from the sheets, their day-by-day
   attendance filled in, and an **Export to Excel** button.

If that works, the installation is complete and correct.

---

## Running it day to day

You do not normally need to do anything — the application **starts by itself
whenever the server reboots**.

| To do this | Windows | Linux / Mac |
|---|---|---|
| Start it | `start.bat` | `./start.sh` |
| Stop it | `stop.bat` | `./stop.sh` |
| Restart it | `restart.bat` | `./restart.sh` |
| See what it is doing | `logs.bat` | `./logs.sh` |

**Stopping the application never deletes anything.**

---

## Changing settings

All settings live in one file: **`config.env`**. Open it in any text editor
(Notepad is fine). Every setting is explained in plain English inside the file.

The two most likely changes:

- **The port number** (`TS_PORT`) — if 8077 clashes with something else.
- **How strict name-matching is** (`TS_ROSTER_MIN_SCORE`) — higher means fewer
  wrong matches but more sheets sent for review.

**After editing, you must restart** (`restart.bat` or `./restart.sh`) or the
change will not take effect.

---

## Updating the employee list

A roster of **1,863 employees** is already included and working.

To update it later, **you do not need to touch any files** — an administrator
uploads the new list through the web page and it applies immediately.

---

## Your data, and backing it up

Everything the application stores lives in the **`data`** folder next to this
guide:

| Folder | What it holds |
|---|---|
| `data/roster.csv` | Your employee list |
| `data/uploads` | The original files exactly as uploaded |
| `data/pages` | One image per page |
| `data/exports` | The generated Excel files |
| `data/timesheets.db` | The database of everything read and corrected |

**To back up the application, copy the `data` folder.** That is the whole
backup. Nothing valuable is stored anywhere else, and none of it lives inside
Docker.

To restore, put the `data` folder back and run the installer again.

---

## A note on security

By default the application is reachable by anyone who can reach the server on
port 8077, **without a password**. That is normally fine on a private company
network.

**Do not put this directly on the public internet** without first asking your
IT team to put a login in front of it. It contains employee names and
attendance records.

---

## What accuracy to expect

Measured on pipeline v33 (this package), 20 September 2026. Full detail in
`source/docs/revamp/01-REVAMP-REPORT.md` §9.

**Against the paper.** Fifty pages drawn at random, none used for tuning,
every day row checked by eye against the scan:

| What is being read | Result |
|---|---|
| Day-by-day attendance | **95.6%** of rows right (96.6% by the sheet's own convention) |
| Errors caught by a flag | **99.3%** — 8 unflagged wrong rows in 1,157 |
| Employee name and code | right on about 98% of pages |
| Non-timesheet pages (printouts, cover pages, on-duty forms) | refused and marked for review, 10 of 10 |
| Pages that failed to process | **0** (of 9,003 run) |

Typed forms read at 95–99%; fully handwritten sheets are the floor at about 84%.

**Against your own typed records: 84.3%.** On the 292 pages that also exist
in the Excel files, 7,130 of 8,462 day rows matched. The difference from the
paper number is mostly how the Excel is coded (leave entered as A on one
client and L on another; a worked Sunday as W or P), plus records that
contradict each other — see below. Names matched on 98.3%.

**Every imperfect page was flagged.** Of 164 pages that were not fully
right, 164 carried a review flag and none passed silently. That, not the
percentage, is what this tool is for.

**Part of the gap is not fixable by software.** In the client's own
spreadsheets, **153 of 1,659 employee records (9.2%) contradict each other** --
the same person, same month, different attendance in different files. Those
pages have no single correct answer to be measured against. `VERIFICATION.md`
explains this, and the list can be produced for cleanup.

**Most pages will show a page-level review flag.** A timesheet is held for
review whenever its own totals cannot be checked against its rows — most
often because the "Total Man Hours" box was left blank on the paper. That is
by design. Work from the row colours: on the full run, 56% of day rows
needed no attention at all.

**Read this the right way.** This is a tool that does the first pass and shows
its working — not a replacement for human checking. It is designed so that the
sheets it gets wrong are the sheets it *flags*, which is why the review screen
exists. A person still confirms the flagged ones before anybody is paid.

For context: a person typing these by hand takes about 4 minutes per sheet.

---

## If something goes wrong

See **`TROUBLESHOOTING.md`**. It lists every error message this package can
produce and what to do about each one.

The single most useful thing you can do is run `logs.bat` (or `./logs.sh`) —
it shows what the application is reporting, and it changes nothing.
