# ClanDraft

Two self-contained static pages for browsing clan/player draft data.

- `index.html` - Clan Draft roster roller, plus the Gauntlet: a 30-day scrim/raid calendar simulated against your locked roster.
- `list.html` - Player rankings, sourced from `CombinedLists.csv`.
- `ratings.html` - Raid ratings computed from scoreboard data alone (`raids.sqlite`; regenerate with `python -I raid_ratings_page.py`), with player profiles and a board scanner.

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

## Board scanner

The "Scan a board" tab in `ratings.html` sends a screenshot to a small proxy (`scan-proxy/server.js`) that holds the
Anthropic API key and asks Claude for the printed rows; the page then resolves names and looks up ratings and
projections deterministically. A read name is snapped to the nearest handle the database has seen on a board, under an
edit distance that treats look-alike glyphs (I/l/1, O/0, S/5, B/8, Z/2) as nearly free and similar shapes as half an
edit, so one or two misread characters do not turn a regular into an unrated player; the row shows how the name was
matched (look-alike, regular, prefix, nearest). The same code lives in the bot as `agentic/namematch.py`.

On Docks and Skydock the two sides are different populations (Skydock defenders average about 0.4 z below the global
mean, attackers about 0.15 below), so a scan rates each player from their record in that role when they have one
(shrunk toward that side's average; `n_da`/`z_da`/`ovr_da` and friends in the rows), else on the map, else overall, and
an unknown player counts as that side's average rather than the global one. The win and score models are fitted on the
same definition. The key never reaches the browser. The proxy is the second service in `render.yaml`
(`clandraft-scan`); set `ANTHROPIC_API_KEY` for it in the Render dashboard. It caps reads per address per hour.
To run it locally for a page opened from disk:

    ANTHROPIC_API_KEY=... node scan-proxy/server.js      # listens on 8787; the page tries it after the Render URL

`raid_ratings_page.py` also writes `predict_data.json`: the scan tab's inputs (per-era player rows, the handle-to-name
map, per-map baselines, the fitted outcome models) for consumers outside the page. The Avian Discord bot's `!predict`
command (`agentic/predict.py` in that project) is a port of the scan tab over this file, so the two give the same
numbers; after a rebuild the bot picks the new file up by itself (it is re-read when its mtime changes). `!predictfull`
adds a one-standard-deviation error bar to every number (the fitted models' coefficient covariances and residual spread
are exported for that). To fix a misread, reply to either result with the same command and the fix in your own words
(`!predict STIBS2900 is STIPS2000`, `!predict remove the last avian`, `!predict add Kuurb to team 2`, `!predict look at
the 4th imperialist again`): the model gets the note, the earlier read and the original screenshot, edits the read, and
the game is re-projected with a `corrected:` footer listing what changed. `!predict docks` in reply re-projects the
same board on another map, and `!predictfull` in reply adds the error bars without a new read. `!ovr` with a
screenshot (or `!ovr name1 name2 ...`) skips the projection and lists each player's overall OVR, games and clan with a
mean per team; it takes the same reply corrections, and `!predict` in reply to an `!ovr` result projects that board.

## Visit counts

Each page pings a free anonymous hit counter ([hits.sh](https://hits.sh), no account) on load, keyed by the
deployed host and page name. Open the stats page to read the totals:

- index: <https://hits.sh/clandraft.onrender.com/index/>
- list: <https://hits.sh/clandraft.onrender.com/list/>
- ratings: <https://hits.sh/clandraft.onrender.com/ratings/>

The badge form (`.svg` instead of the trailing `/`) shows the number inline and accepts `?view=today-total`.
Counts are per page load. The previous counter (counterapi.dev v1) was shut down with HTTP 410 in October 2026
and its v2 requires an account and an API key on every request, so the earlier totals were not carried over.

## Deploy on Render

This repo includes a `render.yaml` blueprint for a static site with no build command, publishing the repo root.

1. On [Render](https://dashboard.render.com/), choose **New > Blueprint** and point it at this repo, or
2. Choose **New > Static Site**, set the build command to empty, and the publish directory to `.`.

## STATS ELO tab (index.html)

The STATS ELO tab on index.html shows the data-only rating (raid_score.py over raids.sqlite, the same numbers as
ratings.html) plus an event counter, without the screenshot reader. Its data lives in two marked blocks in index.html
(`var STATS_ELO = ...; /* /STATS_ELO */` and `var STATS_META = ...; /* /STATS_META */`) that `python raid_ratings_page.py`
rewrites whenever it rebuilds ratings.html; generate.js only rewrites PLAYERS / ROWS and leaves these blocks alone.
Events count every board a player stands on in the era, scored or not, by type (Defense, Raid, Scrimmage, Defense
Training, other); W-L is their record on two-sided boards that carry both scores. Profiles, boards and the scan tool
stay on ratings.html.
