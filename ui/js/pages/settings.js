// Profile: recent sign-ins, change password, delete account.
// Deleting the account is a cross-service flow: roadmap first asks progress to
// delete this user's logs and refuses (503) if it can't, so no personal data
// is left behind in progress.
import { api, session } from "../api.js";
import { requireLogin } from "../auth.js";
import { errorText, flash, flashNext, h, render } from "../ui.js";

const user = requireLogin();
const main = document.querySelector("main");

function passwordField(id, text, autocomplete) {
  return h("div", { class: "field" }, h("label", { for: id }, text),
    h("input", { id, name: id, type: "password", required: true, autocomplete, maxlength: 200 }));
}

function passwordForm() {
  const form = h("form", {},
    passwordField("current", "Current password", "current-password"),
    passwordField("new", "New password", "new-password"),
    passwordField("confirm", "Confirm new password", "new-password"),
    h("div", { class: "form-actions" }, h("button", { type: "submit", class: "btn btn-primary" }, "Change password")));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    if (data.new !== data.confirm) { flash("New passwords don't match."); return; }
    try {
      // Every other session's token stops working; this one gets a fresh token.
      session.save(await api.roadmap.post("/me/password", { current: data.current, new: data.new }));
      flashNext("Password changed. You've been logged out everywhere else.");
      location.reload();
    } catch (err) {
      flash(errorText(err));
      form.reset();
    }
  });
  return form;
}

function deleteForm() {
  const form = h("form", {},
    h("p", { class: "muted" }, "Deletes your account, roadmap, assessments and every progress log. This can't be undone."),
    passwordField("delete-password", "Password", "current-password"),
    h("div", { class: "form-actions" }, h("button", { type: "submit", class: "btn btn-danger" }, "Delete my account")));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!confirm("Delete your account and all your data?")) return;
    try {
      await api.roadmap.del("/me", { password: form.querySelector("input").value });
      session.clear();
      flashNext("Your account and all its data have been deleted.");
      location.href = "login.html";
    } catch (err) {
      flash(errorText(err));   // 503 if progress couldn't delete the logs: the account is kept
      form.reset();
    }
  });
  return form;
}

async function load() {
  const { logins } = await api.roadmap.get("/me");
  render(main, 
    ...[...main.querySelectorAll(".flash-wrap")],
    h("div", { class: "page-head" }, h("div", {},
      h("p", { class: "eyebrow" }, "Profile"),
      h("h1", {}, user.username))),
    h("div", { class: "detail-grid" },
      h("section", { class: "card" }, h("h2", {}, "Change password"), passwordForm()),
      h("section", { class: "card" }, h("h2", {}, "Recent sign-ins"),
        logins.length
          ? h("ol", { class: "timeline" }, logins.map((l) => h("li", {}, h("div", { class: "tl-head" },
              h("span", { class: "tl-date" }, String(l.created_at).slice(0, 16).replace("T", " ")),
              h("span", { class: `pill ${l.success ? "s-pill-completed" : "f-pill-brutal"}` }, l.success ? "signed in" : "failed"),
              h("span", { class: "muted" }, l.ip || "")))))
          : h("p", { class: "muted" }, "No sign-ins recorded yet."))),
    h("section", { class: "card card-danger" }, h("h2", {}, "Delete account"), deleteForm()));
}

load().catch((err) => {
  main.querySelector(".loading")?.remove();
  flash(errorText(err));
});
