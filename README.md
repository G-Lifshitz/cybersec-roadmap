# Cybersecurity Career Roadmap Tracker (cyberroadmap)

Plan and track a career in cybersecurity: keep a roadmap of the courses, certs, labs, books and projects you want to do, log your study sessions on them, and see where your time goes.

**Live:** https://glifshitzieu2024ui.z1.web.core.windows.net

Assignment 2 splits the Assignment 1 monolith into two services along the seam in ADR 2, each with its own SQL Server database, plus a static UI. Everything runs locally with one command and deploys to Azure on every merge to `main`.

```
browser ──► ui/ (static HTML/JS: nginx locally, Azure Storage static website)
   │  Bearer token, CORS limited to the UI's origin
   ├──► roadmap  (accounts, roadmap items, timeline, assessment) ──► roadmap DB
   │       ▲  │ DELETE item/account logs
   │       │  ▼
   └──► progress (progress logs, summary, stats) ───────────────► progress DB
           GET /items/{id}, PATCH status, GET /items (2 s timeout)
```

| Folder | What it is |
|---|---|
| `services/roadmap/` | Flask API: accounts and bearer tokens, roadmap items, career timeline, assessment. Own `Dockerfile`, `requirements.txt`, `migrations/`, `openapi.yaml`, tests. |
| `services/progress/` | Flask API: progress logs, study summary, stats. Same layout. |
| `ui/` | The static UI (plain HTML, CSS and ES modules, no build step). `config.js` holds the two service URLs. |
| `db/init.sql` | Local SQL Server setup: one database and one login per service, plus test databases. |
| `infra/azure-setup.sh` | The one-time Azure setup (every command, in order). |
| `.github/workflows/pipeline.yml` | CI on every push and PR, CD on `main`. |
| `system.yaml` | Every service, its environment variables, its calls across the seam and its Azure names (validated against `system.schema.json`). |
| `ADR.md`, `AI_USAGE.md` | Decisions (1-5 from Assignment 1, 6-10 for this one) and AI use. |

## Run everything locally

Needs Docker Desktop (on Apple Silicon, turn on *Settings → General → Use Rosetta for x86_64/amd64 emulation*: SQL Server has no arm64 image).

```bash
git clone https://github.com/G-Lifshitz/cybersec-roadmap.git
cd cybersec-roadmap
docker compose up --build
```

| URL | |
|---|---|
| http://localhost:8080 | the UI (register an account to start) |
| http://localhost:8001/health | roadmap service |
| http://localhost:8002/health | progress service |

What happens: `mssql` starts SQL Server; `db-init` runs `db/init.sql` once and exits (idempotent, so every `up` is safe); `roadmap` and `progress` each apply their pending migrations (`migration applied: 001_init.sql`) and start gunicorn; `ui` is a stock `nginx:alpine` serving `ui/`. The passwords in `docker-compose.yml` are local-only defaults; override them in a `.env` file (see `.env.example`).

`docker compose down` stops everything and keeps the data; `docker compose down -v` also deletes the database volume.

To see what happens when the other service is down: `docker compose stop roadmap`, then log a session in the UI (it is refused with a clear message and nothing is saved), then `docker compose start roadmap`.

## Run a single service

With compose's SQL Server running (`docker compose up -d mssql db-init`):

```bash
cd services/roadmap            # or services/progress
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL="mssql+pymssql://roadmap_svc:Local_Roadmap_Only_2026@localhost:1433/roadmap_db"
export TOKEN_SECRET="local-only-token-secret-0123456789abcdef"     # same value in both services
export PROGRESS_URL="http://localhost:8002"                         # progress uses ROADMAP_URL instead
python migrate.py
flask --app "app:create_app()" run --port 8001
```

Or only one service inside compose: `docker compose up --build mssql db-init roadmap`. Every variable a service reads, with its default, is listed in `system.yaml`.

## Tests and coverage

Each service has its own suite. Unit tests need nothing; the model tests (marked `db`) need a SQL Server and are skipped without `TEST_DATABASE_URL`.

```bash
cd services/roadmap
pip install -r requirements-dev.txt
ruff check .
pytest                                    # unit tests only, db tests skipped

# everything, against compose's SQL Server (test database, not the app's):
TEST_DATABASE_URL="mssql+pymssql://roadmap_svc:Local_Roadmap_Only_2026@localhost:1433/roadmap_test" \
  pytest --cov=. --cov-report=term-missing
```

For `services/progress` use `progress_svc`, `Local_Progress_Only_2026` and `progress_test`. CI runs exactly this against a fresh SQL Server container and fails below 70% coverage per service. The cross-seam flow (progress → roadmap) is tested in `services/progress/tests/test_api.py` against a stub of roadmap, including roadmap being down (ADR 9).

## Deployment

Every push and pull request runs CI; every push to `main` (a merged pull request) also deploys. `pipeline.yml`:

1. **validate**: `system.yaml` against `system.schema.json`, both `openapi.yaml` files against the OpenAPI spec.
2. **test** (per service): ruff, then pytest against a SQL Server service container, `--cov-fail-under=70`.
3. **build** (per service): `docker build`.
4. **publish** (main only, after 1-3 pass): push `ghcr.io/g-lifshitz/cybersec-roadmap-<service>:<commit SHA>`.
5. **deploy** (main only): sign in to Azure with OIDC as the managed identity `glifshitz-ieu2024-github` (no Azure password stored anywhere); store each service's `DATABASE_URL` and `TOKEN_SECRET` as Container Apps secrets; deploy the SHA-tagged image with 0-1 replicas and its environment variables; write `ui/config.js` with the two service URLs and upload `ui/` to the storage account's `$web` container; then fail the run unless both `/health` endpoints answer 200 with this commit's SHA within 6 minutes.

