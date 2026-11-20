import { api, session } from "../api.js";
import { safeNext } from "../auth.js";
import { authShell, errorText, flash, flashNext, h, param, render } from "../ui.js";

const isRegister = location.pathname.endsWith("register.html");

const main = document.querySelector("main");
const usernameInput = h("input", { id: "username", type: "text", name: "username", required: true, autofocus: true,
  autocomplete: "username", maxlength: 30,
  // Same rule the roadmap service enforces; checking here just saves a round trip.
  pattern: isRegister ? "[A-Za-z0-9_]{3,30}" : null,
  title: isRegister ? "3-30 letters, numbers or underscores (not an email address)" : null });
const passwordInput = h("input", { id: "password", type: "password", name: "password", required: true,
  autocomplete: isRegister ? "new-password" : "current-password", minlength: isRegister ? 8 : null, maxlength: 200 });
const confirmInput = isRegister
  ? h("input", { id: "confirm", type: "password", name: "confirm", required: true, autocomplete: "new-password" })
  : null;
const submit = h("button", { type: "submit", class: "btn btn-primary btn-block" }, isRegister ? "Create account" : "Log in");

const form = h("form", { class: "card auth-card", novalidate: false },
  h("div", { class: "field" },
    h("label", { for: "username" }, "Username ",
      isRegister && h("span", { class: "hint" }, "letters, numbers or _ (not your email)")),
    usernameInput),
  h("div", { class: "field" },
    h("label", { for: "password" }, "Password ", isRegister && h("span", { class: "hint" }, "at least 8 characters")),
    passwordInput),
  confirmInput && h("div", { class: "field" }, h("label", { for: "confirm" }, "Confirm password"), confirmInput),
  submit,
);

render(main, 
  h("a", { href: "login.html", class: "logo logo-center" }, "cyberroadmap"),
  h("div", { class: "auth" },
    h("div", { class: "auth-head" },
      h("h1", {}, isRegister ? "Create your account" : "Welcome back"),
      h("p", { class: "muted" }, isRegister ? "Track what you plan to learn and what you've done." : "Log in to pick up where you left off.")),
    form,
    isRegister
      ? h("p", { class: "auth-switch" }, "Already have an account? ", h("a", { href: "login.html" }, "Log in"))
      : h("p", { class: "auth-switch" }, "New here? ", h("a", { href: "register.html" }, "Create an account"))),
);
authShell();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  document.querySelector(".flash-wrap")?.remove();
  if (isRegister && passwordInput.value !== confirmInput.value) {
    flash("Passwords don't match.");
    return;
  }
  submit.disabled = true;
  try {
    const result = await api.roadmap.post(isRegister ? "/auth/register" : "/auth/login",
      { username: usernameInput.value, password: passwordInput.value });
    session.save(result);
    if (result.failed_attempts) {
      const n = result.failed_attempts;
      flashNext(`Heads up: ${n} failed login attempt${n === 1 ? "" : "s"} on your account since you last logged in. Check Profile if that wasn't you.`);
    } else if (isRegister) {
      flashNext("Account created. Add the first thing you want to learn.");
    }
    location.href = safeNext(param("next"));
  } catch (err) {
    flash(errorText(err));
    passwordInput.value = "";
    if (confirmInput) confirmInput.value = "";
  } finally {
    submit.disabled = false;
  }
});
