# 15 — Deploy to Any Cloud (or Your Own Hardware)

`04-DEPLOY-TO-CLOUD.md` covers Google Cloud, because that is where this system
was first deployed and where the automation scripts were written. **Nothing
about the application requires Google Cloud.** This document covers AWS, Azure,
any VPS provider, and bare metal.

---

## 1. What the application actually requires

Strip away the provider and this is the whole dependency list:

| Requirement | Detail |
|---|---|
| A Linux machine | Ubuntu 22.04 or 24.04 verified; any modern distro with Docker works |
| Processors | 4 vCPU recommended, 2 minimum |
| Memory | **16 GB** if the handwritten-header model is enabled, **8 GB** without it |
| Disk | 100 GB for a year of scans at the volumes measured here; 20 GB to try it |
| Graphics card | **None.** Everything runs on the processor |
| Docker | Engine plus the Compose plugin |
| Inbound ports | 80 and 443 only |
| Outbound | Needed once, to pull images and obtain a certificate. Not needed to process documents |

That is it. No managed database, no object storage, no load balancer, no
message queue, no cloud-specific service of any kind. The deployment is two
containers and one directory on disk.

**The memory figure is the one that bites.** The header model is 3.3 GB and has
to sit alongside two OCR workers. On an 8 GB machine, set `TS_VLM_HEADER=0`.
Measured cost of doing so: 91.4% → 89.5% day status on handwritten pages.

---

## 2. Picking a machine

Specifications, not prices — prices change and vary by region, so check the
provider's current rates. The method in `05-WHAT-IT-COSTS.md` (unit price ×
hours, with the arithmetic shown) transfers to any provider.

| Provider | 4 vCPU / 16 GB | 2 vCPU / 8 GB (header model off) |
|---|---|---|
| AWS EC2 | `t3.xlarge`, `m5.xlarge`, `m6i.xlarge` | `t3.large` |
| Azure | `Standard_D4s_v5`, `Standard_D4as_v5` | `Standard_D2s_v5` |
| Google Cloud | `e2-standard-4` | `e2-standard-2` |
| DigitalOcean | 4 vCPU / 16 GB droplet | 2 vCPU / 8 GB droplet |
| Hetzner | `CPX41`, `CCX23` | `CPX31` |
| Linode / Akamai | Dedicated 16 GB | Dedicated 8 GB |

Burstable instance types (`t3`, `B`-series) are fine. OCR work is bursty by
nature — a monthly batch, then idle — which suits a credit model well. Watch
credit exhaustion on a long batch; if a run slows dramatically part-way
through, that is the cause.

**Compute dominates the bill and stops when the machine stops.** For a monthly
processing cycle, run it during the window and stop it afterwards. On every
provider that is the single biggest saving available.

---

## 3. Deploying to any Linux machine

### 3.1 Build the image

On your own machine:

```bash
cd source-code
docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 .
docker save timesheet-app:2.5.0-amd64 | gzip > timesheet-app-amd64.tar.gz
```

`--platform linux/amd64` matters if you are building on an Apple Silicon Mac
and deploying to an x86 server. For an ARM server (AWS Graviton, Ampere), drop
the flag or use `--platform linux/arm64` — the build works on both, and ARM is
often cheaper per unit of work.

Alternatively build on the server itself and skip the transfer. It needs
Docker and about 10 minutes.

### 3.2 Stage the files

```bash
./deployment/prepare-deploy.sh
```

This assembles `_deploy-staging/` with the layout the compose files expect.
See `04-DEPLOY-TO-CLOUD.md` §3 for what it does and why it is needed.

### 3.3 Prepare the server

```bash
ssh user@your-server
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in
```

Optional, for the handwritten-header model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\nEnvironment=OLLAMA_KEEP_ALIVE=2h\n' \
  | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
