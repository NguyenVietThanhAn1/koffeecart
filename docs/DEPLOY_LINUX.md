# Deploying to a Linux server

Step by step, from a fresh Ubuntu server to a running shop with nightly verified backups,
a weekly restore drill and uptime alerts. Plain HTTP on the server's IP (no domain needed).
CI/CD (automatic deploys from GitHub) is the last step and is described in [CI_CD.md](CI_CD.md).

Written for Ubuntu 24.04 LTS with 2 GB RAM, 1-2 vCPU and 20 GB disk (other systemd-based
distributions work with their own Docker install steps). Commands run as a normal user with
sudo (called `deploy` below). The same stack, backup scripts and monitor are exercised on every
CI run, but this guide itself has not yet been followed on a real server: note anything that
differs.

## 1. Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"   # log out and back in for this to apply
docker compose version
```

## 2. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
```

Docker writes its own iptables rules, so a port published by a container **bypasses ufw**.
That is why only Nginx publishes a port (`80`); PostgreSQL publishes nothing, and the optional
Uptime Kuma UI is bound to `127.0.0.1` only.

## 3. Code and configuration

```bash
sudo mkdir -p /opt/koffeecart && sudo chown "$USER": /opt/koffeecart
git clone https://github.com/NguyenVietThanhAn1/koffeecart.git /opt/koffeecart
cd /opt/koffeecart
cp .env.example .env.prod
chmod 600 .env.prod
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # use as SECRET_KEY
nano .env.prod
```

Fill in at least:

```
SECRET_KEY=<the generated value>
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,<server-ip>
CSRF_TRUSTED_ORIGINS=http://<server-ip>
DB_ENGINE=django.db.backends.postgresql
DB_NAME=koffeecart
DB_USER=koffeecart
DB_PASSWORD=<a long random password>
DB_PORT=5432
WEB_IMAGE=<dockerhub-user>/koffeecart
```

Keep `localhost` in `ALLOWED_HOSTS`: the container healthcheck and `monitor.sh` call
`http://localhost/health/`. Leave the `SECURE_*` / `*_COOKIE_SECURE` settings off while the site
is plain HTTP, or logins fail (browsers drop "secure" cookies on HTTP).

## 4. First start

Before CI has pushed an image, build on the server:

```bash
./deploy.sh --build
```

Once CI pushes images, deploy a tested one instead (the tag is shown in the CI run):

```bash
./deploy.sh sha-<commit>
./deploy.sh --rollback     # back to the previous tag if needed
```

`deploy.sh` waits until `web` and `nginx` are healthy and rolls back by itself if they are not.

> Upgrading a server that ran the old stack (PostgreSQL 15)? A PostgreSQL 17 container cannot
> open a version 15 data directory. If the data is not needed:
> `docker compose --env-file .env.prod -f docker-compose.prod.yml down -v` (deletes the volumes),
> then deploy. If it is needed, take a dump with the old stack first and restore it afterwards.

Then add demo products and an admin account:

```bash
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
$COMPOSE exec web python manage.py seed_demo
$COMPOSE exec web python manage.py createsuperuser     # admin: http://<server-ip>/securelogin/
```

Check: `http://<server-ip>/` shows the shop, and

```bash
./monitor.sh               # exit code 0 = all critical checks passed
```

## 5. Backups and restore drill

```bash
sudo deploy/systemd/install.sh            # jobs run as the owner of /opt/koffeecart
systemctl list-timers 'koffeecart-*'
sudo systemctl start koffeecart-backup.service           # one backup right now
sudo systemctl start koffeecart-restore-drill.service    # and prove it restores
tail logs/backup.log
```

- **Nightly 02:30** `backups/backup.sh`: `pg_dump | gzip`, then verified (valid gzip and the
  "dump complete" footer). A failed dump is reported and deleted, never kept as a fake backup.
  Dumps older than `BACKUP_RETENTION_DAYS` (default 7) are deleted.
- **Sunday 03:30** `backups/restore-drill.sh`: restores the newest dump into a throwaway
  database, checks that accounts/products/migrations are there, logs how long it took, drops it.
- **Off-server copy** (recommended: a backup on the same disk dies with the disk): install
  [rclone](https://rclone.org/install/), `rclone config` a remote (Backblaze B2, S3, Google Drive...),
  and set `BACKUP_OFFSITE=<remote>:<bucket-or-folder>` in `.env.prod`.

Restore by hand:

```bash
backups/backup.sh list
backups/backup.sh restore                                  # pick one, confirm with "yes"
backups/backup.sh restore backups/koffeecart_<date>.sql.gz --yes
```

The web container is stopped during the restore, so the site shows 502 for a few seconds.

## 6. Uptime alerts (optional)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml --profile monitoring up -d
# on your own computer:
ssh -L 3001:localhost:3001 deploy@<server-ip>      # then open http://localhost:3001
```

Create the admin user, then add a monitor:

- Type **HTTP(s) - Keyword**, URL `http://nginx/health/`, keyword `"status": "ok"`, interval 60 s
- **Headers**: `{"Host": "localhost"}` (Django only accepts hosts listed in `ALLOWED_HOSTS`)
- **Notifications**: Telegram bot, email (SMTP) or Discord, so a failure reaches your phone

`/health/` checks the database too, so this alerts on "app down" and "database down".

## 7. Rate limiting

Nginx allows 10 POSTs per minute per IP (burst 5) on the login, register and password forms,
and 20 requests per second per IP on the rest of the app. Check it:

```bash
for i in $(seq 1 20); do curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost/accounts/login/; done | sort | uniq -c
```

The first few answers are `403` (no CSRF token: Django refused them), the rest `429` (Nginx
stopped them before Django). Blocked requests are logged in `logs/error.log`.

## 8. Automatic deploys from GitHub

Install a self-hosted runner on this server and configure the repository secrets and
variables as described in [CI_CD.md](CI_CD.md). Set `DEPLOY_DIR=/opt/koffeecart`.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `400 Bad Request` | the host you typed is not in `ALLOWED_HOSTS` | add the IP/name, `./deploy.sh <current tag>` |
| `403 CSRF verification failed` on login | `CSRF_TRUSTED_ORIGINS` missing `http://<ip>`, or `*_COOKIE_SECURE=True` on plain HTTP | fix `.env.prod`, redeploy |
| `502 Bad Gateway` | `web` is not running or not healthy | `docker compose ... logs web`, `./monitor.sh` |
| `./deploy.sh: Permission denied` | executable bit lost | `git pull` (fixed in the repo) or `chmod +x *.sh backups/*.sh` |
| `429 Too Many Requests` | rate limit | wait a minute; see section 7 |
| `database files are incompatible with server` | old PostgreSQL 15 volume | see the note in section 4 |
