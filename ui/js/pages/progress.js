// Progress: the list of roadmap items with filters, counts and how far along each is.
// Data from both services: items and counts from roadmap, completion and time
// from progress. If progress is down the list still shows, without percentages.
import { api, query } from "../api.js";
import { requireLogin } from "../auth.js";
import { errorText, flash, h, label, param, tags, render } from "../ui.js";

requireLogin();
const main = document.querySelector("main");

const filters = {
  search: param("search") || "", status: param("status") || "", type: param("type") || "", skill: param("skill") || "",
};
const filtering = Object.values(filters).some(Boolean);

function select(name, anyLabel, values, current) {
  return h("select", { name, onchange: (e) => e.target.form.requestSubmit() },
    h("option", { value: "" }, anyLabel),
    values.map((v) => h("option", { value: v, selected: v === current }, label(v))));
}

function stat(value, text, accent = "", unit = "") {
  return h("div", { class: "stat" },
    h("span", { class: `stat-value ${accent}`.trim() }, value, unit && h("small", {}, unit)),
    h("span", { class: "stat-label" }, text));
}

function itemRow(item, completion) {
  const pct = completion ?? null;
  return h("a", { href: `item.html?id=${item.id}`, class: `item-row s-${item.status}` },
    h("div", { class: "item-main" },
      h("div", { class: "item-title" }, item.title),
      h("div", { class: "item-sub" },
        h("span", { class: "pill pill-type" }, item.type),
        item.platform && h("span", { class: "item-platform" }, item.platform),
        h("span", { class: `pill d-${item.difficulty}` }, item.difficulty),
        tags(item.skill_tags).map((t) => h("span", { class: "mini-tag" }, `#${t}`)))),
    h("div", { class: "item-side" },
      h("div", { class: "prio", title: `Priority ${item.priority}` },
        [0, 1, 2, 3, 4].map((n) => h("i", { class: n < item.priority ? "on" : null }))),
      h("div", { class: "bar" }, h("div", { class: "bar-fill", style: { width: `${pct ?? 0}%` } })),
      h("span", { class: "pct" }, pct === null ? "–" : `${pct}%`)));
}

async function load() {
  const [items, dashboard, options, summary] = await Promise.all([
    api.roadmap.get(`/items${query(filters)}`),
    api.roadmap.get("/dashboard"),
    api.roadmap.get("/options"),
    // Progress being down shouldn't hide the roadmap: show it without numbers.
    api.progress.get("/summary").catch(() => null),
  ]);
  const completion = summary?.completion || {};
  const { counts, skills } = dashboard;

  const form = h("form", { method: "GET", action: "progress.html", class: "filter-bar" },
    h("input", { type: "search", name: "search", value: filters.search, placeholder: "Search title or platform",
      class: "filter-search" }),
    select("status", "Any status", options.statuses, filters.status),
    select("type", "Any type", options.types, filters.type),
    select("skill", "Any tag", dashboard.tags, filters.skill),
    h("button", { type: "submit", class: "btn btn-ghost btn-sm" }, "Filter"),
    filtering && h("a", { href: "progress.html", class: "clear-link" }, "Clear"));

  let list;
  if (items.items.length) {
    list = h("div", { class: "item-list" }, items.items.map((it) => itemRow(it, summary ? (completion[it.id] ?? 0) : null)));
  } else if (filtering) {
    list = h("div", { class: "empty" }, "No items match these filters. ", h("a", { href: "progress.html" }, "Clear filters"));
  } else {
    list = h("div", { class: "empty" },
      h("p", { class: "empty-title" }, "Your roadmap is empty"),
      h("p", { class: "muted" }, "Add the first course, cert or lab you want to work on."),
      h("a", { href: "item-edit.html", class: "btn btn-primary" }, "+ Add your first item"));
  }

  render(main, 
    ...[...main.querySelectorAll(".flash-wrap")],
    h("div", { class: "page-head" }, h("div", {},
      h("p", { class: "eyebrow" }, "Progress"),
      h("h1", {}, "Your items"),
      h("p", { class: "lede" }, "Everything you're planning to learn, and how far along you are."))),
    h("section", { class: "stats" },
      stat(counts.total, "items"),
      stat(counts.in_progress, "in progress", "accent-blue"),
      stat(counts.completed, "completed", "accent-green"),
      stat(summary ? Math.round((summary.total_minutes / 60) * 10) / 10 : "–", "logged", "", summary ? "h" : "")),
    summary === null && h("div", { class: "callout" }, h("span", { class: "callout-icon" }, "!"),
      h("div", {}, "Progress data is unavailable right now, so percentages and time are hidden. Your roadmap is fine.")),
    summary?.weak_skills?.length > 0 && h("div", { class: "callout" }, h("span", { class: "callout-icon" }, "!"),
      h("div", {}, "You're finding ", h("strong", {}, summary.weak_skills.join(", ")), " hard. Consider an easier resource first.")),
    Object.keys(skills).length > 0 && h("section", { class: "tag-cloud" },
      Object.entries(skills).map(([tag, c]) => h("a", {
        href: `progress.html${query({ skill: tag })}`, class: `tag ${filters.skill === tag ? "active" : ""}`.trim(),
      }, tag, " ", h("span", { class: "tag-count" }, `${c.completed}/${c.completed + c.in_progress + c.not_started}`)))),
    form,
    list,
  );
}

load().catch((err) => {
  main.querySelector(".loading")?.remove();
  flash(errorText(err));
});
