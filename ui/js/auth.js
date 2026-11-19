// Shared by every logged-in page: redirect to login without a session, draw the
// shell, wire up "Log out". Tokens are stateless, so logging out is forgetting it.
import { session } from "./api.js";
import { shell, flashNext } from "./ui.js";

export function requireLogin() {
  const user = session.user;
  if (!session.token || !user) {
    location.replace(`login.html?next=${encodeURIComponent(location.pathname + location.search)}`);
    throw new Error("not logged in");
  }
  shell(user, () => {
    session.clear();
    flashNext("You've been logged out.");
    location.href = "login.html";
  });
  return user;
}

// Only follow ?next= to a page on this site, never to another origin.
export function safeNext(raw) {
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "progress.html";
}
