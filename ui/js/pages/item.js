// One item: details from roadmap, logs from progress, and the form to log a session.
// Logging a session is the main cross-service flow: the browser calls progress,
// and progress calls roadmap (ownership check, then status sync). If roadmap is
// down, progress answers 503 and nothing is saved; that message is shown here.
import { api } from "../api.js";
import { requireLogin } from "../auth.js";
import { errorText, flash, flashNext, h, label, param, tags, render } from "../ui.js";

requireLogin();
const main = document.querySelector("main");
const id = param("id");
const FELT = ["easy", "fair", "hard", "brutal"];

function history(logs) {
  if (!logs.length) return h("p", { class: "muted" }, "No sessions logged yet.");
  return h("ol", { class: "timeline" }, logs.map((log) => h("li", {},
    h("div", { class: "tl-head" },
      h("span", { class: "tl-date" }, String(log.checked_in_at).slice(0, 10)),
      h("span", { class: "tl-pct" }, `${log.completion_pct}%`),
      log.felt_difficulty && h("span", { class: `pill f-pill-${log.felt_difficulty}` }, log.felt_difficulty),
      log.time_spent_mins ? h("span", { class: "muted" }, `${log.time_spent_mins} min`) : null),
    log.notes && h("p", { class: "tl-notes" }, log.notes))));
}

function logForm(completion) {
  const out = h("output", { id: "pct-out", class: "range-out" }, `${completion}%`);
  const range = h("input", { id: "completion_pct", type: "range", name: "completion_pct", min: 0, max: 100, step: 5,
    value: completion, oninput: (e) => { out.value = `${e.target.value}%`; } });
  const form = h("form", {},
    h("div", { class: "field" }, h("label", { for: "completion_pct" }, "Where are you now? ", out), range),
    h("div", { class: "field" }, h("span", { class: "field-label" }, "How did it feel?"),
      h("div", { class: "segmented segmented-felt" }, FELT.map((f) => h("label", { class: `f-${f}` },
        h("input", { type: "radio", name: "felt_difficulty", value: f }), h("span", {}, f))))),
    h("div", { class: "field" },
      h("label", { for: "time_spent_mins" }, "Time spent ", h("span", { class: "hint" }, "minutes")),
      h("input", { id: "time_spent_mins", type: "number", name: "time_spent_mins", min: 0, max: 1440, step: 5,
        placeholder: "60", class: "input-short" })),
    h("div", { class: "field" }, h("label", { for: "notes" }, "Notes"),
      h("textarea", { id: "notes", name: "notes", rows: 3, maxlength: 2000,
        placeholder: "What did you cover? Anything blocking you?" })),
    h("div", { class: "form-actions" }, h("button", { type: "submit", class: "btn btn-primary" }, "Save log")));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const result = await api.progress.post(`/items/${encodeURIComponent(id)}/logs`, {
        completion_pct: Number(data.completion_pct),
        felt_difficulty: data.felt_difficulty || null,
        time_spent_mins: data.time_spent_mins ? Number(data.time_spent_mins) : 0,
        notes: data.notes || "",
      });
      flashNext(result.status_synced ? "Progress logged."
        : "Progress logged, but the item's status couldn't be updated right now.");
      location.reload();
    } catch (err) {
      flash(errorText(err));   // e.g. 503 roadmap_unavailable: nothing was saved
      button.disabled = false;
    }
  });
  return form;
}

async function load() {
  const { item } = await api.roadmap.get(`/items/${encodeURIComponent(id)}`);
  let logs = null;
  let completion = 0;
  try {
    const result = await api.progress.get(`/items/${encodeURIComponent(id)}/logs`);
    logs = result.logs;
    completion = result.completion;
  } catch {
    logs = null;   // progress down: show the item, hide the log section
  }
  document.title = `${item.title} · cyberroadmap`;

  const deleteButton = h("button", { type: "button", class: "btn btn-danger btn-sm" }, "Delete item");
  deleteButton.addEventListener("click", async () => {
    if (!confirm("Delete this item and all its logs?")) return;
    try {
      const result = await api.roadmap.del(`/items/${encodeURIComponent(id)}`);
      flashNext(result.logs_deleted === null
        ? "Item deleted. Its logs will be ignored until progress is reachable again."
        : "Item deleted.");
      location.href = "progress.html";
    } catch (err) {
      flash(errorText(err));
    }
  });

  render(main, 
    ...[...main.querySelectorAll(".flash-wrap")],
    h("a", { href: "progress.html", class: "back" }, "← Progress"),
    h("div", { class: "page-head" },
      h("div", {},
        h("h1", {}, item.title),
        h("div", { class: "item-sub" },
          h("span", { class: "pill pill-type" }, item.type),
          item.platform && h("span", { class: "item-platform" }, item.platform),
          h("span", { class: `pill d-${item.difficulty}` }, item.difficulty),
          h("span", { class: `pill s-pill-${item.status}` }, label(item.status)),
          tags(item.skill_tags).map((t) => h("span", { class: "mini-tag" }, `#${t}`)))),
      h("div", { class: "head-actions" },
        // The roadmap service only accepts http(s) links, so this can't be a javascript: URL.
        item.url && h("a", { href: item.url, target: "_blank", rel: "noopener noreferrer", class: "btn btn-ghost" }, "Open resource ↗"),
        h("a", { href: `item-edit.html?id=${item.id}`, class: "btn btn-ghost" }, "Edit"))),
    h("div", { class: "progress-block" },
      h("div", { class: "bar bar-lg" }, h("div", { class: "bar-fill", style: { width: `${completion}%` } })),
      h("span", { class: "pct-lg" }, logs === null ? "–" : `${completion}%`)),
    logs === null
      ? h("div", { class: "callout" }, h("span", { class: "callout-icon" }, "!"),
          h("div", {}, "Progress logs are unavailable right now. Try again in a minute."))
      : h("div", { class: "detail-grid" },
          h("section", { class: "card" }, h("h2", {}, "Log a session"), logForm(completion)),
          h("section", { class: "card" }, h("h2", {}, "History"), history(logs))),
    h("div", { class: "danger-zone" }, deleteButton));
}

if (!id) location.replace("progress.html");
load().catch((err) => {
  main.querySelector(".loading")?.remove();
  flash(err.status === 404 ? "Item not found." : errorText(err));
});
