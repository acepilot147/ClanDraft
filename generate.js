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

// Tier letters are derived from OVR; the thresholds reproduce the
// hand-assigned Letter column the CSV used to carry.
function tierFromOvr(ovr) {
  if (ovr >= 97) return "X";
  if (ovr >= 93) return "S+";
  if (ovr >= 89) return "S";
  if (ovr >= 80) return "A";
  if (ovr >= 70) return "B";
  if (ovr >= 65) return "C";
  return "D";
}

function loadRows() {
  const raw = fs.readFileSync(CSV_PATH, "utf8");
  const [header, ...data] = parseCSV(raw);
  const col = (r, name) => r[header.indexOf(name)];
  return data.map((r) => ({
    name: col(r, "Name").trim(),
    ovr: Number(col(r, "OVR")),
    tier: tierFromOvr(Number(col(r, "OVR"))),
    year: Number(col(r, "Year")) || 0,
    clan: col(r, "Clan") || "",
    cheater: col(r, "Cheater") === "TRUE",
    source: col(r, "Source") || "",
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
  }));
}

// One entry per player: the highest-OVR row wins (ties broken by the more
// recent year); its clan is used unless blank, in which case the most
// recent year among the player's other rows that has a clan set is used.
function buildIndexPlayers(rows) {
  const byName = new Map();
  for (const r of rows) {
    if (!byName.has(r.name)) byName.set(r.name, []);
    byName.get(r.name).push(r);
  }

  const players = [];
  for (const [name, group] of byName) {
    let best = group[0];
    for (const r of group) {
      if (r.ovr > best.ovr || (r.ovr === best.ovr && r.year > best.year)) best = r;
    }
    let clan = best.clan;
    if (!clan) {
      const withClan = group.filter((r) => r.clan).sort((a, b) => b.year - a.year);
      if (withClan.length) clan = withClan[0].clan;
    }
    const player = { name, ovr: best.ovr, tier: best.tier, clan, year: best.year };
    if (group.some((r) => r.cheater)) player.cheater = true;
    players.push(player);
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
