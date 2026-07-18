#!/usr/bin/env node
// Checks every username in CombinedLists.csv against Roblox's user API and reports
// the ones that carry alternate handles: accounts whose past usernames Roblox still
// remembers, and accounts that have since been renamed away from the name the CSV
// uses. Results are stored in RobloxNames.csv, which doubles as the lookup cache -
// a name already recorded there is never re-fetched, so re-runs only hit the API for
// names added to CombinedLists.csv since the last run.
//
//   node check-roblox-names.js               # fetch what's missing, print flags
//   node check-roblox-names.js --refresh     # re-fetch every name
//   node check-roblox-names.js --max-age 90  # re-fetch entries older than 90 days
//   node check-roblox-names.js --offline     # print flags from the cache, no API calls
//   node check-roblox-names.js --host users.roblox.com   # force one host for everything
//   DEBUG_HTTP=1 node check-roblox-names.js  # trace every request and status
//
// The two endpoints are throttled so differently that they are handled separately:
//
//   - the batch name->id resolve goes to Roblox directly. It is metered by usernames
//     requested rather than by request, and RoProxy's shared quota rejects 100-name
//     batches outright, while Roblox itself answers them instantly.
//   - username-history is one call per name and is the slow part, so it is fanned across
//     several hosts at once (`historyHosts`) - each rate-limited independently, so they
//     act as parallel lanes. RoProxy sustains ~1 call per 10.8s per lane.
//
// The limiters punish haste rather than queueing behind it - see `delayMs` - so each
// lane paces itself and treats a 429 as a signal to back off. A cold pass over the whole
// CSV still takes on the order of an hour, which is the reason results are cached.
"use strict";

const fs = require("fs");
const path = require("path");
const { readCSV, formatCSV } = require("./csv");

const ROOT = __dirname;
const CSV_PATH = path.join(ROOT, "CombinedLists.csv");
const CACHE_PATH = path.join(ROOT, "RobloxNames.csv");

const USERS_API = (host) => `https://${host}/v1/usernames/users`;
const HISTORY_API = (host, id) => `https://${host}/v1/users/${id}/username-history?limit=100`;

const CACHE_HEADER = ["LegacyName", "RobloxId", "CurrentName", "PastNames", "Status", "CheckedAt"];
const PAST_NAME_SEP = " | ";
const REQUEST_TIMEOUT_MS = 15000;

// Status values written to the cache's Status column.
const NOT_FOUND = "notfound"; // Roblox does not resolve the name at all
const RENAMED = "renamed"; // resolves, but the account goes by a different name now
const CURRENT = "current"; // resolves, and the CSV uses the account's current name

const opts = parseArgs(process.argv.slice(2));

