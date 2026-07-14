---
name: verify
description: How to run and drive this repo's static pages for verification
---

# Verifying BuildTeam pages

Both pages are self-contained static HTML - no build step, no server.
Open them directly with `file:///e:/GitHub/BuildTeam/index.html` (or `list.html`) in a browser.

## Driving with Playwright

Use `playwright-core` with the system Chrome (`chromium.launch({ channel: "chrome" })`); no bundled browser download needed.

The draft game script in index.html is NOT wrapped in an IIFE, so all state and functions are page globals reachable from `page.evaluate`: `PLAYERS`, `slots`, `roll`, `rerollsLeft`, `blindMode`, `render()`, `newRun()`, `lockedNames()`, etc.

To force a deterministic hand instead of clicking Roll:

```js
await page.evaluate(() => {
  roll = [/* pick entries from PLAYERS by tier/name */];
  render();
});
await page.click('.card[data-pick="0"]');
```

## Gotchas

- Rare picks (S, S+, X) hold the roll on screen ~230-280ms for the selection animation before the slot locks; wait before asserting `slots`.
- Blind mode masks tiers: set `blindMode = true; render()` in evaluate (persisted key is `clanDraftBlindMode` in localStorage).
- `generate.js` only regenerates the embedded `PLAYERS`/`ROWS` arrays from CombinedLists.csv; all other HTML/CSS/JS is hand-edited.
