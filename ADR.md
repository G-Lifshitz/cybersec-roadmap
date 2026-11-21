# Architecture Decision Records

---

## 1. Backend framework: Flask with Jinja2 server-side rendering

Date: 2026-09-26

Status: Decided

Context: The project needs a Python web framework. The two realistic options were Flask (synchronous, minimal, template-based) and FastAPI (async, auto-generates OpenAPI docs, designed for JSON APIs). The app is a personal tool with no concurrency requirements and a simple request/response model.

Decision: Use Flask 3.x with Jinja2 templates served by the same process. No separate frontend build step.

Alternatives considered: FastAPI — rejected because its async model and JSON-API design are overkill for a single-user tool with no concurrent load. It would also require a separate frontend or a heavier templating setup, adding complexity with no payoff at this scale.

Consequences: Jinja2 templates keep the entire stack in one process with zero build tooling, and the synchronous model is fine for SQLite I/O. If the app ever needs real concurrency, adding Gunicorn workers requires no code changes.

---

## 2. Domain separation: roadmap items vs. progress logs

Date: 2026-09-26

Status: Decided

Context: The assignment requires two distinct backend feature domains that are logically separable and could each become a microservice later. The app tracks two related but independent concerns: what a user plans to learn, and what they have actually done.

Decision: Split into two independent modules — `models/roadmap.py` owns the `roadmap_items` table (what to learn: title, type, platform, skill tags, priority, status) and `models/progress.py` owns the `progress_logs` table (what was done: completion %, felt difficulty, time spent, notes). Neither module imports the other.

Alternatives considered: A single `models.py` file with all functions — rejected because it conflates two responsibilities and makes future extraction into separate services harder. A seam between the two domains must be visible now even if the split doesn't happen until Assignment 2.

Consequences: The only coupling is one-way and at the SQL level, from progress into roadmap: `add_log()` issues a cross-table UPDATE to sync the parent item's status, and `weak_skills()` JOINs `roadmap_items` to read skill tags. Everything else is cleanly separated, so a future split would only need to replace those two queries with calls to the roadmap service.

---

## 3. SQLite schema: user-owned rows with cascading foreign keys

Date: 2026-09-30

Status: Decided

Context: Both domains share one SQLite file, and since accounts were added every row has to belong to exactly one user. The relationships (a log belongs to an item, an item belongs to a user) must be enforced without an ORM.

Decision: `roadmap_items.user_id`, `login_events.user_id` and `assessments.user_id` reference `users(id)`, and `progress_logs.item_id` references `roadmap_items(id)`, all with `ON DELETE CASCADE` and `PRAGMA foreign_keys = ON` set once on the singleton connection in `db.py`. Progress rows have no `user_id` of their own: ownership is always reached through the parent item.

Alternatives considered: Also storing `user_id` on `progress_logs` — rejected because two copies of the owner could disagree, and an ownership check on the wrong column would still pass. SQLAlchemy ORM — rejected because it hides the schema behind Python classes; with raw `sqlite3` the whole schema is readable in `init_db()`.

Consequences: Deleting a user or an item removes everything under it in one statement, which is what self-service account deletion relies on. Any progress query that isn't already behind an owner-checked item has to JOIN `roadmap_items` to filter by user, as `weak_skills()` and `total_time_spent()` do.

---

## 4. Testing approach: model layer and pure logic, not routes

Date: 2026-09-30

Status: Decided

Context: The assignment asks for at least 70% coverage on core business logic. The code that can silently go wrong here is the model layer (SQL, ownership checks, status updates, rate limits) and the questionnaire scoring, not the Flask glue that passes form fields through.

