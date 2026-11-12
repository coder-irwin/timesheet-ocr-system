# Putting It Online

Getting the system onto a server so colleagues can use it from a browser, over
HTTPS, behind a login.

Works on any provider — AWS, Azure, Google Cloud, DigitalOcean, Hetzner, or a
machine in your own office. The application is two containers and a folder; the
only thing that differs between providers is how you create the machine.

**About an hour**, most of it uploads and downloads.

> Already have Google Cloud and the `gcloud` tool? There is a script that
> creates everything in one command — see
> [`04-DEPLOY-TO-CLOUD.md`](04-DEPLOY-TO-CLOUD.md). This guide is the manual
> route, which works everywhere.

---

## What you will end up with

```
        your colleagues
              │  https://  (padlock in the browser, login required)
              ▼
    ┌─────────────────────┐
    │  Caddy              │  certificate, obtained and renewed automatically
    │                     │  username + password gate
    └──────────┬──────────┘
               │  inside the server only
               ▼
    ┌─────────────────────┐      ┌──────────────────────┐
    │  The application    │─────>│  Handwriting helper  │  optional
    └──────────┬──────────┘      └──────────────────────┘
               ▼
          data folder          database · uploads · exports
```

Nothing leaves the server. No document or employee record is sent anywhere.

---

## 1. Create a server

Whatever provider you use, ask for:

| | |
|---|---|
| Operating system | Ubuntu 24.04 (or 22.04) |
| Processors | 4 |
| Memory | **16 GB** — or 8 GB if you skip the handwriting helper |
| Disk | 100 GB for a year of scans; 30 GB to try it |
| Open ports | 80 and 443 to the internet. SSH (22) **only from your own address** |

Machine names that match, by provider:

| Provider | 4 CPU / 16 GB | 2 CPU / 8 GB |
|---|---|---|
| AWS EC2 | `t3.xlarge`, `m5.xlarge` | `t3.large` |
| Azure | `Standard_D4s_v5` | `Standard_D2s_v5` |
| Google Cloud | `e2-standard-4` | `e2-standard-2` |
| DigitalOcean | 4 vCPU / 16 GB droplet | 2 vCPU / 8 GB |
| Hetzner | `CPX41` | `CPX31` |

No graphics card is needed anywhere.

**The memory figure is the one that matters.** The handwriting helper is a
3.3 GB model that sits alongside the application. On 8 GB it will not fit, and
the setup script below detects that and switches it off for you. Measured cost
of going without it: handwritten day-status accuracy drops from 91.4% to 89.5%.

Note down the server's **public IP address** and make sure you can reach it:

```
ssh ubuntu@YOUR-SERVER-IP
```

(The username is `ubuntu` on AWS and most Ubuntu images, `root` on Hetzner and
DigitalOcean. Your provider tells you which.) Type `exit` to come back.

---

## 2. Get the code and build the application

On **your own machine**, not the server:

```
git clone https://github.com/coder-irwin/timesheet-ocr-system.git
cd timesheet-ocr-system
```

Build the container and save it as a file you can upload:

```
cd source-code
docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 .
docker save timesheet-app:2.5.0-amd64 | gzip > timesheet-app-amd64.tar.gz
cd ..
```

**5 to 10 minutes.** The result is about 320 MB.

> `--platform linux/amd64` matters if you are on an Apple Silicon Mac and your
> server is a normal Intel/AMD machine — without it you would build for the
> wrong processor. For an ARM server (AWS Graviton, Ampere) use
> `--platform linux/arm64` instead.
>
> If building locally is awkward, you can clone and build on the server itself
> and skip the upload in step 4.

---

## 3. Arrange the files

```
./deployment/prepare-deploy.sh
```

This creates a `_deploy-staging` folder containing exactly the layout the
server expects. Move the container file into it:

```
mv source-code/timesheet-app-amd64.tar.gz _deploy-staging/timesheet-app/
```

> **Why a staging step?** The repository is arranged for reading — source in
> one folder, deployment scripts in another, documentation at the top. A server
> needs them arranged differently. This script does the rearranging so you do
> not have to.

---

## 4. Upload

Replace `ubuntu@YOUR-SERVER-IP` with your own throughout.

```
cd _deploy-staging
scp -r timesheet-app gcp overlay ubuntu@YOUR-SERVER-IP:~/
```

**This uploads about 320 MB** and is the slowest step — anywhere from two
minutes to twenty depending on your connection.

Then put the two support folders where the application expects them:

```
ssh ubuntu@YOUR-SERVER-IP "mv ~/gcp ~/overlay ~/timesheet-app/"
```

---

## 5. Run the setup script

```
ssh ubuntu@YOUR-SERVER-IP
cd timesheet-app
./gcp/setup-server.sh
```

This does the rest: checks the server's size, installs Docker, installs the
handwriting helper if there is memory for it, loads the application, and then
asks you two things:

**Your web address.** Press Enter to accept the default. The default looks odd —
something like `203.0.113.45.nip.io` — but it is correct and deliberate. A
certificate authority will not issue a certificate for a bare IP address, and
`nip.io` turns an IP into a real hostname, so you get a genuine certificate and
a proper padlock without having to own a domain. If you *do* own one and have
pointed it at the server, type it instead.

**Your username and password.** The password is immediately scrambled into a
hash; the plain text is never written to disk.

It finishes by telling you whether the site is answering.

> **If it says "not answering yet"** it is almost always ports 80 and 443 not
> being open in your provider's firewall. Open them, then run the restart
> command the script prints. Certificate issuance needs port 80 reachable from
> the internet.

