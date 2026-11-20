// Talks to the two services. Every page goes through api.roadmap / api.progress.
//
// Cold starts (A2 §7.5): on Azure both apps scale to zero and the databases
// pause, so the first request after idle can fail to connect, return 503 from
// the Container Apps proxy, or 503 "starting_up" from our own code while the
// database resumes. GET requests are retried with backoff for up to ~90 s while
// a "starting up" banner is shown. Writes are not retried automatically (a
// retried POST could save twice); the user gets a message and can resend.

import { showBanner, hideBanner } from "./ui.js";

const TOKEN_KEY = "cyberroadmap.token";
const USER_KEY = "cyberroadmap.user";
const RETRY_FOR_MS = 90_000;

// Session storage: the token disappears when the tab closes, which limits how
// long a stolen token is useful. Pages never put API data into innerHTML (see
// ui.js), so script injection can't read it in the first place.
export const session = {
  get token() { return sessionStorage.getItem(TOKEN_KEY); },
  get user() {
    try { return JSON.parse(sessionStorage.getItem(USER_KEY)); } catch { return null; }
  },
  save({ token, user }) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function isWaking(status, body) {
  // 502/503/504 from the platform while the app starts, or our own 503s.
  return status === 502 || status === 504 || (status === 503 && body?.error !== "roadmap_unavailable");
}

async function request(base, method, path, body) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (session.token) headers.Authorization = `Bearer ${session.token}`;

  const started = Date.now();
  let delay = 2000;
  for (;;) {
    let resp = null;
    let data = null;
    try {
      resp = await fetch(`${base}${path}`, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
      data = resp.status === 204 ? null : await resp.json().catch(() => null);
    } catch {
      resp = null;   // network error: app not reachable yet (or CORS)
    }

    const waking = resp === null || isWaking(resp.status, data);
    if (waking && method === "GET" && Date.now() - started < RETRY_FOR_MS) {
      showBanner("The service is starting up after being idle. Retrying…");
      await sleep(delay);
      delay = Math.min(delay * 1.5, 10_000);
      continue;
    }
    hideBanner();

    if (resp === null) {
      throw new ApiError(0, { message: "Can't reach the service right now. Try again in a minute." });
    }
    if (resp.status === 401 && !path.startsWith("/auth/")) {
      session.clear();
      location.href = `login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
      return new Promise(() => {});   // page is navigating away
    }
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data;
  }
}

function client(base) {
  return {
    get: (path) => request(base, "GET", path),
    post: (path, body = {}) => request(base, "POST", path, body),
    put: (path, body = {}) => request(base, "PUT", path, body),
    patch: (path, body = {}) => request(base, "PATCH", path, body),
    del: (path, body) => request(base, "DELETE", path, body),
  };
}

const config = window.APP_CONFIG || {};
export const api = {
  roadmap: client(config.ROADMAP_URL || ""),
  progress: client(config.PROGRESS_URL || ""),
};

export function query(params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}
