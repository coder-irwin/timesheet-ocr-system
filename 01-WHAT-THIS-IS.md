# 01 — What This Is

No technical knowledge is assumed in this document. If a term has to be used,
it is explained where it first appears.

---

## 1. The problem being solved

AARVI ENCON supplies manpower to industrial sites — refineries, power plants,
construction projects. Each site keeps a monthly attendance sheet for the
workers posted there. At the end of the month those sheets come back to the
office so the workers can be paid and the client can be invoiced.

The sheets are a mess, through no fault of anyone:

- **They are filled in by hand.** A site supervisor ticks boxes and writes
  times with a pen. Handwriting varies enormously.
- **Every client uses a different form.** A sheet from a Technip site looks
  nothing like one from an ISGEC site. Column orders differ, labels differ,
  some have clock times and some do not, some put one worker per sheet and some
  put thirty-three workers on one sheet.
- **They arrive as scans and photographs.** Some are clean PDF scans. Many are
  phone photos: tilted, shadowed, sometimes upside down.
- **The volume is real.** This package includes 3,733 such documents from three
  regional offices covering one financial year.

Before this system, a person read each sheet and typed the contents into a
spreadsheet. That is slow, and more importantly it is the kind of work where
mistakes are invisible: a mistyped "P" instead of "A" is one worker paid for a
day they did not work, and nothing in the spreadsheet looks wrong.

---

## 2. What the system does

Think of it as a careful assistant that reads the sheets and tells you honestly
which ones it is unsure about.

**Step 1 — You upload.** Drag the sheets into a web page. PDFs, JPEGs, photos.
A whole month's worth at once if you like.

**Step 2 — It reads each sheet.** For every page it works out:
- which form family this is, and therefore where to look for things
- who the worker is (name, employee code, designation)
- which month the sheet covers
- the day grid: for each day of the month, what was recorded
- clock-in and clock-out times, where the sheet has them
- the hours totals

**Step 3 — It checks its own work.** This is the part that makes the system
useful rather than just fast. The sheet usually states its own totals — "26
days present", "208 hours". The system adds up what it read and compares. If
the day-by-day reading does not agree with the sheet's own total, something is
wrong and it says so. It also checks things like: are the weekly offs actually
falling on the same weekday each week? Is this employee in the master roster?
Is anyone recorded as working 20 hours in a day?

**Step 4 — A person reviews what was flagged.** The reviewer sees the original
scan next to the extracted grid. Anything uncertain is highlighted with a
reason. They fix it on screen and save. Every correction is recorded against
their name.

**Step 5 — Excel comes out.** One workbook containing a day-by-day detail
sheet, a monthly attendance grid, an invoice sheet, a payroll-import sheet, a
dashboard, and an audit trail of who changed what.

---

## 3. What "accuracy" means here, honestly

This is the part most easily misunderstood, so it is worth being precise.

The system reads **typed and well-structured sheets essentially perfectly.** On
the horizontal multi-employee sheets used at ISGEC sites, the most recent
measurement read **93 out of 93 day cells correctly** — every cell, for all
three workers on the sheet.

The system reads **handwriting at roughly 90%.** On 19 hand-graded handwritten
pages, it read **533 of 583 day cells correctly, or 91.4%.**

Those two numbers cannot honestly be averaged into one figure, which is why
this project does not quote a single accuracy percentage.

What matters more than either number: on those same 19 handwritten pages,
**every single page was flagged for human review.** Not one was passed off as
finished. Of the 583 cells, 31 were marked as "could not read" rather than
being guessed at. The design principle is that an unread cell must stay
visibly unread — the system is never allowed to fill in a blank with a
plausible guess, because a plausible guess is indistinguishable from a correct
reading once it is in a spreadsheet.

So the fair description of the system is:

> It removes most of the typing, and it tells you exactly which parts still
> need a human. It does not remove the human.

---

## 4. Why it runs on your own infrastructure

The sheets contain named workers' attendance records. That is personal data
about real people, and it belongs to AARVI and its clients.

The system is built so that nothing leaves the machine it runs on. The
text-recognition models are bundled inside the application itself and work with
no internet connection at all. There is no external service call in the
reading path, no API key for a third-party vision provider, nothing uploaded
anywhere. This was a deliberate design constraint from the start, not an
afterthought, and it is the reason the system can be run inside an office with
the network cable unplugged if required.

There is one optional component that reads difficult handwritten *headers* (the
worker's name at the top of a sheet). It is a model that runs on the same
machine, reached over a local-only address. It never leaves the machine either.
It can be switched off entirely with one setting, at a small cost in accuracy
on the hardest handwritten names.

---

## 5. What it is built from

Everything here is open-source and free to use commercially. There are no
licence fees and no per-page charges.

| Part | What it does |
|---|---|
| Python | The language the whole system is written in |
| RapidOCR / PP-OCRv6 | Reads text out of images. Runs locally on an ordinary processor; no graphics card needed |
| FastAPI | Serves the web pages and the upload endpoint |
| SQLite | Stores the extracted records and the audit trail. A single file on disk |
| openpyxl | Writes the Excel workbooks |
| Docker | Packages the whole thing so it runs identically everywhere |
| Caddy | Handles HTTPS and logins when deployed to a server |

The complete list with exact pinned versions is in
`source-code/requirements.txt`. Versions are pinned deliberately so that a
build next year produces the same behaviour as a build today.

---

## 6. What a running day looks like

A typical month is around 3,000 pages. On a four-processor cloud machine, with
the difficult-header reader switched on, that is roughly eight to twenty-three
machine-hours spread over the month — comfortably an overnight job, not a
round-the-clock operation. Typed sheets process in seconds. A hard handwritten
page can take one to two minutes because of the header reader.

Speed was deliberately traded away for accuracy wherever the two conflicted.
That choice is recorded in the design decisions and can be reversed with
configuration if your priorities differ — see `05-WHAT-IT-COSTS.md`, which
shows what each machine size costs and what you get for it.

---

## Where to go next

- To actually see it working: `03-SETUP-ON-A-LAPTOP.md`
- To understand the internals: `02-HOW-IT-WORKS.md`
- To know what it cannot do: `10-KNOWN-LIMITATIONS.md`
