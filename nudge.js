#!/usr/bin/env node
// Nudges CombinedLists.csv OVRs from per-game raid scoreboards (RaidStats.csv).
//
//   node nudge.js            report only: prints movers, writes NudgeReport.csv
//   node nudge.js --apply    also upserts Year=2026 / Source="Raid nudge" rows
//                            into CombinedLists.csv (then run generate.js)
//
// Model: score-against-expectation with Bayesian shrinkage.
//   1. Within each game, every player gets a composite performance z-score
//      built from kills, damage-beyond-kills (residual of a per-game
//      dmg~kills fit, so assault-gun volume isn't double-counted), and heals.
//   2. Expected z comes from the priors of everyone in that lobby - being
//      last in a stacked lobby you were expected to be last in is NOT a
//      negative signal. A team-asymmetry term credits stats earned on the
//      weaker side of the lobby.
//   3. The surprise (observed - expected) updates the rating with a Kalman
//      gain, so one game is a nudge and only sustained over/under-performance
//      moves a rating far. Stale priors (old source years) get wider
//      uncertainty and therefore move more.
//
// Idempotent by construction: priors EXCLUDE rows the raid games themselves
// produced (Source "Raid stats" hand re-score, and this script's own
// "Raid nudge" rows), and every run recomputes from scratch over all games
// in RaidStats.csv. Re-running after --apply changes nothing.
"use strict";

const fs = require("fs");
const path = require("path");
const { readCSV, formatCSV } = require("./csv");

const ROOT = __dirname;
const COMBINED = path.join(ROOT, "CombinedLists.csv");
const RAID = path.join(ROOT, "RaidStats.csv");
const GAMES = path.join(ROOT, "Games.csv");
const REPORT = path.join(ROOT, "NudgeReport.csv");

// ---- tuning knobs -----------------------------------------------------------
const W_KILLS = 0.45; // composite weights: elite play = kills + damage
const W_DMG_RESID = 0.4;
const W_HEALS = 0.15;
const WINSOR_Z = 2.5; // cap one popped-off (or farmed) game
const RHO = 0.6; // how predictive a rating is of a single game's z
const TEAM_BETA = 0.25; // expected-z shift per point of team-strength asymmetry
// Per-map absolute baseline: within-game z is purely relative to the lobby,
// so a share of the observed score comes from comparing raw stats to the
// map's pooled profile across games (maps play consistently). Only active
// once a map has enough symmetric games to have a stable profile.
const W_MAP = 0.3; // blend weight of the map baseline vs the within-game z
const MIN_MAP_GAMES = 3;
const SIGMA_GAME = 6.0; // single-game noise, in OVR points (big = small nudges)
const LOBBY_SD_FLOOR = 3.0; // don't let a flat lobby explode the z->OVR scale
const MAX_MOVE_PER_GAME = 2.5; // OVR points; belt-and-suspenders outlier cap
// 97+ is the all-time-great tier ("X" in generate.js), assigned by hand
// only: stat nudges never lift a rating into it (ceiling at 96), and
// ratings already inside it are frozen completely. Below 97, nudges move
// freely in both directions.
const TIER_LOCK = 97;
// Hand exceptions from a_cemaster: stats never reduce these players'
// ratings (leadership value not visible in scoreboards). Boosts still apply.
const NO_DOWN = new Set(["Avaitron", "aspirrant"]);
// Game years are recorded in Games.csv for provenance but deliberately NOT
// modeled: a_cemaster's call (2026-08) - the 2024-2026 era gap is minor, so
// all games count equally regardless of age. Prior sigma still reflects how
// stale the player's newest list rating is.
function priorSigma(year) {
  if (year == null) return 7.0; // no prior at all: data decides
  if (year >= 2025) return 3.0;
  if (year >= 2023) return 4.0;
  return 5.5;
}
const NUDGE_YEAR = "2026";
const NUDGE_SOURCE = "Raid nudge";
const EXCLUDED_SOURCES = new Set(["Raid stats", NUDGE_SOURCE]);
// Unreadable/placeholder scoreboard rows: they still count toward each game's
// within-game statistics (they were real players in the lobby) but never get
// rated or written to CombinedLists.
const PLACEHOLDER = /^\(.*\)$/;
// -----------------------------------------------------------------------------

