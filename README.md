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
