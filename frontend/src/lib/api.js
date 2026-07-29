const BASE = "/api";

export async function apiGet(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function apiDelete(path) {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function apiUpload(path, file, params) {
  const fd = new FormData();
  fd.append("file", file); // field name must match the FastAPI parameter
  // Loader flags are query params; the file is the whole multipart body.
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  // No Content-Type header — the browser sets the multipart boundary itself.
  const res = await fetch(`${BASE}${path}${qs}`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
