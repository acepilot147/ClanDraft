#!/usr/bin/env node
// Regenerates the embedded PLAYERS array in index.html and list.html from
// CombinedLists.csv. CombinedLists.csv is the single source of truth; run
// this script after every edit to it, then commit the updated HTML files.
"use strict";

const fs = require("fs");
const path = require("path");
const { parseCSV } = require("./csv");

const ROOT = __dirname;
const CSV_PATH = path.join(ROOT, "CombinedLists.csv");
const INDEX_PATH = path.join(ROOT, "index.html");
const LIST_PATH = path.join(ROOT, "list.html");

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
  // The regex strips a leading U+FEFF byte-order mark (invisible in most editors);
  // spreadsheet apps re-add it to the CSV on save and it breaks header parsing.
  const raw = fs.readFileSync(CSV_PATH, "utf8").replace(/^﻿/, "");
  const [header, ...data] = parseCSV(raw);
  const col = (r, name) => r[header.indexOf(name)];
  // The name column was renamed Name -> LegacyName at some point; accept both.
  const nameCol = header.indexOf("Name") !== -1 ? "Name" : "LegacyName";
  return data.map((r) => ({
    name: col(r, nameCol).trim(),
    ovr: Number(col(r, "OVR")),
    tier: tierFromOvr(Number(col(r, "OVR"))),
    year: Number(col(r, "Year")) || 0,
    clan: col(r, "Clan") || "",
    leader: (col(r, "Leader") || "").trim(),
    cheater: col(r, "Cheater") === "TRUE",
    rcl: col(r, "RCL") === "TRUE",
    source: col(r, "Source") || "",
  }));
}

function buildListPlayers(rows) {
  return rows.map((r) => {
    const row = {
      name: r.name,
      ovr: r.ovr,
      tier: r.tier,
      year: r.year,
      clan: r.clan,
      source: r.source,
    };
    if (r.cheater) row.cheater = true;
    if (r.rcl) row.rcl = true;
    if (r.leader) row.leader = r.leader;
    return row;
  });
}

// One entry per CSV row, so every year's variation of a player can show up
// in the draft pool (not just their highest-OVR version). A row's clan is
// used unless blank, in which case only the immediately preceding year's row
// may supply it. If that row has no clan either, the entry shows no clan tag
// (old clans don't carry forward). A cheater flag on any row marks the
// person, so it applies to all of their variations.
function buildIndexPlayers(rows) {
  const byName = new Map();
  for (const r of rows) {
    if (!byName.has(r.name)) byName.set(r.name, []);
    byName.get(r.name).push(r);
  }

  const players = [];
  for (const [name, group] of byName) {
    const cheater = group.some((r) => r.cheater);
    // Leadership is a person-wide trait: the most recent row that carries a
    // Leader class speaks for all of that player's yearly variations.
    const leadRow = group.filter((g) => g.leader).sort((a, b) => b.year - a.year)[0];
    for (const r of group) {
      let clan = r.clan;
      if (!clan) {
        const earlier = group.filter((g) => g.year < r.year).sort((a, b) => b.year - a.year);
        if (earlier.length) clan = earlier[0].clan;
      }
      const player = { name, ovr: r.ovr, tier: r.tier, clan, year: r.year };
      if (leadRow) player.leader = leadRow.leader;
      if (cheater) player.cheater = true;
      if (r.rcl) player.rcl = true;
      players.push(player);
    }
  }

  players.sort((a, b) => b.ovr - a.ovr || a.name.localeCompare(b.name) || b.year - a.year);
  return players;
}

function replaceArray(html, marker, arr) {
  const start = html.indexOf(marker);
  if (start === -1) throw new Error("could not find `" + marker + "` in file");
  const arrayStart = start + marker.length;
  const arrayEnd = html.indexOf("];", arrayStart) + 2;
  return html.slice(0, arrayStart) + JSON.stringify(arr) + ";" + html.slice(arrayEnd);
}

function main() {
  const rows = loadRows();

  let indexHtml = fs.readFileSync(INDEX_PATH, "utf8");
  indexHtml = replaceArray(indexHtml, "var PLAYERS = ", buildIndexPlayers(rows));
  indexHtml = replaceArray(indexHtml, "var ROWS = ", buildListPlayers(rows));
  fs.writeFileSync(INDEX_PATH, indexHtml);

  const listHtml = fs.readFileSync(LIST_PATH, "utf8");
  fs.writeFileSync(LIST_PATH, replaceArray(listHtml, "var PLAYERS = ", buildListPlayers(rows)));

  console.log(`Regenerated PLAYERS+ROWS in index.html (${buildIndexPlayers(rows).length} players) and list.html (${rows.length} rows) from CombinedLists.csv.`);
}

main();
