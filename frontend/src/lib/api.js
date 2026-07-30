const BASE = "/api";

// FastAPI puts validation messages in a `detail` body; without this every
// 400/409 reads as a bare status code.
async function unwrap(res) {
  if (res.ok) return res.json();
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (body.detail) detail = JSON.stringify(body.detail);
  } catch {
    // non-JSON error body; keep the status line
  }
  throw new Error(detail);
}

export async function apiGet(path) {
  return unwrap(await fetch(`${BASE}${path}`));
}

export async function apiDelete(path) {
  return unwrap(await fetch(`${BASE}${path}`, { method: "DELETE" }));
}

export async function apiUpload(path, file, params) {
  const fd = new FormData();
  fd.append("file", file); // field name must match the FastAPI parameter
  // Loader flags are query params; the file is the whole multipart body.
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  // No Content-Type header — the browser sets the multipart boundary itself.
  return unwrap(await fetch(`${BASE}${path}${qs}`, { method: "POST", body: fd }));
}

export async function apiPost(path, body) {
  return unwrap(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