function mean(xs) {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}
function sd(xs) {
  const m = mean(xs);
  return Math.sqrt(mean(xs.map((x) => (x - m) * (x - m))));
}
function zScores(xs) {
  const m = mean(xs);
  const s = sd(xs) || 1;
  return xs.map((x) => (x - m) / s);
}
function clamp(x, lo, hi) {
  return Math.min(hi, Math.max(lo, x));
}

function loadPriors() {
  const rows = readCSV(fs, COMBINED);
  const header = rows[0];
  const col = Object.fromEntries(header.map((h, i) => [h, i]));
  // newest row per player, skipping raid-derived rows (double-count guard).
  // A "Raid nudge" row that absorbed another source's row carries that row's
  // original value in NudgeBase - that value is the recoverable prior; nudge
  // rows without a base (players first rated by the nudge) carry none.
  const best = new Map();
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const name = r[col.LegacyName];
    if (!name) continue;
    let ovr;
    if (r[col.Source] === NUDGE_SOURCE) {
      const m = /^(\d+(?:\.\d+)?)/.exec(r[col.NudgeBase] || "");
      if (!m) continue;
      ovr = parseFloat(m[1]);
    } else if (EXCLUDED_SOURCES.has(r[col.Source])) {
      continue;
    } else {
      ovr = parseFloat(r[col.OVR]);
    }
    const year = parseInt(r[col.Year], 10) || 0;
    if (!isFinite(ovr)) continue;
    const prev = best.get(name);
    if (!prev || year > prev.year) best.set(name, { ovr, year, row: r });
  }
  return { priors: best, rows, col };
}

function loadGames() {
  const rows = readCSV(fs, RAID);
  const header = rows[0];
  const col = Object.fromEntries(header.map((h, i) => [h, i]));
  const games = new Map();
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const id = r[col.Map];
    if (!id) continue;
    if (!games.has(id)) games.set(id, []);
    games.get(id).push({
      mode: r[col.Mode],
      team: r[col.Team],
      name: r[col.Canonical] || r[col.Handle],
      kills: parseFloat(r[col.Kills]) || 0,
      dmg: parseFloat(r[col.DMG]) || 0,
      heals: parseFloat(r[col.Heals]) || 0,
    });
  }
  // chronological: M1, M2, ... M10 (numeric part)
  return [...games.entries()].sort(
    (a, b) => parseInt(a[0].replace(/\D/g, ""), 10) - parseInt(b[0].replace(/\D/g, ""), 10)
  );
}

function loadGameMeta() {
  const rows = readCSV(fs, GAMES);
  const col = Object.fromEntries(rows[0].map((h, i) => [h, i]));
  const maps = new Map();
  const years = new Map();
  for (let i = 1; i < rows.length; i++) {
    const id = rows[i][col.GameId];
    if (!id) continue;
    if (rows[i][col.Map]) maps.set(id, rows[i][col.Map]);
    const y = parseInt(rows[i][col.Date], 10); // Date is a year or YYYY-MM-DD
    if (y) years.set(id, y);
  }
  return { maps, years };
}

