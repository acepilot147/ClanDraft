# ClanDraft

Two self-contained static pages for browsing clan/player draft data.

- `index.html` - Clan Draft roster roller.
- `list.html` - Player rankings, sourced from `CombinedLists.csv`.

Both pages embed their data inline, so no build step or server-side code is required.

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