# wait for it to answer BEFORE pulling -- see 04-DEPLOY-TO-CLOUD.md §8
until curl -sf http://127.0.0.1:11434/api/tags >/dev/null; do sleep 2; done
ollama pull qwen3-vl:4b
ollama list | grep -q qwen3-vl || echo "PULL FAILED -- do not proceed"
```

That last check matters. A silent pull failure leaves a server that looks
healthy with no header model, and the only symptom is quietly worse name
accuracy.

### 3.4 Copy and start

```bash
# from _deploy-staging/
scp -r timesheet-app gcp overlay user@your-server:~/
ssh user@your-server
cd ~/timesheet-app
docker load -i timesheet-app-amd64.tar.gz
docker tag timesheet-app:2.5.0-amd64 timesheet-app:2.0.0   # compose expects this tag

# the overlay and login file must be in place BEFORE compose starts
mv ~/overlay ~/timesheet-app/overlay
mv ~/gcp     ~/timesheet-app/gcp

# login file: one "name hash" line per person
docker run --rm caddy:2 caddy hash-password --plaintext 'your-password'
printf 'team <paste-the-hash>\n' > gcp/users.caddy

# the site name, used for the certificate
printf 'SITE=your.domain.com\nTEAM_HASH=unused\nCLIENT_HASH=unused\n' > .env

docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \
  --env-file config.env --env-file .env up -d
docker compose ps
```

**The overlay must exist before compose starts.** Docker turns a bind-mount
with a missing source path into an empty *directory*, and the container then
tries to import a directory where a module should be. It will refuse to start.
This is the single most common deployment failure here.

---

## 4. HTTPS without owning a domain

Caddy obtains and renews a certificate automatically, but a certificate
authority will not issue one for a bare IP address.

**With a domain:** point an A record at the server's IP, set
`SITE=your.domain.com`. Done.

**Without a domain:** use a wildcard DNS service that resolves a hostname
containing the IP:

```
SITE=203.0.113.45.nip.io      # for a server at 203.0.113.45
```

`nip.io` resolves `<ip>.nip.io` to `<ip>`. Because it is a real hostname, a
genuine certificate is issued and browsers show no warning. `sslip.io` works
the same way. This is what the Google Cloud deployment uses.

Caddy needs ports 80 and 443 reachable from the internet for the challenge. If
80 is blocked, certificate issuance fails with a `challenge failed` error in
the Caddy log.

---

## 5. What differs per provider

Only three things, and all are provisioning concerns rather than application
ones.

### Firewall

Allow 80 and 443 from anywhere. Restrict SSH to your own address — do not
leave 22 open to the world.

| Provider | Where |
|---|---|
| AWS | Security group inbound rules |
| Azure | Network security group |
| Google Cloud | VPC firewall rules (`allow-web`, created by `deploy_gcp.sh`) |
| DigitalOcean | Cloud Firewall |
| Hetzner | Firewall, or `ufw` on the box |
| Bare metal | `ufw allow 80,443/tcp` and restrict 22 |

The Google Cloud setup routes administrative access through Google's own
tunnel rather than an open SSH port. The equivalents are AWS Systems Manager
Session Manager and Azure Bastion. Both are worth using; neither is required.

### Backups

Everything that matters lives in one directory: `~/timesheet-app/data`. Back
up a volume snapshot, or just that directory.

| Provider | Mechanism |
|---|---|
| AWS | EBS snapshots, or Data Lifecycle Manager for a schedule |
| Azure | Managed disk snapshots, or Azure Backup |
| Google Cloud | Disk snapshot schedule (`deploy_gcp.sh` sets one up, 7 days) |
| DigitalOcean | Droplet snapshots or volume snapshots |
| Bare metal | `tar -czf` on a cron, to somewhere else |

Whatever you choose, **verify a backup before relying on it**: confirm the
archive extracts and that the database passes `PRAGMA integrity_check`. The
procedure is in `12-OPERATIONS-RUNBOOK.md` §3.

### Stopping and starting

| Provider | Stop | Start |
|---|---|---|
| AWS | `aws ec2 stop-instances --instance-ids i-...` | `start-instances` |
| Azure | `az vm deallocate -g RG -n NAME` | `az vm start` |
| Google Cloud | `gcloud compute instances stop NAME` | `./wake.sh` |
| DigitalOcean | `doctl compute droplet-action power-off ID` | `power-on` |

On Azure use **deallocate**, not `stop` — plain `stop` keeps billing compute.
Measured cold start on Google Cloud was 56 seconds to full readiness; expect
something similar elsewhere, dominated by loading the OCR models.

---

## 6. What of the Google Cloud tooling transfers

| Script | Transfers? |
|---|---|
| `prepare-deploy.sh` | **Yes**, provider-neutral |
| `Caddyfile`, `docker-compose.prod.yml`, `overlay/` | **Yes**, plain Docker |
| `user.sh` | Logic yes, transport no — it reaches the server with `gcloud compute ssh`. Swap in plain `ssh` |
| `restore.sh` | Same: replace `gcloud compute ssh/scp` with `ssh`/`scp`. §7 below |
| `deploy_gcp.sh` | **No.** It creates Google Cloud resources. §3 above is the manual equivalent |
| `wake.sh`, `autosleep.sh` | **No.** They call Google Cloud APIs. The table in §5 gives the equivalents |
| `cost_collector.py`, `cloudcost.py`, the `/cost` page | **No.** They query Google's billing API. The page will report nothing on another provider |

So: the application and its configuration are fully portable. Only
provisioning, power control and cost reporting are provider-specific, and all
three are a handful of commands.

---

## 7. Restoring on a non-Google server

`restore.sh` does the right things in the right order but reaches the machine
with `gcloud`. The equivalent with plain SSH:

```bash
BUNDLE=/path/to/restore.tgz
HOST=user@your-server
REMOTE=/home/user/timesheet-app

