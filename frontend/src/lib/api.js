const BASE = "/api";

const CSRF_COOKIE = "i2b2ml_csrf";
const CSRF_HEADER = "X-CSRF-Token";

/**
 * Called when the backend says the session has ended.
 *
 * Registered by SessionProvider. Without it, a session that expires mid-use
 * turns every panel into its own red error box — nine different ways of saying
 * "sign in again" and no way to do it.
 */
let onUnauthenticated = () => {};

export function setUnauthenticatedHandler(fn) {
  onUnauthenticated = fn ?? (() => {});
}

/**
 * A route this account may not call.
 *
 * Distinct from a failure on purpose: `workspace.jsx` turns every rejection
 * into a red "could not load X" panel, and a researcher seeing that for a
 * custodian-only endpoint would reasonably think the app was broken.
 */
export class ForbiddenError extends Error {
  constructor(message) {
    super(message);
    this.name = "ForbiddenError";
    this.forbidden = true;
  }
}

function readCookie(name) {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * The CSRF token, held in memory.
 *
 * The server validates the header against the token stored on the session
 * row, not against the cookie - so the client only has to *know* the value,
 * and `/auth/login` and `/auth/me` both return it. Keeping it here rather
 * than reading `document.cookie` removes a whole class of cookie-scope bug:
 * the cookie was originally set with Path=/api and was therefore invisible to
 * the app's own pages at "/", so no header was ever sent and every unsafe
 * request 403'd.
 */
let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token ?? null;
}

function csrfHeaders() {
  // Cookie as a fallback, for the window between a reload and /auth/me
  // answering.
  const token = csrfToken ?? readCookie(CSRF_COOKIE);
  return token ? { [CSRF_HEADER]: token } : {};
}

// FastAPI puts validation messages in a `detail` body; without this every
// 400/409 reads as a bare status code.
async function detailOf(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (body.detail) return JSON.stringify(body.detail);
  } catch {
    // non-JSON error body; fall through to the status line
  }
  return `${res.status} ${res.statusText}`;
}

async function unwrap(res) {
  if (res.ok) return res.json();

  if (res.status === 401) {
    onUnauthenticated();
    throw new Error("your session has ended — sign in again");
  }
  if (res.status === 403) throw new ForbiddenError(await detailOf(res));

  throw new Error(await detailOf(res));
}

// same-origin rather than include: the frontend is served from the same origin
// as the API in dev (Vite proxies /api) and in production, so the cookie rides
// along without widening CORS.
const CREDENTIALS = "same-origin";

export async function apiGet(path) {
  return unwrap(await fetch(`${BASE}${path}`, { credentials: CREDENTIALS }));
}

export async function apiDelete(path) {
  return unwrap(
    await fetch(`${BASE}${path}`, {
      method: "DELETE",
      credentials: CREDENTIALS,
      headers: csrfHeaders(),
    }),
  );
}

export async function apiUpload(path, file, params) {
  const fd = new FormData();
  fd.append("file", file); // field name must match the FastAPI parameter
  // Loader flags are query params; the file is the whole multipart body.
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  // No Content-Type header — the browser sets the multipart boundary itself.
  return unwrap(
    await fetch(`${BASE}${path}${qs}`, {
      method: "POST",
      credentials: CREDENTIALS,
      headers: csrfHeaders(),
      body: fd,
    }),
  );
}

export async function apiPost(path, body) {
  return unwrap(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      credentials: CREDENTIALS,
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(body),
    }),
  );
}