function parseArgs(argv) {
  const o = {
    refresh: false,
    offline: false,
    maxAgeDays: Infinity,
    limit: Infinity,
    resolveHost: "users.roblox.com",
    // History lookups fan out across these hosts concurrently, one worker each. The
    // rate limit is keyed per host to our request stream, so two hosts are two
    // independent lanes and roughly double throughput; each worker paces itself, so a
    // slower host simply takes fewer names. RoProxy carries the bulk; Roblox's own host
    // is slower but its budget is entirely separate, so it is pure additional capacity.
    historyHosts: ["users.roproxy.com", "users.roblox.com"],
    // Floor and ceiling for the adaptive per-host pacing (see `makePace`). 9s is the
    // fastest RoProxy has been observed to sustain; going faster does not just waste
    // requests, it suppresses the limiter and collapses real throughput by an order of
    // magnitude.
    delayMs: 9000,
    maxDelayMs: 120000,
    historyAttempts: 15,
    // A resolve 429 means "this window's username quota is spent", which needs ~30s of
    // quiet to refill - same lesson, longer timescale.
    resolveRetry: { retryMs: 30000, attempts: 10 },
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--refresh") o.refresh = true;
    else if (a === "--offline") o.offline = true;
    else if (a === "--max-age") o.maxAgeDays = Number(argv[++i]);
    else if (a === "--delay") o.delayMs = Number(argv[++i]);
    else if (a === "--limit") o.limit = Number(argv[++i]);
    else if (a === "--host") { o.resolveHost = argv[++i]; o.historyHosts = [o.resolveHost]; }
    else throw new Error(`unknown argument: ${a}`);
  }
  return o;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const key = (name) => name.trim().toLowerCase();

// How fast a history host lets us go is not a constant to be looked up once: the budget
// depends on recent traffic from this IP (RoProxy's is shared with its other users), so
// an interval that sustains indefinitely one hour crawls the next, and a burst of
// successes says nothing about the sustained rate. Rather than hard-code a guess, ease
// the interval down while calls land and back off hard on a 429, which settles wherever
// the host is actually willing to serve. Each host gets its own pace - they throttle
// independently, so one lane backing off must not slow the other.
function makePace() {
  return {
    ms: opts.delayMs,
    ok() {
      this.ms = Math.max(opts.delayMs, Math.round(this.ms * 0.9));
    },
    limited() {
      this.ms = Math.min(opts.maxDelayMs, Math.round(this.ms * 1.5));
    },
  };
}

// Unique usernames from CombinedLists.csv. The CSV carries one row per player per
// year, so the same name shows up several times; only distinct names get looked up.
function loadLegacyNames() {
  const [header, ...data] = readCSV(fs, CSV_PATH);
  // The name column was renamed Name -> LegacyName at some point; accept both.
  const nameIdx = header.indexOf("Name") !== -1 ? header.indexOf("Name") : header.indexOf("LegacyName");
  if (nameIdx === -1) throw new Error(`no Name or LegacyName column in ${path.basename(CSV_PATH)}`);
  const seen = new Map();
  for (const row of data) {
    const name = (row[nameIdx] || "").trim();
    if (name && !seen.has(key(name))) seen.set(key(name), name);
  }
  return [...seen.values()];
}

function loadCache() {
  const cache = new Map();
  if (!fs.existsSync(CACHE_PATH)) return cache;
  const [header, ...data] = readCSV(fs, CACHE_PATH);
  const idx = Object.fromEntries(CACHE_HEADER.map((h) => [h, header.indexOf(h)]));
  for (const row of data) {
    const legacyName = (row[idx.LegacyName] || "").trim();
    if (!legacyName) continue;
    const pastNames = (row[idx.PastNames] || "").split(PAST_NAME_SEP).map((s) => s.trim()).filter(Boolean);
    cache.set(key(legacyName), {
      legacyName,
      id: row[idx.RobloxId] ? Number(row[idx.RobloxId]) : null,
      currentName: row[idx.CurrentName] || "",
      pastNames,
      status: row[idx.Status] || "",
      checkedAt: row[idx.CheckedAt] || "",
    });
  }
  return cache;
}

function saveCache(cache) {
  const rows = [...cache.values()]
    .sort((a, b) => a.legacyName.localeCompare(b.legacyName))
    .map((e) => [
      e.legacyName,
      e.id == null ? "" : String(e.id),
      e.currentName,
      e.pastNames.join(PAST_NAME_SEP),
      e.status,
      e.checkedAt,
    ]);
  fs.writeFileSync(CACHE_PATH, formatCSV([CACHE_HEADER, ...rows]));
}

function isStale(entry) {
  if (opts.refresh) return true;
  if (!entry.checkedAt) return true;
  if (opts.maxAgeDays === Infinity) return false;
  const ageDays = (Date.now() - Date.parse(entry.checkedAt)) / 86400000;
  return !(ageDays < opts.maxAgeDays);
}

// Neither endpoint sends Retry-After, and they want opposite retry strategies, so the
// caller passes its own: `retryMs` between attempts, `attempts` before giving up.
// Requests get an explicit timeout because a call that stalls otherwise hangs the whole
// run indefinitely, which looks identical to slow progress.
async function getJSON(url, { init, retryMs, attempts, pace, label }) {
  const adaptive = !!pace;
  let lastError = null;
  // One call's retries are one congestion event, not N of them: widening the interval
  // per attempt would race to the ceiling on a single stubborn name and leave every
  // later name paying for it, since a success only eases back a notch.
  let backedOff = false;
  for (let attempt = 0; attempt < attempts; attempt++) {
    const waitMs = () => (adaptive ? pace.ms : retryMs);
    let res;
    const t0 = Date.now();
    if (process.env.DEBUG_HTTP) console.error(`    -> attempt ${attempt + 1} ${url}`);
    try {
      res = await fetch(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
      if (process.env.DEBUG_HTTP) console.error(`    <- ${res.status} in ${Date.now() - t0}ms`);
    } catch (err) {
      if (process.env.DEBUG_HTTP) console.error(`    !! ${err.name} in ${Date.now() - t0}ms`);
      // Timeout or connection error: both are worth retrying, the host is flaky.
      lastError = err;
      await sleep(waitMs());
      continue;
    }
    if (res.status === 429) {
      // The body of a response we don't parse still has to be released, or its
      // connection stays checked out of the pool and later requests wedge behind it.
      // Retries make that failure mode easy to hit and hard to read: throughput decays
      // to a standstill while the host itself is answering fine.
      await res.body?.cancel();
      lastError = null;
      if (adaptive && !backedOff) {
        pace.limited();
        backedOff = true;
      }
      // Long waits are announced: a silent multi-minute pause is indistinguishable
      // from a hang, which cost real debugging time while building this.
      if (waitMs() >= 10000) console.log(`  [${label || url}] rate limited, backing off to ${Math.round(waitMs() / 1000)}s...`);
      await sleep(waitMs());
      continue;
    }
    if (res.status === 400 || res.status === 404) {
      await res.body?.cancel();
      return null;
    }
    if (!res.ok) {
      await res.body?.cancel();
      throw new Error(`${res.status} ${res.statusText} for ${url}`);
    }
    if (adaptive) pace.ok();
    return res.json();
  }
  throw new Error(
    `gave up on ${url} after ${attempts} attempts` +
      (lastError ? `: ${lastError.message}` : " (rate limited throughout)")
  );
}

// Resolves one batch of names to accounts. Roblox matches past usernames here too, so
// a name the CSV still uses can come back pointing at a renamed account - that is
// exactly the case worth flagging, and `requestedUsername` is what reveals it.
async function resolveBatch(batch) {
  const body = await getJSON(USERS_API(opts.resolveHost), {
    ...opts.resolveRetry,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usernames: batch, excludeBannedUsers: false }),
    },
  });
  const resolved = new Map();
  // Unresolvable names are omitted from the response rather than returned as null.
  for (const u of (body && body.data) || []) resolved.set(key(u.requestedUsername), u);
  return resolved;
}

