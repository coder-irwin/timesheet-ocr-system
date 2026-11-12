# 05 — What It Costs

Every figure here was derived from Google's own Cloud Billing Catalog for
`asia-south1` (Mumbai) on 9 November 2026, with the arithmetic shown so you can
re-derive or update it. Nothing is a vendor estimate or a remembered number.

---

## 1. Software licensing: nothing

There are no licence fees, no subscriptions and no per-page charges. Every
component is open source and free for commercial use: Python, RapidOCR with the
PP-OCRv6 models, FastAPI, SQLite, openpyxl, Caddy, Docker, and the optional
header model. The system makes no call to any paid service. If you run it on
an office machine, the running cost is electricity.

The costs below are therefore **only** what Google Cloud charges for the
machine, if you choose to deploy it there.

---

## 2. The unit prices

| Resource | Price |
|---|---|
| E2 processor | $0.0261993 per vCPU-hour |
| E2 memory | $0.00351072 per GiB-hour |
| Balanced persistent disk | $0.12 per GiB-month |
| Standard persistent disk | $0.048 per GiB-month |
| External IP, attached to a running machine | $0.005 per hour |
| External IP, reserved while the machine is stopped | **$0.012 per hour** |
| Snapshot storage | $0.052 per GiB-month |

A month is taken as 730 hours throughout.

**Note the IP line.** A reserved address costs *more* while the machine is
stopped than while it is running. This is correct and intended by the provider
— it discourages hoarding addresses. It is also counter-intuitive, and it means
stopping a machine makes one line on your bill go **up**.

---

## 3. Machine size options

Compute only, running continuously:

| Machine | Processors | Memory | Per hour | Per month | With sustained-use discount |
|---|---|---|---|---|---|
| `e2-standard-2` | 2 | 8 GiB | $0.08048 | $58.75 | ~$41.13 |
| **`e2-standard-4`** | **4** | **16 GiB** | **$0.16097** | **$117.51** | **~$82.26** |
| `e2-standard-8` | 8 | 32 GiB | $0.32194 | $235.01 | ~$164.51 |

`e2-standard-4` is the shipped default. The reason is memory, not speed: the
3.3 GB header model plus two parallel readers do not fit in 8 GiB. Choosing
`e2-standard-2` saves about $59 a month and means switching the header model
off, which measurement puts at roughly two percentage points of day-status
accuracy on handwritten sheets (91.4% against 89.5% on the same 19 pages).

The "sustained-use discount" is applied automatically by the provider for
machines that run most of a month. It is roughly 30% on compute. It is not a
negotiated rate and needs no action.

---

## 4. Running continuously

`e2-standard-4`, 100 GB disk, static IP, nightly snapshots:

| Line | Per month |
|---|---|
| Compute | $117.51 |
| Disk, 100 GB balanced | $12.00 |
| Static IP, attached | $3.65 |
| Snapshots (~10 GiB incremental, 7 kept) | $0.52 |
| Network egress, observed under light use | ~$2.00 |
| **Total at list price** | **$135.68** |
| **Total with the sustained-use discount** | **~$100.43** |

At roughly ₹88 to the dollar: **about ₹11,900 a month at list, or ₹8,800 with
the discount.**

> **A correction worth recording.** An earlier internal note put this at about
> $115 a month. That figure was too low. It used a stale compute price and put
> the IP at $3 a month rather than the $8.76 that actually applies to a reserved
> address. The numbers in this document are derived from the live price catalog
> and the arithmetic is shown above. If a ₹10,000 monthly ceiling matters, note
> that list price exceeds it and the discounted rate sits under it — so the
> ceiling holds only once the machine has been running long enough to earn the
> discount.

---

## 5. Stopped, with all data kept

| Line | Per month |
|---|---|
| Disk, 100 GB | $12.00 |
| Static IP, reserved (the higher rate) | $8.76 |
| Snapshots | $0.52 |
| **Total** | **$21.28** |

**About ₹1,900 a month.** Compute drops to nothing. Nothing is lost; starting
back up takes 56 seconds, measured.

For a system used in a monthly cycle this is the arrangement that makes sense:
run it during the processing window, stop it the rest of the time. Ten days of
use a month works out at roughly $60 rather than $136.

---

## 6. Getting to genuinely zero

If you need the bill to be nothing at all, every stored resource has to go,
which means getting the data off the cloud first:

| Action | Saves | Cost of doing it |
|---|---|---|
| Stop the machine | $117.51/mo | 56-second cold start |
| Snapshot the disk, then delete the disk | $12.00/mo | Rebuild takes 10–15 min instead of 56 s |
| Release the static IP | $8.76/mo | **The URL changes permanently** |
| Delete the snapshots | $0.52/mo | No cloud-side backup remains |

Releasing the address is irreversible: it returns to the provider's pool and
the old URL stops working for good. Only do it with an offline backup verified
first — meaning the archive extracts and the database passes
`PRAGMA integrity_check`.

---

## 7. Running it on your own hardware instead

Worth considering seriously. Measured throughput is 8 to 23 machine-hours for a
3,000-page month. That is an overnight job on one ordinary desktop.

| | Cloud `e2-standard-4` | One office desktop |
|---|---|---|
| Monthly cost | ₹8,800–11,900 | Electricity |
| Setup | `deploy_gcp.sh` | `03-SETUP-ON-A-LAPTOP.md` |
| Access from other offices | Yes, over HTTPS | Only on the local network, unless you expose it |
| Data leaves the premises | Yes, to the provider's region | No |
| Backups | Automatic nightly snapshots | Yours to arrange |

The deciding question is usually access, not cost: if several offices need to
use it, the cloud deployment pays for itself in avoided coordination. If one
team does the processing, a desktop is cheaper and keeps the data in the
building.

---

## 8. Keeping track of spend

**Budget alert.** `deploy_gcp.sh` sets one automatically at 80% and 100% of a
configurable ceiling, defaulting to ₹10,000. This does not cap spending — the
provider has no hard cap — it emails you.

**The built-in cost page.** There is a page at `/cost`, not linked from the
menu, that shows this project's cloud spend only. It works in two modes and
labels which one it is using:

- `ESTIMATE` — list prices multiplied by hours, *before* the sustained-use
  discount, so it reads high by roughly 30%.
- `EXACT` — real billed figures including discounts, credits and tax, taken
  from the provider's billing export. Lags a few hours.

Getting to `EXACT` needs two one-time steps, both of which only an account
owner can do and one of which has no API at all, so it cannot be scripted:

1. Run the commands in `deployment/enable_cost_scope.sh`, which grant the
   machine permission to read billing data (about a minute of downtime).
2. In the Cloud console: Billing → your account → Billing export → BigQuery
   export → Standard usage cost → select the project and a dataset named
   `billing` → Save.

Until step 2 is done the page says `ESTIMATE`. **At the time of this handover
it has not been done**, so that page has only ever shown estimates.

---

## 9. One-line summary

| Arrangement | Monthly |
|---|---|
| Cloud, running continuously | ₹8,800 – ₹11,900 |
| Cloud, run ~10 days a month | ~₹5,300 |
| Cloud, stopped with data kept | ~₹1,900 |
| Cloud, everything deleted | ₹0 (data must be moved off first) |
| Own hardware | Electricity |
| Software licences, any arrangement | ₹0 |
