#!/usr/bin/env node
// Regenerates the embedded PLAYERS array in index.html and list.html from
// CombinedLists.csv. CombinedLists.csv is the single source of truth; run
// this script after every edit to it, then commit the updated HTML files.
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const CSV_PATH = path.join(ROOT, "CombinedLists.csv");
const INDEX_PATH = path.join(ROOT, "index.html");
const LIST_PATH = path.join(ROOT, "list.html");

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

function loadRows() {
  const raw = fs.readFileSync(CSV_PATH, "utf8");
  const [header, ...data] = parseCSV(raw);
  const col = (r, name) => r[header.indexOf(name)];
  return data.map((r) => ({
    name: col(r, "Name"),
    ovr: Number(col(r, "OVR")),
    tier: col(r, "Letter"),
    year: Number(col(r, "Year")),
    clan: col(r, "Clan") || "",
    source: col(r, "Source"),
    canonical: col(r, "Canonical") || col(r, "Name"),
  }));
}

function buildListPlayers(rows) {
  return rows.map((r) => ({
    name: r.name,
    ovr: r.ovr,
    tier: r.tier,
    year: r.year,
    clan: r.clan,
    source: r.source,
    canonical: r.canonical,
  }));
}

// One entry per player: the highest-OVR row wins (ties broken by the more
// recent year); its clan is used unless blank, in which case the most
// recent year among the player's other rows that has a clan set is used.
function buildIndexPlayers(rows) {
  const byCanon = new Map();
  for (const r of rows) {
    if (!byCanon.has(r.canonical)) byCanon.set(r.canonical, []);
    byCanon.get(r.canonical).push(r);
  }

  const players = [];
  for (const [canonical, group] of byCanon) {
    let best = group[0];
    for (const r of group) {
      if (r.ovr > best.ovr || (r.ovr === best.ovr && r.year > best.year)) best = r;
    }
    let clan = best.clan;
    if (!clan) {
      const withClan = group.filter((r) => r.clan).sort((a, b) => b.year - a.year);
      if (withClan.length) clan = withClan[0].clan;
    }
    players.push({ name: canonical, ovr: best.ovr, tier: best.tier, clan, year: best.year });
  }

  players.sort((a, b) => b.ovr - a.ovr || a.name.localeCompare(b.name));
  return players;
}

function replacePlayersArray(html, players) {
  const marker = "var PLAYERS = ";
  const start = html.indexOf(marker);
  if (start === -1) throw new Error("could not find `var PLAYERS = ` in file");
  const arrayStart = start + marker.length;
  const arrayEnd = html.indexOf("];", arrayStart) + 2;
  return html.slice(0, arrayStart) + JSON.stringify(players) + ";" + html.slice(arrayEnd);
}

function main() {
  const rows = loadRows();

  const indexHtml = fs.readFileSync(INDEX_PATH, "utf8");
  fs.writeFileSync(INDEX_PATH, replacePlayersArray(indexHtml, buildIndexPlayers(rows)));

  const listHtml = fs.readFileSync(LIST_PATH, "utf8");
  fs.writeFileSync(LIST_PATH, replacePlayersArray(listHtml, buildListPlayers(rows)));

  console.log(`Regenerated PLAYERS in index.html (${buildIndexPlayers(rows).length} players) and list.html (${rows.length} rows) from CombinedLists.csv.`);
}

main();