---

## 6. Open it

Visit **https://your-address** in a browser, sign in with the username and
password you chose. Then follow steps 6 onward in
[`RUN-IT-ON-YOUR-COMPUTER.md`](RUN-IT-ON-YOUR-COMPUTER.md) — uploading and
exporting work identically.

If you have `roster.csv` and `designations.csv`, upload them now so identities
can be matched:

```
scp roster.csv designations.csv ubuntu@YOUR-SERVER-IP:~/timesheet-app/data/
ssh ubuntu@YOUR-SERVER-IP "cd timesheet-app && sudo docker compose restart timesheet"
```

---

## 7. Adding people

Give everyone their own login. Every upload, edit and export is then recorded
against the person who did it, visible in the page history and in the `Audit`
sheet of every export. A shared login destroys that.

```
ssh ubuntu@YOUR-SERVER-IP
cd timesheet-app
./gcp/user.sh add priya          # generates a password and prints it once
./gcp/user.sh add raj mypassword # or choose it yourself
./gcp/user.sh list
./gcp/user.sh remove priya
```

Only the scrambled form is stored. Adding or removing restarts the login gate
for about two seconds; the application itself keeps running.

---

## 8. Keeping it running

```
ssh ubuntu@YOUR-SERVER-IP
cd timesheet-app
sudo docker compose ps                  # is it up?
sudo docker compose logs -f timesheet   # watch the application
```

Or from anywhere, without logging in:

```
curl -su 'yourname:yourpassword' https://your-address/api/health
```

`"ocr_ready": true` and `"queue_depth": 0` is a healthy, idle system. A
`queue_depth` that never falls means work is stuck.

**During a big upload the server may look unhealthy for two or three minutes**
while the models load and the processors saturate. It recovers by itself.

### Saving money

Compute is almost the entire bill and it stops when the machine stops. If you
process once a month, run it for that window and stop it afterwards.

| Provider | Stop | Start |
|---|---|---|
| AWS | `aws ec2 stop-instances --instance-ids i-...` | `start-instances` |
| Azure | `az vm deallocate -g GROUP -n NAME` | `az vm start -g GROUP -n NAME` |
| Google Cloud | `gcloud compute instances stop NAME --zone=ZONE` | `./gcp/wake.sh` |
| DigitalOcean | `doctl compute droplet-action power-off ID` | `power-on` |

On Azure use **deallocate**, not `stop` — plain `stop` keeps charging for
compute. Restarting takes under a minute; most of it is loading the OCR models.

### Backups

Everything that matters is in one folder. Back it up before anything
significant, and **check the backup before trusting it**:

```
ssh ubuntu@YOUR-SERVER-IP "sudo tar -czf /tmp/backup.tgz -C ~ timesheet-app"
scp ubuntu@YOUR-SERVER-IP:/tmp/backup.tgz .
tar -tzf backup.tgz | wc -l        # a file count, not an error
```

Your provider's disk-snapshot feature (EBS snapshots, Azure Backup, DigitalOcean
snapshots) is worth turning on as well. A snapshot protects against disk
failure; it does not protect against a bad change, so take your own copy first.

---

## 9. Check it properly before telling anyone

```
cd source-code
./.venv/bin/python tools/e2e_prod_test.py --url https://your-address
```

32 checks over HTTPS: that visitors without a login are refused, that your
login works, that the version running is the version you built, that a real
upload is read correctly against independent ground truth, that confidence
scores are attached, that the statuses survive into the Excel, that page
locking works, and that the audit trail names the right person.

It ends with either:

```
E2E PASSED — 32/32 checks. Safe to share.
```

or a list of what failed and `Do not share the URL until these pass.`

It needs the test fixtures, which are not in this public repository — see
"Employee data" in [`RUN-IT-ON-YOUR-COMPUTER.md`](RUN-IT-ON-YOUR-COMPUTER.md).

---

## When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| Browser: "can't reach this site" | Ports 80/443 closed in the provider firewall | Open them, then restart the containers |
| Browser: certificate warning | Certificate not issued yet | Wait two minutes. Check `sudo docker compose logs caddy` for `challenge failed` — that means port 80 is unreachable |
| `Permission denied (publickey)` on ssh | Wrong username or key | Usually `ubuntu` on AWS/Azure, `root` on Hetzner/DigitalOcean |
| A container will not start, error says `not a directory` | The `overlay` folder was not moved into `timesheet-app/` before starting | Move it, delete the empty folders Docker created in its place, start again |
| Caddy will not start at all | `gcp/users.caddy` missing or empty | The setup script creates it; re-run it |
| Site loads but every page is flagged | No employee list | Upload `roster.csv` — step 6 |
| Upload fails on a big batch | Request size limit | Caddy allows 512 MB per request; split the batch |

More in [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md), and provider
specifics in [`15-DEPLOY-TO-ANY-CLOUD.md`](15-DEPLOY-TO-ANY-CLOUD.md).

---

## One thing to know before you start

`deployment/deploy_gcp.sh` on its own does **not** produce a working server. It
uploads the application but not the `overlay` folder or the login file, and
Docker silently turns a missing folder into an empty one, after which the
container refuses to start. That is why this guide moves `overlay` and `gcp`
into place in step 4, before anything starts, and why the Google Cloud route
requires `restore.sh` afterwards.

It is the most common way a deployment here fails, and it is the reason step 4
is a separate step rather than folded into step 5.
