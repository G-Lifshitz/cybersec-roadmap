// Stats: totals, streaks, a month calendar, time per skill, and the last 12 weeks.
// The progress service computes everything (domain/stats.py), including the bar
// coordinates; this page only draws it. Without roadmap, "time per skill" is
// missing (skills: null) and the rest still shows.
import { api, query } from "../api.js";
import { requireLogin } from "../auth.js";
import { duration, errorText, flash, h, param, render } from "../ui.js";

requireLogin();
const main = document.querySelector("main");

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const c of children) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

function stat(value, text, unit = "", accent = "") {
  return h("div", { class: "stat" },
    h("span", { class: `stat-value ${accent}`.trim() }, value, unit && h("small", {}, unit)),
    h("span", { class: "stat-label" }, text));
}

function calendar(r) {
  return h("section", { class: "card" },
    h("div", { class: "card-head" },
      h("a", { href: `stats.html${query({ month: r.prev_month })}`, class: "btn btn-ghost btn-sm", "aria-label": "Previous month" }, "←"),
      h("h2", {}, r.month_label),
      r.next_month
        ? h("a", { href: `stats.html${query({ month: r.next_month })}`, class: "btn btn-ghost btn-sm", "aria-label": "Next month" }, "→")
        : h("span", { class: "btn btn-sm cal-spacer", "aria-hidden": "true" }, "→")),
    h("table", { class: "cal" },
      h("thead", {}, h("tr", {}, r.weekdays.map((d) => h("th", { scope: "col" }, d)))),
      h("tbody", {}, r.month_grid.map((week) => h("tr", {}, week.map((d) => h("td", {
        class: ["cal-day", `shade-${d.shade}`, d.in_month ? "" : "out", d.is_today ? "today" : ""].join(" ").trim(),
        title: d.title,
      }, Number(d.day.slice(8, 10)))))))),
    h("div", { class: "cal-legend", "aria-hidden": "true" },
      h("span", {}, "Less"), [0, 1, 2, 3, 4].map((n) => h("i", { class: `shade-${n}` })), h("span", {}, "More")));
}

function skills(r) {
  let body;
  if (r.skills === null) {
    body = h("p", { class: "muted" }, "Skill tags come from your roadmap, which can't be reached right now.");
  } else if (r.skills.length) {
    body = h("ul", { class: "hbars" }, r.skills.map(([tag, minutes, pct]) => h("li", {},
      h("span", { class: "hbar-label" }, tag),
      h("span", { class: "hbar" }, h("span", { style: { width: `${pct}%` } })),
      h("span", { class: "hbar-value" }, duration(minutes)))));
  } else {
    body = h("p", { class: "muted" }, "Log time on items with skill tags to see where it goes.");
  }
  return h("section", { class: "card" }, h("h2", {}, "Time per skill"), body);
}

function weekly(r) {
  return h("section", { class: "card" }, h("h2", {}, "Last 12 weeks"),
    svg("svg", { class: "weekly", viewBox: "0 0 900 185", role: "img", "aria-label": "Minutes studied per week, last 12 weeks" },
      svg("line", { class: "baseline", x1: 0, y1: 150.5, x2: 900, y2: 150.5 }),
      ...r.weekly.map((b) => svg("g", {},
        svg("title", {}, `Week of ${b.label}: ${duration(b.value)}`),
        svg("rect", { x: b.x, y: b.y, width: b.width, height: b.height, rx: 3 }),
        svg("text", { x: b.center, y: 170, "text-anchor": "middle" }, b.label)))));
}

async function load() {
  const { report: r } = await api.progress.get(`/stats${query({ month: param("month") })}`);
  render(main, 
    ...[...main.querySelectorAll(".flash-wrap")],
    h("div", { class: "page-head" }, h("div", {},
      h("p", { class: "eyebrow" }, "Stats"),
      h("h1", {}, "Your study"),
      h("p", { class: "lede" }, "When you study, how much, and on what. Built from the sessions you log."))),
    h("section", { class: "stats" },
      stat(r.total_hours, "studied in total", "h"),
      stat(r.sessions, `sessions on ${r.days_studied} day${r.days_studied === 1 ? "" : "s"}`),
      stat(r.current_streak, "current streak", "d", "accent-green"),
      stat(r.longest_streak, "longest streak", "d")),
    !r.sessions && h("div", { class: "empty empty-sm" }, "Nothing logged yet. Open an item on your ",
      h("a", { href: "progress.html" }, "Progress"), " page and log a session; it shows up here straight away."),
    h("div", { class: "detail-grid stats-grid" }, calendar(r), skills(r)),
    weekly(r));
}

load().catch((err) => {
  main.querySelector(".loading")?.remove();
  flash(errorText(err));
});
