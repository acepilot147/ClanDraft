#!/usr/bin/env node
// Resolves scoreboard handles to canonical CombinedLists.csv names.
//
//   node resolve-handles.js handle1 handle2 ...
//   node resolve-handles.js --json handle1 handle2 ...
//
// Resolution order (strongest first):
//   MATCH     exact canonical name in CombinedLists.csv, or a confirmed alias
//             recorded in ALIASES.md.
//   CANDIDATE the handle appears in some account's Roblox rename history
//             (RobloxNames.csv), or matches a canonical name under I/l
//             look-alike normalization. Evidence, not proof - confirm with
//             a_cemaster and record the decision in ALIASES.md before merging.
//   UNKNOWN   no trace anywhere; likely a genuinely new player.
"use strict";

const fs = require("fs");
const path = require("path");
const { readCSV } = require("./csv");

const ROOT = __dirname;

// Lookup key: case-insensitive, with capital-I-for-lowercase-l obfuscation
// collapsed ("eviImatty" and "evilmatty" get the same key). Only used to
// FIND candidates; exact-case identity is preserved in the output.
function confusableKey(name) {
  return name.trim().toLowerCase().replace(/i/g, "l");
}
function exactKey(name) {
  return name.trim().toLowerCase();
}

function loadCanonicals() {
  const rows = readCSV(fs, path.join(ROOT, "CombinedLists.csv"));
  const set = new Set();
  for (let i = 1; i < rows.length; i++) if (rows[i][0]) set.add(rows[i][0]);
  return set;
}

// Parses the pipe tables in ALIASES.md. Both alias tables have the shape
// | canonical | alias, alias | notes | - the "Do NOT merge" section is a
// bullet list, so it is naturally skipped.
function loadAliases() {
  const text = fs.readFileSync(path.join(ROOT, "ALIASES.md"), "utf8");
  const map = new Map(); // exactKey(alias) -> canonical
  for (const line of text.split("\n")) {
    if (!line.startsWith("|")) continue;
    const cells = line.split("|").map((c) => c.replace(/`/g, "").trim());
    // cells[0] is empty (leading pipe); canonical = cells[1], aliases = cells[2]
    if (cells.length < 3 || !cells[1] || /^-+$/.test(cells[1])) continue;
    if (/^Canonical/i.test(cells[1])) continue;
    const canonical = cells[1];
    for (const alias of cells[2].split(",").map((a) => a.trim()).filter(Boolean)) {
      map.set(exactKey(alias), canonical);
    }
    map.set(exactKey(canonical), canonical);
  }
  return map;
}

function loadRenameHistory() {
  const rows = readCSV(fs, path.join(ROOT, "RobloxNames.csv"));
  const map = new Map(); // exactKey(handle) -> Set of LegacyNames it points to
  const add = (handle, legacy) => {
    const k = exactKey(handle);
    if (!map.has(k)) map.set(k, new Set());
    map.get(k).add(legacy);
  };
  const header = rows[0];
  const iLegacy = header.indexOf("LegacyName");
  const iCurrent = header.indexOf("CurrentName");
  const iPast = header.indexOf("PastNames");
  for (let i = 1; i < rows.length; i++) {
    const legacy = rows[i][iLegacy];
    if (!legacy) continue;
    if (rows[i][iCurrent]) add(rows[i][iCurrent], legacy);
    for (const p of (rows[i][iPast] || "").split("|").map((s) => s.trim()).filter(Boolean)) {
      add(p, legacy);
    }
  }
  return map;
}

function resolve(handle, ctx) {
  const ek = exactKey(handle);
  const ck = confusableKey(handle);

  if (ctx.aliasMap.has(ek))
    return { handle, status: "MATCH", canonical: ctx.aliasMap.get(ek), via: "ALIASES.md" };
  if (ctx.canonicalExact.has(ek))
    return { handle, status: "MATCH", canonical: ctx.canonicalExact.get(ek), via: "CombinedLists" };

  const candidates = new Set();
  if (ctx.renames.has(ek)) for (const l of ctx.renames.get(ek)) candidates.add(l);
  if (ctx.canonicalConfusable.has(ck)) candidates.add(ctx.canonicalConfusable.get(ck));
  if (ctx.aliasConfusable.has(ck)) candidates.add(ctx.aliasConfusable.get(ck));
  if (candidates.size)
    return { handle, status: "CANDIDATE", candidates: [...candidates], via: "rename history / I-l look-alike" };

  return { handle, status: "UNKNOWN" };
}

function main() {
  const args = process.argv.slice(2);
  const json = args.includes("--json");
  const handles = args.filter((a) => a !== "--json");
  if (!handles.length) {
    console.error("usage: node resolve-handles.js [--json] handle1 handle2 ...");
    process.exit(1);
  }

  const canonicals = loadCanonicals();
  const canonicalExact = new Map();
  const canonicalConfusable = new Map();
  for (const c of canonicals) {
    canonicalExact.set(exactKey(c), c);
    canonicalConfusable.set(confusableKey(c), c);
  }
  const aliasMap = loadAliases();
  const aliasConfusable = new Map();
  for (const [k, v] of aliasMap) aliasConfusable.set(k.replace(/i/g, "l"), v);
  const renames = loadRenameHistory();

  const ctx = { canonicalExact, canonicalConfusable, aliasMap, aliasConfusable, renames };
  const results = handles.map((h) => resolve(h, ctx));

  if (json) {
    console.log(JSON.stringify(results, null, 2));
    return;
  }
  for (const r of results) {
    if (r.status === "MATCH") console.log(`MATCH      ${r.handle} -> ${r.canonical}  (${r.via})`);
    else if (r.status === "CANDIDATE") console.log(`CANDIDATE  ${r.handle} -> ${r.candidates.join(" | ")}  (${r.via}; confirm + record in ALIASES.md)`);
    else console.log(`UNKNOWN    ${r.handle}  (new player?)`);
  }
}

main();