// Roblox returns the raw rename log, so a player who cycles away from a handle and
// back lists it once per cycle (one account logs 80 entries for 30-odd handles).
// What's wanted here is the set of handles the player has answered to, so the log is
// deduped and the name they go by now is dropped - leaving only the alternates.
async function fetchPastNames(id, currentName, host, pace) {
  const body = await getJSON(HISTORY_API(host, id), {
    attempts: opts.historyAttempts,
    pace,
    label: host,
  });
  const names = ((body && body.data) || []).map((h) => h.name);
  const seen = new Set([key(currentName)]);
  const alternates = [];
  for (const n of names) {
    if (seen.has(key(n))) continue;
    seen.add(key(n));
    alternates.push(n);
  }
  return alternates;
}

function flagLine(e) {
  const parts = [];
  if (e.status === RENAMED) parts.push(`now "${e.currentName}"`);
  if (e.pastNames.length) parts.push(`past: ${e.pastNames.join(", ")}`);
  return `FLAG  ${e.legacyName.padEnd(24)} ${parts.join("  |  ")}`;
}

// A player's alternate handle turning up as another CombinedLists.csv name means the
// two rows are one person - the case ALIASES.md exists to reconcile - so call it out
// separately from the ordinary rename flags.
function collisions(entries, legacyNames) {
  const byName = new Map(legacyNames.map((n) => [key(n), n]));
  const found = new Map();
  for (const e of entries) {
    for (const alt of [e.currentName, ...e.pastNames]) {
      if (!alt || key(alt) === key(e.legacyName)) continue;
      const other = byName.get(key(alt));
      if (!other) continue;
      // Two players who have traded handles each name the other, so key the pair on
      // both names to report it once rather than once per direction.
      const pair = [key(e.legacyName), key(other)].sort().join(" ");
      if (!found.has(pair)) found.set(pair, { legacyName: e.legacyName, other, alt });
    }
  }
  return [...found.values()];
}