// Pooled per-map stat profile from symmetric (RED/BLUE) games: the absolute
// yardstick that within-game z can't provide. Returns a scorer built on the
// same composite as observedZ (kills, dmg-beyond-kills, heals), standardized
// against the map's pooled distribution.
function buildMapBaselines(games, gameMaps) {
  const pools = new Map(); // map name -> { rows, gameCount }
  for (const [id, players] of games) {
    const map = gameMaps.get(id);
    if (!map) continue;
    if (players.some((p) => p.team !== "RED" && p.team !== "BLUE")) continue;
    if (!pools.has(map)) pools.set(map, { rows: [], gameCount: 0 });
    const pool = pools.get(map);
    pool.rows.push(...players);
    pool.gameCount++;
  }
  const scorers = new Map();
  for (const [map, pool] of pools) {
    if (pool.gameCount < MIN_MAP_GAMES) continue;
    const ks = pool.rows.map((p) => p.kills);
    const ds = pool.rows.map((p) => p.dmg);
    const hs = pool.rows.map((p) => p.heals);
    const mk = mean(ks);
    const md = mean(ds);
    let num = 0;
    let den = 0;
    for (let i = 0; i < ks.length; i++) {
      num += (ks[i] - mk) * (ds[i] - md);
      den += (ks[i] - mk) * (ks[i] - mk);
    }
    const slope = den > 0 ? num / den : 0;
    const resid = ds.map((d, i) => d - (md + slope * (ks[i] - mk)));
    const sk = sd(ks) || 1;
    const sr = sd(resid) || 1;
    const mh = mean(hs);
    const sh = sd(hs) || 1;
    const rawOf = (p) =>
      W_KILLS * ((p.kills - mk) / sk) +
      W_DMG_RESID * ((p.dmg - (md + slope * (p.kills - mk))) / sr) +
      W_HEALS * ((p.heals - mh) / sh);
    const raws = pool.rows.map(rawOf);
    const mRaw = mean(raws);
    const sRaw = sd(raws) || 1;
    scorers.set(map, (p) => (rawOf(p) - mRaw) / sRaw);
  }
  return scorers;
}

// Observed composite z for each player in one game. All standardization is
// within-game, so map/mode/lobby pace never leak across games.
function observedZ(players) {
  const kills = players.map((p) => p.kills);
  const dmg = players.map((p) => p.dmg);
  const heals = players.map((p) => p.heals);
  // per-game OLS dmg ~ kills; residual = damage volume not explained by frags
  const mk = mean(kills);
  const md = mean(dmg);
  let num = 0;
  let den = 0;
  for (let i = 0; i < kills.length; i++) {
    num += (kills[i] - mk) * (dmg[i] - md);
    den += (kills[i] - mk) * (kills[i] - mk);
  }
  const slope = den > 0 ? num / den : 0;
  const resid = dmg.map((d, i) => d - (md + slope * (kills[i] - mk)));

  const zk = zScores(kills);
  const zd = zScores(resid);
  const zh = zScores(heals);
  const raw = players.map((_, i) => W_KILLS * zk[i] + W_DMG_RESID * zd[i] + W_HEALS * zh[i]);
  // re-standardize the composite so it is a proper z, then winsorize
  return zScores(raw).map((z) => clamp(z, -WINSOR_Z, WINSOR_Z));
}

