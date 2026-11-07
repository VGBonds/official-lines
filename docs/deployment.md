# Deployment on Hetzner

The goal: a small server that runs the pipeline every 3 hours and serves the website, for about €5 a month. This guide assumes you have never set up a server.

What you will end up with:

```
Hetzner server (Ubuntu)
├── systemd timer ── every 3 h ──► uv run parallax run ──► writes ~/parallax/site/
├── systemd timer ── nightly ───► database backup (14 days kept)
└── Caddy web server ──────────► serves ~/parallax/site/ over HTTPS
```

## 1. An SSH key (once, on your laptop)

An SSH key lets you log in to the server without a password. Check whether you have one:

```bash
ls ~/.ssh/id_ed25519.pub
```

If it says "No such file", create one (press Enter at every question):

```bash
ssh-keygen -t ed25519
```

Show the public half, which you'll paste into Hetzner:

```bash
cat ~/.ssh/id_ed25519.pub
```

## 2. Create the server

1. Sign up at **console.hetzner.cloud** and create a project called `parallax`.
2. **Add Server**:
   - Location: any EU location (e.g. Falkenstein or Nuremberg).
   - Image: **Ubuntu 24.04**.
   - Type: **CX22** (2 vCPU, 4 GB RAM), about €4–5 a month. Plenty for Parallax.
   - SSH key: paste the line from step 1.
   - Name: `parallax`.
3. Create it, and note its **IPv4 address** (e.g. `203.0.113.10`). Below we write it as `SERVER_IP`.

Optional, recommended: in the server's **Backups** tab, enable Hetzner backups (+20% of the server price) for whole-server snapshots.

## 3. A domain (optional, can wait)

The site works on the bare IP address over plain HTTP. For a real launch you want a domain (e.g. from Cloudflare Registrar, Namecheap or INWX, about €10 a year):

- At your registrar, create an **A record** for your domain (or a subdomain) pointing to `SERVER_IP`.
- Wait a few minutes. With the domain in place, Caddy gets an HTTPS certificate by itself.

## 4. Set up the server

Copy the deploy scripts to the server, then run the setup as root:

```bash
scp -r deploy root@SERVER_IP:/root/
ssh root@SERVER_IP "bash /root/deploy/setup-server.sh YOUR_DOMAIN_OR_SERVER_IP"
```

The first time, SSH asks whether you trust the server; type `yes`. The script takes 2–3 minutes. It installs the firewall, automatic security updates, the Caddy web server and uv, creates a `parallax` user (the pipeline never runs as root), and switches on the timers.

## 5. Send the code

From the project folder on your laptop:

```bash
deploy/push.sh SERVER_IP
```

Run this again whenever you change code or the source catalog. It never touches the server's database, settings or website.

## 6. Settings on the server

Create a **second** API key in the Anthropic Console (workspace `parallax`, name `parallax-server`). Then log in as the app user and create the settings file:

```bash
ssh parallax@SERVER_IP
cd parallax
cp .env.example .env
nano .env
```

In nano, fill in `ANTHROPIC_API_KEY=` and `PARALLAX_SITE_URL=https://your-domain` (or `http://SERVER_IP`). Save with **Ctrl+O, Enter**, quit with **Ctrl+X**. Then lock the file so only the app user can read it:

```bash
chmod 600 .env
```

## 7. First run and check

Still logged in as `parallax`:

```bash
uv run parallax run
```

Open `https://your-domain` (or `http://SERVER_IP`) in a browser. From now on the timer runs every 3 hours by itself.

## Everyday server commands

Log in with `ssh parallax@SERVER_IP` first.

| Task | Command |
|---|---|
| When does the next run happen? | `systemctl list-timers 'parallax*'` |
| Log of the latest runs | `journalctl -u parallax-run -n 100 --no-pager` |
| Follow a run live | `journalctl -u parallax-run -f` |
| Run the pipeline now | `cd parallax && uv run parallax run` |
| AI spend this month | `cd parallax && uv run parallax costs` |
| Pause the schedule | from your laptop: `ssh root@SERVER_IP systemctl stop parallax-run.timer` |
| Resume the schedule | from your laptop: `ssh root@SERVER_IP systemctl start parallax-run.timer` |

## Updating

- **Code or sources changed:** on your laptop, `deploy/push.sh SERVER_IP`.
- **Deploy files changed** (timers, Caddyfile): copy them again and re-run the setup script (step 4). It is safe to repeat.

## Restoring a backup

Backups are in `~/parallax/data/backups/` on the server, one per night, kept for 14 days. To restore one:

```bash
ssh parallax@SERVER_IP
cd parallax
gunzip -k data/backups/parallax-2026-11-20.db.gz
mv data/parallax.db data/parallax-broken.db
mv data/backups/parallax-2026-11-20.db data/parallax.db
```

To keep a copy on your laptop as well:

```bash
scp parallax@SERVER_IP:parallax/data/backups/*.gz ~/parallax-backups/
```

## Monthly cost

| Item | Cost |
|---|---|
| Hetzner CX22 | ~€4–5 |
| Hetzner backups (optional) | ~€1 |
| Domain | ~€1 (€10–15 a year) |
| Anthropic API | $15–35, capped by `PARALLAX_MONTHLY_BUDGET_USD` |