async function main() {
  const legacyNames = loadLegacyNames();
  const cache = loadCache();

  const stale = legacyNames.filter((n) => !cache.has(key(n)) || isStale(cache.get(key(n))));
  const todo = stale.slice(0, opts.limit);
  console.log(
    `${legacyNames.length} unique usernames in CombinedLists.csv: ` +
      `${legacyNames.length - stale.length} already cached, ${todo.length} to look up.`
  );

  if (todo.length && !opts.offline) {
    // Phase 1 - resolve names to accounts in batches of 100. Fast when it works (the
    // whole todo list is a handful of calls); names that don't resolve are cached as
    // NOT_FOUND right here so they are never retried.
    const pending = []; // { legacyName, user } awaiting a history lookup
    for (let i = 0; i < todo.length; i += 100) {
      const batch = todo.slice(i, i + 100);
      const resolved = await resolveBatch(batch);
      for (const legacyName of batch) {
        const user = resolved.get(key(legacyName));
        if (user) {
          pending.push({ legacyName, user });
        } else {
          cache.set(key(legacyName), {
            legacyName, id: null, currentName: "", pastNames: [],
            status: NOT_FOUND, checkedAt: new Date().toISOString(),
          });
          saveCache(cache);
        }
      }
      console.log(`resolved ${Math.min(i + 100, todo.length)}/${todo.length} names to accounts`);
    }

    // Phase 2 - fetch rename history, the slow part, fanned across the history hosts.
    // One worker per host pulls from a shared index, so a faster host takes more names
    // and a host that stalls simply contributes fewer. Writes stay safe because a
    // worker only yields at `await`: cache.set + saveCache run to completion between
    // them, so concurrent workers never interleave a half-written cache.
    let taken = 0;
    let done = 0;
    const total = pending.length;
    async function worker(host) {
      const pace = makePace();
      while (taken < total) {
        const { legacyName, user } = pending[taken++];
        let pastNames;
        try {
          pastNames = await fetchPastNames(user.id, user.name, host, pace);
        } catch (err) {
          // One name that runs out of retries must not kill a run of hundreds. Leave
          // it uncached and carry on; the next run picks up whatever was skipped.
          console.log(`  ${legacyName} - skipped, will retry next run (${err.message})`);
          continue;
        }
        cache.set(key(legacyName), {
          legacyName,
          id: user.id,
          currentName: user.name,
          pastNames,
          status: key(user.name) === key(legacyName) ? CURRENT : RENAMED,
          checkedAt: new Date().toISOString(),
        });
        // Written as we go: a cold run is long, and an interrupted one should resume.
        saveCache(cache);
        done++;
        console.log(`  [${done}/${total}] ${legacyName} -> ${user.name}${pastNames.length ? ` (${pastNames.length} past)` : ""} (${host.split(".")[1]})`);
        await sleep(pace.ms);
      }
    }
    await Promise.all(opts.historyHosts.map(worker));
  }

  const entries = legacyNames.map((n) => cache.get(key(n))).filter(Boolean);
  const flagged = entries.filter((e) => e.status === RENAMED || e.pastNames.length);

  console.log(`\n=== ${flagged.length} of ${entries.length} usernames have alternate handles ===`);
  for (const e of flagged.sort((a, b) => a.legacyName.localeCompare(b.legacyName))) console.log(flagLine(e));

  const hits = collisions(entries, legacyNames);
  if (hits.length) {
    console.log(`\n=== ${hits.length} alternate handles collide with another CombinedLists.csv name (same person, two identities?) ===`);
    for (const h of hits) console.log(`SAME? ${h.legacyName} and ${h.other} (via "${h.alt}") - reconcile in ALIASES.md`);
  }

  const missing = entries.filter((e) => e.status === NOT_FOUND);
  if (missing.length) {
    console.log(`\n${missing.length} usernames do not resolve on Roblox (deleted, banned, or a nickname the CSV made up):`);
    console.log(missing.map((e) => e.legacyName).join(", "));
  }
  console.log(`\nStored in ${path.basename(CACHE_PATH)}.`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
