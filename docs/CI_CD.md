# CI/CD

Workflow file: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). It runs on every push and
pull request to `main`. Only pushes to `main` build a pushable image and deploy.

```
lint ──► test ──┐
                ├──► build (scan + smoke test + push) ──► deploy   (main only)
security ───────┘
```

| Job | What it does | Fails the run when |
| --- | --- | --- |
| `lint` | `ruff check .`, `manage.py check --deploy --fail-level WARNING` (with all HTTPS settings on), `makemigrations --check` | lint error, insecure/incoherent settings, model change without a migration |
| `test` | `pytest` against a `postgres:17` service container, coverage report | a test fails, coverage below 90% |
| `security` | `pip-audit` on `requirements.txt`, Trivy source scan (vulnerabilities, secrets, misconfiguration) | a known vulnerable dependency, any CRITICAL finding |
| `build` | builds the image **once** (GitHub Actions layer cache), Trivy image scan, starts the real prod stack with that image, checks `/health/`, static files and the home page, then pushes tags `sha-<commit>` and `latest` | CRITICAL vulnerability, stack not healthy, page checks fail |
| `deploy` | on the VM: checkout of the commit, `./deploy.sh sha-<commit>` (pull, replace containers, wait for `/health/`, roll back on failure) | new version never becomes healthy (the job also rolls back) |

Design choices worth knowing:

- **One build.** Scan, smoke test and push all use the same image, so what is deployed is exactly what was tested.
- **No `sleep`.** The smoke test uses `docker compose up --wait`, which blocks until every healthcheck passes.
- **Actions are pinned to a commit SHA** (the version is in the comment next to it). Dependabot updates them.
- **Tests run on PostgreSQL**, the production database, so row locks (`select_for_update`) and migrations are really exercised. SQLite would silently ignore the locks.

## What you must set up on GitHub (once)

1. **Repository secrets** (Settings → Secrets and variables → Actions → Secrets)
   - `DOCKERHUB_USERNAME`: Docker Hub user; the image is `<user>/koffeecart`.
   - `DOCKERHUB_TOKEN`: a Docker Hub access token (not your password) with read/write permission.
2. **Repository variable** `DEPLOY_DIR`: absolute path of the git clone on the VM, for example `/home/vagrant/projects/koffeecart`. That directory must contain `.env.prod`.
3. **Environment** `production` (Settings → Environments). Optionally add *required reviewers* so a person approves each deploy.
4. **Self-hosted runner on the VM** (Settings → Actions → Runners → New self-hosted runner). Give it the label `koffeecart`. The runner user must be able to run `docker`, and the image repository must be readable from the VM (`docker login` once on the VM if the Docker Hub repository is private).
5. (Recommended) **Branch protection** on `main`: require the `lint`, `test`, `security` and `build` checks.

## Deploying and rolling back by hand

```bash
cd "$DEPLOY_DIR"
./deploy.sh sha-<full-commit-sha>    # deploy a specific image
./deploy.sh --rollback               # go back to the previously deployed tag
./deploy.sh --build                  # build on the VM (no registry needed)
```

`deploy.sh` remembers the current and previous tag in `.deploy_current` and `.deploy_previous`.
Rollback changes the image only. Database migrations are **not** reverted, so restore from
`backups/backup.sh` if a migration itself was the problem.

## Turning on HTTPS hardening

The defaults keep plain HTTP working (needed for the VM). Once a TLS certificate is in front of
the site (for example Nginx or a load balancer that sets `X-Forwarded-Proto`), set in `.env.prod`:

```
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
CSRF_TRUSTED_ORIGINS=https://your-domain
```

`/health/` is exempt from the HTTPS redirect, so the container healthcheck keeps working.
Add `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` only if you understand that HSTS
preload is very hard to undo. The CI check turns everything on only to prove the settings are coherent.

## Run the same checks locally

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
SECRET_KEY=dev python manage.py makemigrations --check --dry-run
pytest --cov                      # SQLite; the concurrency tests are skipped here
pip-audit -r requirements.txt
```

To run the tests on PostgreSQL like CI does, start a database and export `DB_ENGINE`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (see `.env.example`) before running `pytest`.
