// DOM helpers and the shared page shell (sidebar, flash messages, banner).
//
// Everything is built with h(), which sets text with textContent and attributes
// with setAttribute. Data from the API never goes through innerHTML, so a
// roadmap item titled "<script>…" is shown as text, not run. (Jinja escaped
// this automatically in Assignment 1; here it's this helper's job.)

const ICONS = {
  book: '<path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5c-3.5-.5-6.5 0-8.5 1.5zM12 6.5v13"/>',
  chart: '<path d="M5 19v-5M10 19V9M15 19v-7M20 19V6"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    // Styles go through the CSSOM: the CSP blocks inline style="" attributes.
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// The icon markup is a constant from ICONS above, never API data.
export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name];
  return svg;
}

export function duration(minutes) {
  const m = Math.max(0, Math.round(minutes || 0));
  const hours = Math.floor(m / 60);
  const rest = m % 60;
  if (hours && rest) return `${hours}h ${rest}m`;
  return hours ? `${hours}h` : `${rest}m`;
}

export const label = (s) => String(s || "").replaceAll("_", " ");
export const tags = (raw) => String(raw || "").split(",").map((t) => t.trim()).filter(Boolean);
export const param = (name) => new URLSearchParams(location.search).get(name);

// ── Flash messages survive one navigation, like Flask's flash() ────────────
const FLASH_KEY = "cyberroadmap.flash";

export function flashNext(message) {
  sessionStorage.setItem(FLASH_KEY, message);
}

// Show a message at the top of the page, replacing any earlier one.
export function flash(message, kind = "") {
  const wrap = document.querySelector(".flash-wrap") || h("div", { class: "flash-wrap" });
  if (!wrap.isConnected) document.querySelector("main").prepend(wrap);
  wrap.replaceChildren(h("div", { class: `flash ${kind}`.trim(), role: "status" }, message));
}

function showPendingFlash() {
  const msg = sessionStorage.getItem(FLASH_KEY);
  if (msg) {
    sessionStorage.removeItem(FLASH_KEY);
    flash(msg);
  }
}

// ── "Starting up" banner (see api.js) ──────────────────────────────────────
export function showBanner(message) {
  let el = document.getElementById("wake-banner");
  if (!el) {
    el = h("div", { id: "wake-banner", class: "flash wake", role: "status", "aria-live": "polite" });
    document.body.prepend(el);
  }
  el.textContent = message;
}

export function hideBanner() {
  document.getElementById("wake-banner")?.remove();
}

// ── Page shell ─────────────────────────────────────────────────────────────
const NAV = [
  { href: "progress.html", label: "Progress", icon: "chart", match: ["progress.html", "item.html", "item-edit.html"] },
  { href: "stats.html", label: "Stats", icon: "calendar", match: ["stats.html"] },
  { href: "settings.html", label: "Profile", icon: "user", match: ["settings.html"] },
];

// Wraps the page's <main> in the logged-in layout. Pages call this first.
export function shell(user, onLogout) {
  const page = location.pathname.split("/").pop() || "index.html";
  const main = document.querySelector("main");
  main.className = "main";
  const sidebar = h("aside", { class: "sidebar" },
    h("a", { href: "progress.html", class: "logo" }, "cyberroadmap"),
    h("nav", { class: "side-nav", "aria-label": "Main" },
      NAV.map((link) => {
        const active = link.match.includes(page);
        return h("a", { href: link.href, class: active ? "active" : null, "aria-current": active ? "page" : null },
          icon(link.icon), h("span", {}, link.label));
      })),
    h("a", { href: "item-edit.html", class: "btn btn-primary side-add" }, icon("plus"), " Add item"),
    h("div", { class: "sidebar-foot" },
      h("span", { class: "side-user", title: `Signed in as ${user.username}` }, user.username),
      h("button", { type: "button", class: "link-btn", onclick: onLogout }, "Log out")),
  );
  const wrapper = h("div", { class: "shell" });
  main.replaceWith(wrapper);
  wrapper.append(sidebar, main);
  showPendingFlash();
}

export function authShell() {
  document.querySelector("main").className = "auth-shell";
  showPendingFlash();
}

export function errorText(err) {
  return err?.message || "Something went wrong.";
}

// Replace a container's content. Like h(), skips false/null/undefined, so pages
// can write `condition && h(...)` without the word "false" appearing.
export function render(parent, ...children) {
  parent.replaceChildren(...children.flat().filter((c) => c !== false && c !== null && c !== undefined));
}