Decision: Unit-test every public function in `models/`, `ui/` and `services/assessment.py` against a throwaway SQLite file, including security cases (another user's ids, SQL injection payloads, lockout windows), with a small fake question bank injected in place of the real one. Routes and templates are checked by hand in the browser instead of with unit tests.

Alternatives considered: Route tests with `app.test_client()` for every page — rejected for now because they mostly re-test Flask and Jinja, and each needs a logged-in session, roughly doubling the test code for little extra confidence in the logic. Testing `services/youtube.py` was also left out, because it would mean mocking Google's API rather than testing our own code.

Consequences: 114 tests give 100% line coverage on `models/`, `ui/` and the scoring service (`python -m pytest tests/ --cov=models --cov=ui --cov=services.assessment`). A bug that only lives in a route, such as a wrong redirect, is not caught automatically.

---

## 5. Deliberately not built: automatic progress sync with TryHackMe and Hack The Box

Date: 2026-10-01

Status: Decided

Context: Most users already work through labs and courses on TryHackMe and Hack The Box, so pulling their progress from those platforms automatically was the obvious extra feature. Every roadmap item and progress log is currently entered by hand.

Decision: Don't sync with either platform; users add and update their roadmap items and logs themselves. External APIs stay optional and need no per-user credentials: the YouTube Data API v3 and, since 3 Oct, GitHub's public REST API for linked profiles, read-only.

Alternatives considered: Scraping each user's public profile pages — rejected because it breaks whenever a page layout changes and may break the platforms' terms of service. Asking each user for a platform API token and polling with it — rejected because the app would then store third-party credentials for every user, a secrets-management and breach risk far bigger than the convenience is worth.

Consequences: The app stores no third-party credentials and nothing breaks when those platforms change, which also keeps it within the deployment rule of no required external dependencies. The cost is manual data entry for every item and every study session.

---

## 6. The split: accounts and items in roadmap, only progress logs in progress

Date: 2026-11-19

Status: Decided

Context: Assignment 2 splits the app into exactly two services along the ADR 2 seam, each with its own database. Accounts, login history, rate limits and assessments belonged to neither domain in ADR 2, and only two cross-domain queries existed: `add_log()` updating the item's status and `weak_skills()` joining items for their tags.

Decision: The roadmap service owns accounts, rate limits, assessments, the timeline and roadmap items, and issues a signed bearer token at login; the progress service owns only progress logs. Each former join is now an HTTP call with a 2-second timeout that forwards the user's own token: logging progress asks roadmap whether the item exists and is the caller's (refusing with 503 if roadmap is down), then syncs the item's status, while the summary and stats fetch item tags and leave out the tag-based parts when roadmap is down.

Alternatives considered: A third service for accounts, rejected because the assignment allows exactly two containers. Calling progress-to-roadmap with a service-to-service secret instead of the user's token, rejected because it adds a secret and lets progress act on any user's items; forwarding the token keeps roadmap's ownership checks in force.

Consequences: Only three kinds of call cross the seam (item check and status sync, tags for reports, log deletion when an item or account is deleted), which suggests the seam is in the right place. Progress verifies tokens with the shared TOKEN_SECRET without asking roadmap, so a revoked token can still read progress data until it expires (12 hours); writes are safe because every write goes through roadmap first.

---

## 7. Data and migrations: own database per service, numbered SQL files run at startup

Date: 2026-11-19

Status: Decided

Context: Assignment 1 created its SQLite schema on every boot and patched old databases with `ALTER TABLE` checks. On SQL Server each service has its own database, so the foreign key from `progress_logs` to `roadmap_items` cannot exist, and ownership can no longer come from a join (ADR 3). There was no production data to move: Assignment 1 ran only locally and had no seed data.

Decision: Each service applies its own forward-only migrations (`migrations/NNN_name.sql`) at startup, before serving: each file runs once, in one transaction, recorded in `schema_migrations`, with `sp_getapplock` so two starts can't apply it twice. `progress_logs` gets its own `user_id`, and `item_id` becomes a plain ID whose integrity is enforced in code: progress checks the item with roadmap before inserting, and roadmap asks progress to delete the logs when an item or account is deleted.

Alternatives considered: Alembic, rejected because the models use plain SQL with no ORM, so it would add SQLAlchemy only to run migrations. Running migrations as a separate pipeline step, rejected because the GitHub runner would need the database password and a firewall opening to Azure SQL, while the app already has both.

Consequences: Both databases start empty and evolve only through migration files that are never edited once applied; a fix is a new file. If progress is down when an item is deleted, the item's logs stay behind as orphans, which progress ignores because every report starts from the items roadmap returns.

---

## 9. Pipeline and testing: one workflow, CD gated on CI, cross-seam tested against a stub

Date: 2026-11-20

Status: Decided

Context: Every push must be tested and every merge to main deployed with no manual steps, and only when CI passed on that same commit. Each service's tests need a real SQL Server, but CI must never touch Azure SQL. The cross-seam flow (progress asking roadmap about an item) needs an integration test.

Decision: One GitHub Actions workflow (`pipeline.yml`) runs validate (system.yaml against the schema, both OpenAPI documents), lint plus tests with a 70% coverage gate per service against a SQL Server service container set up by the same `db/init.sql` as compose, and both Docker builds; the CD jobs (push SHA-tagged images to GHCR, deploy, upload the UI, health check) `need` those jobs and run only on pushes to main. The cross-seam integration test runs progress's real API and model logic against a stub of roadmap (`tests/test_api.py`), covering success, roadmap down, status sync failing, and degraded summary and stats.

Alternatives considered: A separate CD workflow triggered by `workflow_run` after CI, rejected because it adds a second trigger whose commit has to be matched by hand, while `needs:` guarantees the same commit. Running the integration test against the full compose stack in CI, rejected for now because it doubles CI time and needs both images built and SQL Server started before a single assertion; the stub is the option §5 allows, and the compose stack is exercised by hand with `docker compose stop roadmap`.

Consequences: A red test, a coverage drop below 70%, an invalid system.yaml or a broken image blocks the deploy. What is deliberately not tested automatically: the static UI's JavaScript (checked by hand), the real network between the two containers, and Azure-only behaviour (cold starts, the database resuming), which the post-deploy health check covers by waiting up to 6 minutes for both /health endpoints to report this commit's SHA.
