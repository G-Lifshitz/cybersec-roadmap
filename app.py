import os
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv

load_dotenv()

from db import init_db
import models.roadmap as roadmap_model
import models.progress as progress_model
from services.youtube import RecommendationService

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

PORT = int(os.environ.get("PORT", 5000))

ITEM_TYPES = ["course", "cert", "lab", "book", "project"]
PLATFORMS = ["HTB", "THM", "YouTube", "Coursera", "OffSec", "TCM", "Other"]
DIFFICULTIES = ["beginner", "intermediate", "advanced"]
STATUSES = ["not_started", "in_progress", "completed"]
FELT_DIFFICULTIES = ["easy", "fair", "hard", "brutal"]

# Single Facade instance — all routes call through it
_rec = RecommendationService()


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    items = roadmap_model.get_all()
    skill_summary = roadmap_model.get_skill_summary()
    weak = progress_model.weak_skills()
    total_mins = progress_model.total_time_spent()

    # Attach latest completion % to each item
    enriched = []
    for item in items:
        enriched.append({
            **dict(item),
            "completion": progress_model.latest_completion(item["id"]),
        })

    return render_template(
        "index.html",
        items=enriched,
        skill_summary=skill_summary,
        weak_skills=weak,
        total_hours=round(total_mins / 60, 1),
        statuses=STATUSES,
    )


# ── Roadmap items ──────────────────────────────────────────────────────────

@app.route("/add", methods=["GET", "POST"])
def add_item():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.")
            return redirect(url_for("add_item"))

        roadmap_model.create(
            title=title,
            type_=request.form.get("type", "course"),
            platform=request.form.get("platform", ""),
            url=request.form.get("url", ""),
            skill_tags=request.form.get("skill_tags", ""),
            difficulty=request.form.get("difficulty", "beginner"),
            priority=int(request.form.get("priority", 3)),
        )
        flash(f'"{title}" added to your roadmap.')
        return redirect(url_for("index"))

    return render_template(
        "add.html",
        item_types=ITEM_TYPES,
        platforms=PLATFORMS,
        difficulties=DIFFICULTIES,
    )


@app.route("/item/<int:item_id>")
def item_detail(item_id):
    item = roadmap_model.get_by_id(item_id)
    if not item:
        flash("Item not found.")
        return redirect(url_for("index"))

    logs = progress_model.get_logs_for_item(item_id)
    completion = progress_model.latest_completion(item_id)

    # YouTube recommendations via the RecommendationService facade
    tags = [t.strip() for t in (item["skill_tags"] or "").split(",") if t.strip()]
    videos = _rec.for_item(tags)

    return render_template(
        "item.html",
        item=dict(item),
        logs=logs,
        completion=completion,
        videos=videos,
        felt_difficulties=FELT_DIFFICULTIES,
    )


@app.route("/item/<int:item_id>/log", methods=["POST"])
def log_progress(item_id):
    item = roadmap_model.get_by_id(item_id)
    if not item:
        flash("Item not found.")
        return redirect(url_for("index"))

    pct = max(0, min(100, int(request.form.get("completion_pct", 0))))
    progress_model.add_log(
        item_id=item_id,
        completion_pct=pct,
        felt_difficulty=request.form.get("felt_difficulty"),
        notes=request.form.get("notes", "").strip(),
        time_spent_mins=int(request.form.get("time_spent_mins", 0) or 0),
    )
    flash("Progress logged.")
    return redirect(url_for("item_detail", item_id=item_id))


@app.route("/item/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    roadmap_model.delete(item_id)
    flash("Item removed.")
    return redirect(url_for("index"))


# ── Recommendations ────────────────────────────────────────────────────────

@app.route("/recommendations")
def recommendations():
    weak = progress_model.weak_skills()
    videos, subs = _rec.for_weak_skills(weak)
    return render_template(
        "recommendations.html",
        weak_skills=weak,
        videos=videos,
        subscriptions=subs,
    )


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