Azure resources (all in `rg-glifshitz-ieu2024`, region `germanywestcentral`):

| Resource | Name |
|---|---|
| Storage account (static website, the UI) | `glifshitzieu2024ui` |
| Container Apps environment | `glifshitz-ieu2024-env` |
| Container Apps | `glifshitz-ieu2024-roadmap`, `glifshitz-ieu2024-progress` |
| SQL server, serverless databases (free offer) | `glifshitz-ieu2024-sql`: `glifshitz-ieu2024-roadmap-db`, `glifshitz-ieu2024-progress-db` |
| Managed identity for the pipeline | `glifshitz-ieu2024-github` |

Everything scales to zero: the apps have 0 minimum replicas and the databases pause after 60 idle minutes. The first request after a long idle can take about a minute; the UI shows "starting up" and retries (ADR 8).

Subscription note: the IE-account Azure for Students subscription had expired and could not be renewed, so this runs in an Azure for Students subscription on the author's personal Microsoft account. The resource names follow the IE username as required.

### Reproduce the initial Azure setup

Done once, by hand; after that only the pipeline changes Azure. Every command is in `infra/azure-setup.sh` (safe to re-run: existing resources are kept). In Azure Cloud Shell (Bash):

```bash
gh auth login                                        # for the GitHub secrets in step 7
gh repo clone G-Lifshitz/cybersec-roadmap && cd cybersec-roadmap
az policy assignment list --query "[?contains(displayName,'Allowed resource deployment regions')].parameters.listOfAllowedLocations.value | [0]" -o tsv
export LOCATION=germanywestcentral                   # one of the regions listed above
read -rs SQL_ADMIN_PASSWORD; export SQL_ADMIN_PASSWORD
bash infra/azure-setup.sh
```

What the script does, in order: (1) shows the subscription and allowed regions; (2) registers the providers and creates the resource group; (3) creates the storage account and enables the static website; (4) creates the SQL server (firewall: Azure services only) and the two serverless databases on the free offer, then opens the firewall to the current IP, creates one contained user per database (`db_ddladmin`, `db_datareader`, `db_datawriter`, own database only) and closes the firewall again; (5) creates the Container Apps environment (no Log Analytics workspace) and both apps with a placeholder image; (6) creates the managed identity, gives it Contributor on the resource group only, and adds federated credentials trusting runs on `main` of this repository; (7) stores `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ROADMAP_DB_PASSWORD`, `PROGRESS_DB_PASSWORD` and `TOKEN_SECRET` as GitHub Actions secrets (generated, never printed) and the resource names as variables; (9) gives the professors Reader on the resource group. After the first deploy, the GHCR packages must be public so Container Apps can pull them.

### Inspect the Azure databases

Used for the migration evidence. The firewall is opened only for the session:

```bash
RG=rg-glifshitz-ieu2024; SRV=glifshitz-ieu2024-sql
MYIP=$(curl -s https://api.ipify.org)
az sql server firewall-rule create -g $RG -s $SRV -n evidence-ip --start-ip-address $MYIP --end-ip-address $MYIP
sqlcmd -S tcp:$SRV.database.windows.net,1433 -d glifshitz-ieu2024-roadmap-db -U sqladmin -l 90 \
  -Q "SELECT version, applied_at FROM schema_migrations; SELECT * FROM roadmap_items;"
az sql server firewall-rule delete -g $RG -s $SRV -n evidence-ip
```

Logs: `az containerapp logs show -n glifshitz-ieu2024-roadmap -g rg-glifshitz-ieu2024 --follow` (add `--type system` for start-up and probe events). Each request is one line: method, path, status, duration.

## Migrations

Each service owns `migrations/NNN_name.sql`, applied in order at container start by `migrate.py` before gunicorn starts: each file once, in one transaction, recorded in `schema_migrations` (ADR 7). Applied files are never edited; a change is a new file. `roadmap/migrations/002_items_updated_at.sql` changes a table that already holds data: add the column as NULL, backfill it from `created_at`, then make it NOT NULL.

## Security

- Passwords are salted scrypt hashes. Login gives the same answer for a wrong user or a wrong password, and is rate-limited per account+IP and per IP (429 with `Retry-After`); the counters are in the database, so scaling to zero doesn't reset them.
- Login returns a signed bearer token (12 h). Changing the password invalidates every older token. Every query on user data filters by the token's user, so other users' ids behave as "not found".
- Each service connects with its own database login that cannot see the other database. No credential is in the repository, the images or the workflow: local defaults are for the throwaway compose SQL Server only; Azure's are generated and stored as GitHub and Container Apps secrets.
- CORS allows only the UI's origin. The UI builds the page with `textContent` only (never `innerHTML` with API data) and a Content-Security-Policy allows only its own scripts and calls to the two services.
- All SQL is parameterised; the one dynamic `UPDATE` uses column names from a fixed whitelist.

## Development process

Work happens on branches and reaches `main` only through pull requests, so CI runs before CD. Decisions are in [ADR.md](ADR.md); AI assistance is disclosed in [AI_USAGE.md](AI_USAGE.md).
