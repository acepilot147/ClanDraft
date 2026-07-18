// Minimal RFC 4180 CSV reader/writer shared by the repo's node scripts.
"use strict";

function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

// Strips a leading U+FEFF byte-order mark (invisible in most editors);
// spreadsheet apps re-add it on save and it breaks header parsing.
function readCSV(fs, path) {
  return parseCSV(fs.readFileSync(path, "utf8").replace(/^﻿/, ""));
}

function formatCSV(rows) {
  return rows
    .map((row) =>
      row
        .map((f) => {
          const s = f == null ? "" : String(f);
          return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        })
        .join(",")
    )
    .join("\n") + "\n";
}

module.exports = { parseCSV, readCSV, formatCSV };