scp "$BUNDLE" "$HOST":/tmp/restore.tgz
ssh "$HOST" bash -s <<EOS
set -e
cd $REMOTE
docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \
  --env-file config.env --env-file .env stop || true

# clear every overlay mount point first: Docker may have left empty
# DIRECTORIES where the module files belong
sudo rm -rf $REMOTE/overlay $REMOTE/gcp/users.caddy
sudo mkdir -p $REMOTE/data $REMOTE/overlay $REMOTE/gcp
sudo tar -xzf /tmp/restore.tgz -C $REMOTE
sudo chown -R \$(id -u):\$(id -g) $REMOTE/data $REMOTE/overlay

# verify BEFORE starting anything
for f in pipeline validate rowconf generic_grid ocr_engine clocks aarvi_form main db; do
  test -f $REMOTE/overlay/app/\$f.py || { echo "MISSING overlay/app/\$f.py"; exit 1; }
done
test -s $REMOTE/gcp/users.caddy || { echo "MISSING gcp/users.caddy"; exit 1; }

docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \
  --env-file config.env --env-file .env up -d
sleep 25 && docker compose ps

# confirm the CONTAINER is serving the overlay, not an empty directory
for f in pipeline rowconf generic_grid ocr_engine clocks validate; do
  printf '%-14s ' \$f
  docker exec timesheet-app sh -c "wc -c < /app/app/\$f.py"
done
EOS
```

Checking byte sizes from inside the container matters: the version string
reported by `/api/health` stays correct even when the code behind it is wrong.

---

## 8. On your own hardware

Often the right answer, and worth considering seriously.

Measured throughput is 8–23 machine-hours for a 3,000-page month — an
overnight job on one ordinary desktop. A 16 GB desktop with a modern processor
runs this comfortably.

What you gain: no monthly bill, and the documents never leave the building,
which is this system's stated privacy position.

What you take on: backups, uptime, and remote access if other offices need it.

For a single team doing the processing, follow `03-SETUP-ON-A-LAPTOP.md` and
stop there — no Caddy, no certificate, no login gate. For several offices,
follow §3 above on a machine on your own network and put it behind whatever
your organisation already uses for remote access.

---

## 9. Verify, whatever you deployed onto

```bash
cd source-code
./.venv/bin/python tools/e2e_prod_test.py --url https://your-site
```

32 checks over HTTPS: anonymous requests refused, the login works, the version
actually running matches your source, a real upload is read correctly against
independent ground truth, per-row confidence is attached, the statuses survive
into the Excel, page locking works, and the audit trail attributes correctly.

It is provider-neutral — it only speaks HTTP. It needs the test fixtures, which
in this repository live under `reference-data/` (and are absent from the public
copy; see its README).

**Do not announce a deployment before it prints `E2E PASSED — 32/32`.**
