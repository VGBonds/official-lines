# Deployment on Hetzner

The goal: a small server that runs the pipeline every 3 hours and serves the website, for under €10 a month. This guide assumes you have never set up a server.

What you will end up with:

```
Hetzner server (Ubuntu)
├── systemd timer ── every 3 h ──► uv run official-lines run ──► writes ~/official-lines/site/
├── systemd timer ── nightly ───► database backup (14 days kept)
└── Caddy web server ──────────► serves ~/official-lines/site/ over HTTPS
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

1. Sign up at **console.hetzner.cloud** and create a project called `official-lines`.
2. **Add Server**:
   - Location: any EU location (e.g. Falkenstein or Nuremberg).
   - Image: **Ubuntu 24.04**.
   - Type: **CX23** (2 vCPU x86, 4 GB RAM), about €8 a month including IPv4. Plenty for Official Lines. If it shows as unavailable, try another location, or take a **CAX11** (ARM) or **CPX12**; both work unchanged.
   - SSH key: paste the line from step 1.
   - Name: `official-lines`.
   - New Hetzner accounts are sometimes held for verification; a small prepaid top-up usually unlocks them.
3. Create it, and note its **IPv4 address** (e.g. `203.0.113.10`). Below we write it as `SERVER_IP`.

**Forgot the SSH key?** Hetzner then emails a root password instead. Don't use the web console (pasting doesn't work there). In your Mac's Terminal, log in once with that password (`ssh root@SERVER_IP`; nothing is shown while you paste, and you may be asked to set a new one), `exit`, then install your key and check that it logs in without a password:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@SERVER_IP
ssh root@SERVER_IP
```

No password email? Server page → **Rescue** → **Reset root password**.

Optional, recommended: in the server's **Backups** tab, enable Hetzner backups (+20% of the server price) for whole-server snapshots.

## 3. A domain (optional, can wait)

The site works on the bare IP address over plain HTTP. For a real launch you want a domain (e.g. from Cloudflare Registrar, Namecheap or INWX, about €10 a year):

- At your registrar, create an **A record** for your domain (or a subdomain) pointing to `SERVER_IP`.
- Do the same for `www` if you want www.your-domain to work (the setup script redirects it to the bare domain).
- **Check for AAAA records** (IPv6). Registrars, Hetzner included, often create them pointing at their own parking or webhosting server. Most devices prefer IPv6, so visitors then land on that server and see a 404 or nothing, while everything looks fine over IPv4. Set each AAAA record (`@` and `www`) to your server's IPv6 address, shown in the Hetzner console next to the IPv4 (ending in `::1`), or delete them.
- Wait a few minutes. With the domain in place, Caddy gets an HTTPS certificate by itself.
- Test both paths: `curl -sI -4 https://your-domain | head -1` and `curl -sI -6 https://your-domain | head -1` should both print `HTTP/2 200`.

## 4. Set up the server

Copy the deploy scripts to the server, then run the setup as root:

```bash
scp -r deploy root@SERVER_IP:/root/
ssh root@SERVER_IP "bash /root/deploy/setup-server.sh YOUR_DOMAIN_OR_SERVER_IP"
```

The first time, SSH asks whether you trust the server; type `yes`. The script takes 2–3 minutes. It switches SSH to key-only login (no passwords; skipped if no key is installed), installs the firewall, automatic security updates, the Caddy web server and uv, creates a `official-lines` user (the pipeline never runs as root), and switches on the timers.

## 5. Send the code

From the project folder on your laptop:

```bash
deploy/push.sh SERVER_IP
```

Run this again whenever you change code or the source catalog. It never touches the server's database, settings or website.

## 6. Settings on the server

Create a **second** API key in the Anthropic Console (workspace `official-lines`, name `official-lines-server`). Then log in as the app user and create the settings file:

```bash
ssh official-lines@SERVER_IP
cd official-lines
cp .env.example .env
nano .env
```

In nano, fill in `ANTHROPIC_API_KEY=` and `OFFICIAL_LINES_SITE_URL=https://your-domain` (or `http://SERVER_IP`). Save with **Ctrl+O, Enter**, quit with **Ctrl+X**. Then lock the file so only the app user can read it:

```bash
chmod 600 .env
```

## 7. First run and check

Still logged in as `official-lines`:

```bash
uv run official-lines run
```

Open `https://your-domain` (or `http://SERVER_IP`) in a browser. From now on the timer runs every 3 hours by itself.

## Everyday server commands

Log in with `ssh official-lines@SERVER_IP` first.

| Task | Command |
|---|---|
| When does the next run happen? | `systemctl list-timers 'official-lines*'` |
| Log of the latest runs | `journalctl -u official-lines-run -n 100 --no-pager` |
| Follow a run live | `journalctl -u official-lines-run -f` |
| Run the pipeline now | `cd official-lines && uv run official-lines run` |
| AI spend this month | `cd official-lines && uv run official-lines costs` |
| Pause the schedule | from your laptop: `ssh root@SERVER_IP systemctl stop official-lines-run.timer` |
| Resume the schedule | from your laptop: `ssh root@SERVER_IP systemctl start official-lines-run.timer` |

## Updating

- **Code or sources changed:** on your laptop, `deploy/push.sh SERVER_IP`.
- **Deploy files changed** (timers, Caddyfile): copy them again and re-run the setup script (step 4). It is safe to repeat.

## Restoring a backup

Backups are in `~/official-lines/data/backups/` on the server, one per night, kept for 14 days. To restore one:

```bash
ssh official-lines@SERVER_IP
cd official-lines
gunzip -k data/backups/official-lines-2026-11-20.db.gz
mv data/official-lines.db data/official-lines-broken.db
mv data/backups/official-lines-2026-11-20.db data/official-lines.db
```

To keep a copy on your laptop as well:

```bash
scp official-lines@SERVER_IP:official-lines/data/backups/*.gz ~/official-lines-backups/
```

## Monthly cost

| Item | Cost |
|---|---|
| Hetzner CX23 | ~€8 |
| Hetzner backups (optional) | ~€1 |
| Domain | ~€1 (€10–15 a year) |
| Anthropic API | $15–35, capped by `OFFICIAL_LINES_MONTHLY_BUDGET_USD` |
