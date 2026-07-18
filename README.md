# ClanDraft

Two self-contained static pages for browsing clan/player draft data.

- `index.html` - Clan Draft roster roller, plus the Gauntlet: a 30-day scrim/raid calendar simulated against your locked roster.
- `list.html` - Player rankings, sourced from `CombinedLists.csv`.

Both pages embed their data inline, so no build step or server-side code is required.

## Data generation

`CombinedLists.csv` lives in the repo root and is deployed with the site, so other tools can
fetch the source sheet directly. After editing it, run `node generate.js` to regenerate
the embedded `PLAYERS`/`ROWS` arrays in both pages, then commit the updated HTML. The CSV's
`Leader` column feeds the leadership classes (Elite/Experienced/Good/No Mic/Negative) used by
the Gauntlet; players without a Leader value lead as Raw +0.

## Roblox name history

`node check-roblox-names.js` checks every username in `CombinedLists.csv` against Roblox and prints
the ones carrying alternate handles - accounts with past usernames, and accounts since renamed away
from the name the CSV uses. It also flags when one player's alternate handle is another player's name
in the CSV, which usually means two sets of rows are the same person.

Results land in `RobloxNames.csv`, which doubles as the lookup cache: names already recorded there
are never re-fetched, so routine re-runs only hit the API for names added since the last run, and an
interrupted run resumes where it stopped. Pass `--refresh` to re-check everything, `--max-age 90` to
re-check entries older than 90 days, or `--offline` to re-print the flags with no API calls.

The two endpoints it calls are throttled so differently that each uses its own host. Name history
(one call per username) goes through [RoProxy](https://roproxy.com/), which sustains ~1 call per
10.8s where Roblox's own host manages ~1 per 2 minutes for the same traffic. The batch name-to-id
resolve goes to Roblox directly, because that endpoint is metered by usernames requested and
RoProxy's shared quota rejects 100-name batches outright. `--host <host>` forces a single host for
both.

Both limiters punish haste rather than queueing behind it, so the script paces itself and treats a
429 as a signal to back off rather than poll. The pacing is deliberately tuned: at 9s apart the
history calls sustain indefinitely, but at 6s the limiter stops handing out slots and real
throughput collapses by an order of magnitude. That puts a cold pass over the whole CSV at roughly
two hours, which is the reason results are cached rather than re-fetched - and why it saves progress
continuously and resumes where it left off. Set `DEBUG_HTTP=1` to trace every request and status.

Treat the output as leads, not conclusions, and record confirmed aliases by hand in `ALIASES.md`.

## Visit counts

Each page pings a free anonymous counter ([counterapi.dev](https://counterapi.dev)) on load.
Check the totals here:

- index: <https://api.counterapi.dev/v1/clandraft-buildteam/index/>
- list: <https://api.counterapi.dev/v1/clandraft-buildteam/list/>

The `count` field in the JSON response is the number of visits.

## Deploy on Render

This repo includes a `render.yaml` blueprint for a static site with no build command, publishing the repo root.

1. On [Render](https://dashboard.render.com/), choose **New > Blueprint** and point it at this repo, or
2. Choose **New > Static Site**, set the build command to empty, and the publish directory to `.`.
