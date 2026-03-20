# Deploying OpenCure Labs Dashboard

Deploy the public dashboard to a DigitalOcean droplet at `opencurelabs.ai`.

---

## Architecture

```
Users → https://opencurelabs.ai → Caddy (auto TLS) → localhost:8787 (FastAPI)
                                                            ↓
                                                     PostgreSQL (local)

Your machine ──(sync-db.sh)──→ Droplet PostgreSQL
```

---

## Step 1: Create Droplet

1. Go to [DigitalOcean](https://cloud.digitalocean.com/droplets/new)
2. **Image:** Ubuntu 24.04 LTS
3. **Plan:** Basic, $6/mo (1 vCPU, 1 GB) or $12/mo (1 vCPU, 2 GB)
4. **Region:** Closest to your users (NYC, SFO, LON)
5. **Auth:** SSH key (add your key if not already added)
6. **Hostname:** `opencurelabs`
7. Click **Create Droplet**, note the IP address

## Step 2: Point DNS

In **Namecheap** (or wherever opencurelabs.ai is registered):

1. Go to Domain List → opencurelabs.ai → Advanced DNS
2. Add/edit these records:

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A | @ | `<DROPLET_IP>` | Automatic |
| A | www | `<DROPLET_IP>` | Automatic |

Wait ~5 minutes for propagation. Verify: `dig opencurelabs.ai`

## Step 3: Run Setup Script

```bash
ssh root@<DROPLET_IP>
curl -sL https://raw.githubusercontent.com/OpenCureLabs/OpenCureLabs/main/deploy/setup-droplet.sh | bash
```

Or clone first:
```bash
ssh root@<DROPLET_IP>
git clone https://github.com/OpenCureLabs/OpenCureLabs.git /opt/opencurelabs
bash /opt/opencurelabs/deploy/setup-droplet.sh
```

This installs Python, PostgreSQL, Caddy (auto-TLS), creates a systemd service, and configures the firewall.

## Step 4: Change the Database Password

The setup script uses a placeholder password. Change it immediately:

```bash
# On the droplet:
su - postgres -c "psql -c \"ALTER USER opencure WITH PASSWORD 'your_secure_password';\""

# Update the systemd service:
sed -i 's/changeme_in_production/your_secure_password/' /etc/systemd/system/opencurelabs-dashboard.service
systemctl daemon-reload
systemctl restart opencurelabs-dashboard
```

## Step 5: Sync Your Data

From your local machine (WSL):

```bash
export DROPLET_IP=<your_droplet_ip>
bash deploy/sync-db.sh
```

This pushes agent_runs, experiment_results, critique_log, etc. to the droplet.

---

## Maintenance

### Update code
```bash
ssh root@<DROPLET_IP> 'bash /opt/opencurelabs/deploy/update.sh'
```

### Check status
```bash
ssh root@<DROPLET_IP> 'systemctl status opencurelabs-dashboard'
ssh root@<DROPLET_IP> 'curl -s localhost:8787/health'
```

### View logs
```bash
ssh root@<DROPLET_IP> 'journalctl -u opencurelabs-dashboard -f'
```

### Re-sync data (after running pipelines locally)
```bash
DROPLET_IP=<ip> bash deploy/sync-db.sh
```

---

## Security Notes

- **Dashboard is read-only** — no mutations via the web interface
- **Rate limited** — 30 req/min on pages, 10 req/min on exports
- **TLS automatic** — Caddy handles Let's Encrypt certificates
- **Firewall** — only ports 22, 80, 443 are open
- **No API keys exposed** — dashboard only reads from PostgreSQL
- **systemd hardening** — `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`

---

## Cost

| Component | Monthly Cost |
|-----------|-------------|
| DigitalOcean droplet (1 vCPU, 1 GB) | $6 |
| Domain (opencurelabs.ai) | ~$12/year |
| TLS certificate (Let's Encrypt via Caddy) | Free |
| **Total** | **~$7/mo** |
