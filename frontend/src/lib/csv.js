/**
 * Client-side CSV download.
 *
 * No endpoint produces CSV, and none needs to — every table the user wants to
 * take away is already in the browser. Building the file here also means what
 * downloads is exactly what was on screen.
 */

function cell(value) {
  const s = value == null ? "" : String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(header, rows) {
  return [header, ...rows].map((line) => line.map(cell).join(",")).join("\r\n");
}

export function downloadCsv(filename, header, rows) {
  // A BOM, so Excel opens UTF-8 patient identifiers correctly rather than
  // mangling them into Latin-1.
  const blob = new Blob(["﻿", toCsv(header, rows)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
