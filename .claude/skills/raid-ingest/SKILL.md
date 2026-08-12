---
name: raid-ingest
description: Ingest a Roblox raid/clan-match scoreboard screenshot - transcribe it, verify with checksums, resolve handles to canonical names, record provenance, and nudge OVRs. Use whenever a_cemaster posts a match scoreboard screenshot or asks to add a raid game.
---

# Raid scoreboard ingestion

Turns a scoreboard screenshot into RaidStats.csv rows and nudged OVRs.
Data files: `RaidStats.csv` (per-game stats), `Games.csv` (provenance),
`CombinedLists.csv` (ratings), `ALIASES.md` (identity decisions).

## 1. Transcribe and checksum

Read the screenshot into two team tables: Team (RED/BLUE), Handle, Kills,
DMG, Heals, Caps. The scoreboard header shows each team's totals (e.g.
"RED [10] / 432 kills / 92600 DMG / 45084 heals / 44 caps").

**Checksum: the sum of each column over a team's rows MUST equal the header
totals.** If any column mismatches, re-read those cells (watch 3/8, 1/7, 0/O
confusions). Then show a_cemaster the full transcription with per-team checksum
status (PASS/FAIL per column) — **image reads always require his
verification before anything is written** (obscured rows, look-alike
glyphs). Use the literal handle `(obscured)` for a row whose name is
unreadable; keep its stats so the game's totals stay complete.

Ask a_cemaster (if not stated): actual map name, event/opponent description,
date, and which side is which clan.

**The match YEAR is a hard requirement — question it if not given.** The
nudge measures every player against their latest prior and writes
current-era (2026) rows, so it silently presumes the game is recent. A
scoreboard from an earlier era must not nudge today's ratings (a player's
2023 performance says little about their 2026 form) — flag it to
a_cemaster and record the game with its real year in Games.csv without
nudging until he decides how to score it.

**Late joins:** players who joined partway poison within-game z-scores
(there is no time-played column). If a row's stats look like a partial game
or a_cemaster says someone joined late, drop the row entirely (precedent:
Asteyrius, awespell in M7).

## 2. Resolve handles

```
node resolve-handles.js <handle1> <handle2> ...
```

- `MATCH` — use the canonical name.
- `CANDIDATE` / `UNKNOWN` — **by default, refresh Roblox rename history for
  these handles to reach a match** (a small name list stays under the rate
  limit; ~10s per name):

  ```
  node check-roblox-names.js --names <handle1>,<candidate1>,...
  ```

  Include both the unresolved handles AND their candidate canonicals — a
  candidate is confirmed when the canonical's account now carries the
  scoreboard handle as its current/past name. Then re-run resolve-handles.
- Canonical names: **presume CombinedLists.csv already holds the name we
  refer to a player by** — a scoreboard handle resolving to an existing
  identity always maps onto that identity, never the other way. If the
  refreshed history reveals a rename claim is actually a DIFFERENT account
  (alt), record it as an alt-account alias, noting both account ids.
- Record every confirmed decision in `ALIASES.md` (renames in the merges
  table, alt accounts in the alias table). Still-unresolved handles: ask
  a_cemaster; a handle with no trace anywhere is a new player and keeps its own
  name as canonical.

## 3. Append the game

- Game ID = next `M<n>` after the highest in RaidStats.csv.
- Append rows to `RaidStats.csv`: `Map(=game id),Mode,Team,Handle,Canonical,Kills,Deaths(empty),DMG,Heals,Caps`.
- Provenance: if a_cemaster can provide the image file path, run
  `powershell -File compress-screenshot.ps1 -In <path> -GameId <id>` — it
  stores a small JPEG in `Screenshots/` and prints the original's SHA-256.
  **If that SHA-256 already appears in Games.csv, this screenshot was
  already ingested — stop and tell a_cemaster.** Append the `Games.csv` row
  (date, event, teams, map, mode, screenshot path, sha256, who provided it).
  If no file path is available, still fill the row and leave
  Screenshot/Sha256 blank.

## 4. Nudge — stage only, do NOT apply by default

```
node nudge.js            # report only; writes NudgeReport.csv
```

Show a_cemaster the top movers (players from THIS game especially) and stop
there. **Never run `--apply` as part of ingestion** — transcription or
identity mistakes may still be latent, so nudges stay staged in
NudgeReport.csv until a_cemaster explicitly asks to apply (e.g. "apply the
nudges"). Staging loses nothing: nudge.js recomputes from all of
RaidStats.csv every run, so the pending nudges are always reproducible and
later corrections to the data automatically flow into the next report.

Commit the ingested data (RaidStats.csv, Games.csv, Screenshots/,
ALIASES.md if changed) when a_cemaster asks — CombinedLists.csv stays untouched.

Only when a_cemaster explicitly flags it:

```
node nudge.js --apply    # upserts Year=2026 "Raid nudge" rows
node generate.js         # regenerate index.html / list.html
```

then commit CombinedLists.csv together with the regenerated HTML.

Notes on the model (knobs at the top of nudge.js): ratings update on
*surprise* — observed within-game z minus the z expected from the lobby's
prior ratings — so being last in a stacked lobby you were expected to be
last in is not a negative signal. 97+ is the hand-assigned all-time-great
tier: nudges never lift anyone into it (ceiling 96) and ratings already
there are frozen; below 97 nudges move freely in both directions. Priors exclude rows sourced
"Raid stats" / "Raid nudge" and every run recomputes from all games, so
re-running or re-applying is always safe.
