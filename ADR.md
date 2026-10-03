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
