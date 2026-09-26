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
