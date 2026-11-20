// Add an item (no ?id=) or edit one (?id=N). Same form both ways, as in Assignment 1.
import { api } from "../api.js";
import { requireLogin } from "../auth.js";
import { errorText, flash, flashNext, h, param, render } from "../ui.js";

requireLogin();
const main = document.querySelector("main");
const id = param("id");

function segmented(name, values, current, extraClass = "", classFor = () => null) {
  return h("div", { class: `segmented ${extraClass}`.trim() },
    values.map((v) => h("label", { class: classFor(v) },
      h("input", { type: "radio", name, value: v, checked: String(v) === String(current) }),
      h("span", {}, v))));
}

async function load() {
  const [options, existing] = await Promise.all([
    api.roadmap.get("/options"),
    id ? api.roadmap.get(`/items/${encodeURIComponent(id)}`).then((r) => r.item) : Promise.resolve({}),
  ]);
  const item = existing || {};
  document.title = `${id ? "Edit" : "Add"} item · cyberroadmap`;

  const form = h("form", { class: "card form-card" },
    h("div", { class: "field" },
      h("label", { for: "title" }, "Title ", h("span", { class: "req" }, "*")),
      h("input", { id: "title", type: "text", name: "title", required: true, maxlength: 200, autofocus: true,
        value: item.title || "", placeholder: "e.g. Practical Ethical Hacking" })),
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Type"),
      segmented("type", options.types, item.type || "course")),
    h("div", { class: "field-grid" },
      h("div", { class: "field" }, h("label", { for: "platform" }, "Platform"),
        h("select", { id: "platform", name: "platform" },
          h("option", { value: "" }, "None"),
          options.platforms.map((p) => h("option", { value: p, selected: item.platform === p }, p)))),
      h("div", { class: "field" }, h("label", { for: "url" }, "Link"),
        h("input", { id: "url", type: "url", name: "url", value: item.url || "", placeholder: "https://", maxlength: 500 }))),
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Difficulty"),
      segmented("difficulty", options.difficulties, item.difficulty || "beginner", "segmented-diff", (d) => `d-${d}`)),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Priority ", h("span", { class: "hint" }, "5 = do this first")),
      segmented("priority", [1, 2, 3, 4, 5], item.priority || 3, "segmented-prio")),
    h("div", { class: "field" },
      h("label", { for: "skill_tags" }, "Skill tags ", h("span", { class: "hint" }, "comma-separated")),
      h("input", { id: "skill_tags", type: "text", name: "skill_tags", maxlength: 200, value: item.skill_tags || "",
        placeholder: "web, network, active directory" })),
    h("div", { class: "form-actions" },
      h("a", { href: id ? `item.html?id=${encodeURIComponent(id)}` : "progress.html", class: "btn btn-ghost" }, "Cancel"),
      h("button", { type: "submit", class: "btn btn-primary" }, id ? "Save changes" : "Add to roadmap")));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    data.priority = Number(data.priority || 3);
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = id
        ? await api.roadmap.put(`/items/${encodeURIComponent(id)}`, data)
        : await api.roadmap.post("/items", data);
      flashNext(id ? "Item updated." : "Added to your roadmap.");
      location.href = `item.html?id=${result.item.id}`;
    } catch (err) {
      flash(errorText(err));
      button.disabled = false;
    }
  });

  render(main, 
    ...[...main.querySelectorAll(".flash-wrap")],
    h("a", { href: "progress.html", class: "back" }, "← Progress"),
    h("div", { class: "page-head" }, h("div", {},
      h("p", { class: "eyebrow" }, id ? "Edit item" : "New item"),
      h("h1", {}, id ? item.title : "Add to your roadmap"))),
    form);
}

load().catch((err) => {
  main.querySelector(".loading")?.remove();
  flash(err.status === 404 ? "Item not found." : errorText(err));
});