function main() {
  const apply = process.argv.includes("--apply");
  const { priors, rows: combinedRows, col } = loadPriors();
  const { maps: gameMaps } = loadGameMeta();
  const games = loadGames();
  const mapScorers = buildMapBaselines(games, gameMaps);

  // Default prior for players with no list history: median of the priors of
  // everyone who shows up in the raid games (deterministic, roster-anchored).
  const knownOvrs = [];
  for (const [, players] of games)
    for (const p of players) if (priors.has(p.name)) knownOvrs.push(priors.get(p.name).ovr);
  knownOvrs.sort((a, b) => a - b);
  const DEFAULT_PRIOR = knownOvrs[Math.floor(knownOvrs.length / 2)] || 84;

  // state: canonical -> { mean, var, games, sumSurprise, priorOvr, priorYear }
  const state = new Map();
  const getState = (name) => {
    if (!state.has(name)) {
      const p = priors.get(name);
      const sig = priorSigma(p ? p.year : null);
      state.set(name, {
        mean: p ? p.ovr : DEFAULT_PRIOR,
        var: sig * sig,
        games: 0,
        sumSurprise: 0,
        priorOvr: p ? p.ovr : null,
        priorYear: p ? p.year : null,
      });
    }
    return state.get(name);
  };

  for (const [gameId, players] of games) {
    // Asymmetric-faction games (e.g. 12 Astartes vs 8 Xenos) have
    // structurally different stat scales per side, so each faction is scored
    // on its own curve with its own expectation baseline and no cross-team
    // asymmetry term. Symmetric pickup lobbies use RED/BLUE team labels and
    // share one lobby-wide curve; named-faction labels signal asymmetry.
    const teams = [...new Set(players.map((p) => p.team))];
    const grouped = teams.length > 1 && teams.some((t) => t !== "RED" && t !== "BLUE");
    const groups = grouped
      ? teams.map((t) => players.filter((p) => p.team === t))
      : [players];

    // blend in the map's absolute baseline for symmetric games on maps with
    // an established profile (relative-to-lobby stays the dominant signal)
    const mapScore = !grouped ? mapScorers.get(gameMaps.get(gameId)) : null;

    for (const group of groups) {
      let zObs = observedZ(group);
      if (mapScore)
        zObs = zObs.map((z, i) =>
          clamp((1 - W_MAP) * z + W_MAP * mapScore(group[i]), -WINSOR_Z, WINSOR_Z)
        );

      // group expectation from CURRENT posterior means (sequential filter)
      const ratings = group.map((p) => getState(p.name).mean);
      const groupMean = mean(ratings);
      const groupSd = Math.max(sd(ratings), LOBBY_SD_FLOOR);
      const teamMean = {};
      for (const t of new Set(group.map((p) => p.team))) {
        teamMean[t] = mean(group.filter((p) => p.team === t).map((p) => getState(p.name).mean));
      }

      group.forEach((p, i) => {
        const s = getState(p.name);
        const opp = Object.keys(teamMean).find((t) => t !== p.team);
        const asym = opp != null ? (teamMean[p.team] - teamMean[opp]) / groupSd : 0;
        const zExp = (RHO * (s.mean - groupMean)) / groupSd + TEAM_BETA * asym;
        const surprise = zObs[i] - zExp; // in z units
        const K = s.var / (s.var + SIGMA_GAME * SIGMA_GAME);
        let move = clamp(K * surprise * groupSd, -MAX_MOVE_PER_GAME, MAX_MOVE_PER_GAME);
        if (s.priorOvr != null && s.priorOvr >= TIER_LOCK) {
          move = 0; // frozen inside the all-time-great tier
        } else {
          if (NO_DOWN.has(p.name) && move < 0) move = 0;
          move = Math.min(move, TIER_LOCK - 1 - s.mean); // ceiling: never nudged into 97+
        }
        s.mean += move;
        s.var *= 1 - K;
        s.games += 1;
        s.sumSurprise += surprise;
      });
    }
  }

  // ---- report ----
  const out = [...state.entries()]
    .filter(([name]) => !PLACEHOLDER.test(name))
    .map(([name, s]) => ({
      name,
      games: s.games,
      prior: s.priorOvr,
      priorYear: s.priorYear,
      post: Math.round(s.mean),
      delta: s.mean - (s.priorOvr != null ? s.priorOvr : DEFAULT_PRIOR),
      sigma: Math.sqrt(s.var),
      avgSurprise: s.sumSurprise / s.games,
    }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

  const reportRows = [
    ["Canonical", "Games", "PriorOVR", "PriorYear", "NewOVR", "Delta", "PosteriorSigma", "AvgSurpriseZ"],
    ...out.map((r) => [
      r.name,
      r.games,
      r.prior != null ? r.prior : `(none; default ${DEFAULT_PRIOR})`,
      r.priorYear != null ? r.priorYear : "",
      r.post,
      r.delta.toFixed(2),
      r.sigma.toFixed(2),
      r.avgSurprise.toFixed(2),
    ]),
  ];
  fs.writeFileSync(REPORT, formatCSV(reportRows));

  console.log(`${games.length} games, ${state.size} players (default prior ${DEFAULT_PRIOR})`);
  console.log("\nPlayer                 Games PriorOVR  NewOVR  Delta  Sigma");
  for (const r of out) {
    console.log(
      `${r.name.padEnd(22)} ${String(r.games).padStart(5)} ${String(r.prior != null ? r.prior : "-").padStart(8)} ${String(r.post).padStart(7)} ${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(1).padStart(5)} ${r.sigma.toFixed(1).padStart(6)}`
    );
  }
  console.log(`\nStaged only - CombinedLists.csv untouched. Full report: NudgeReport.csv`);
  console.log(`To write these into CombinedLists.csv: node nudge.js --apply`);

  if (!apply) return;

  // ---- upsert into CombinedLists.csv: exactly ONE row per player-year ----
  // The nudge takes over the player's existing 2026 row rather than adding a
  // duplicate. When it absorbs a row from another source, that row's original
  // value is banked once in the NudgeBase column, which loadPriors() reads
  // back as the pre-nudge prior - so repeated applies stay idempotent.
  const header = combinedRows[0];
  if (!header.includes("NudgeBase")) header.push("NudgeBase");
  const iBase = header.indexOf("NudgeBase");
  for (let i = 1; i < combinedRows.length; i++)
    while (combinedRows[i].length < header.length) combinedRows[i].push("");

  const byName2026 = new Map(); // name -> row indices with Year=2026
  for (let i = 1; i < combinedRows.length; i++) {
    const r = combinedRows[i];
    if (r[col.Year] !== NUDGE_YEAR) continue;
    if (!byName2026.has(r[col.LegacyName])) byName2026.set(r[col.LegacyName], []);
    byName2026.get(r[col.LegacyName]).push(i);
  }
  // newest row of any source, to copy Clan/Leader/Class/RCL metadata from
  const newestAny = new Map();
  for (let i = 1; i < combinedRows.length; i++) {
    const r = combinedRows[i];
    const y = parseInt(r[col.Year], 10) || 0;
    const prev = newestAny.get(r[col.LegacyName]);
    if (!prev || y > prev.y) newestAny.set(r[col.LegacyName], { y, r });
  }

  const META_COLS = ["Clan", "Leader", "Class Player", "Cheater", "RCL"];
  const drop = new Set();
  let updated = 0;
  let added = 0;
  let absorbed = 0;
  for (const r of out) {
    const idxs = byName2026.get(r.name) || [];
    // prefer the existing nudge row; otherwise take over the highest-OVR
    // row of the year (matches the historical dedup rule in ALIASES.md)
    let keep = idxs.find((i) => combinedRows[i][col.Source] === NUDGE_SOURCE);
    if (keep == null && idxs.length)
      keep = [...idxs].sort((a, b) => +combinedRows[b][col.OVR] - +combinedRows[a][col.OVR])[0];

    if (keep != null) {
      const row = combinedRows[keep];
      for (const i of idxs) {
        if (i === keep) continue;
        const o = combinedRows[i];
        if (!row[iBase] && o[col.Source] !== NUDGE_SOURCE)
          row[iBase] = `${o[col.OVR]} (${o[col.Source] || "unsourced"})`;
        for (const f of META_COLS) if (!row[col[f]] && o[col[f]]) row[col[f]] = o[col[f]];
        drop.add(i);
        absorbed++;
      }
      if (row[col.Source] !== NUDGE_SOURCE) {
        if (!row[iBase]) row[iBase] = `${row[col.OVR]} (${row[col.Source] || "unsourced"})`;
        row[col.Source] = NUDGE_SOURCE;
      }
      row[col.OVR] = String(r.post);
      updated++;
    } else {
      const meta = newestAny.get(r.name);
      const row = header.map(() => "");
      row[col.LegacyName] = r.name;
      row[col.OVR] = String(r.post);
      row[col.Year] = NUDGE_YEAR;
      row[col.Source] = NUDGE_SOURCE;
      if (meta) for (const f of META_COLS) row[col[f]] = meta.r[col[f]];
      combinedRows.push(row);
      added++;
    }
  }
  const finalRows = combinedRows.filter((_, i) => i === 0 || !drop.has(i));
  fs.writeFileSync(COMBINED, formatCSV(finalRows));
  console.log(
    `\nApplied: ${updated} year-rows updated (${absorbed} duplicate rows absorbed), ${added} added. Now run: node generate.js`
  );
}

main();
