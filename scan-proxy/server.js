#!/usr/bin/env node
// Board-scan proxy for ratings.html: holds the Anthropic API key server-side so the public page never sees it.
//
//   ANTHROPIC_API_KEY=... node scan-proxy/server.js        (PORT defaults to 8787)
//
// POST /read  {"image": "<base64>", "media_type": "image/png"}  ->  {"board": {teams: [{side, label, role, players: [{handle}]}]}, "usage", "model"}
// GET  /health                                                 ->  {"ok": true}
//
// The page sends the screenshot (already downscaled to <=1568px), this service asks Claude for the printed names and
// sides only (no statistics) with a strict JSON schema, and returns the parsed board. Everything after that (name resolution, OVR lookup,
// projections) is deterministic and happens in the page. No dependencies: Node 18+ built-in fetch and http.
"use strict";

const http = require("http");

const KEY = process.env.ANTHROPIC_API_KEY;
const PORT = Number(process.env.PORT || 8787);
const MODEL = process.env.SCAN_MODEL || "claude-opus-5-5";
const MAX_BODY = 8 * 1024 * 1024;          // bytes of JSON; a 1568px PNG is ~1-2 MB base64
const RATE = { perHour: Number(process.env.SCAN_RATE_PER_HOUR || 40) };
const ALLOWED_MEDIA = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

if (!KEY) {
  console.error("ANTHROPIC_API_KEY is not set");
  process.exit(1);
}

const SYSTEM = "You read scoreboards and team lists from Roblox clan-war screenshots (Warehouse, Docks Fairzone, Ordana Foundry). " +
  "Return every printed player name for both team panels in printed order - names only, no statistics. Copy handles exactly as rendered (if a glyph could be capital I or lowercase l, write it as the font renders it; " +
  "leave out a name you cannot read at all - never a placeholder such as (obscured)). role: defender for the VAKTOVIAN EMPIRE / base-owning side on Docks, attacker for RAIDERS, neutral for RED/BLUE or Astartes/Xenos boards. " +
  "board_present=false and teams=[] if the image shows no team list at all.";

const SCHEMA = {
  type: "object", additionalProperties: false, required: ["board_present", "teams"],
  properties: {
    board_present: { type: "boolean" },
    teams: { type: "array", items: { type: "object", additionalProperties: false, required: ["side", "label", "role", "players"], properties: {
      side: { type: "string", enum: ["left", "right"] }, label: { type: "string" }, role: { type: "string", enum: ["defender", "attacker", "neutral", "unknown"] },
      players: { type: "array", items: { type: "object", additionalProperties: false, required: ["handle"], properties: {
        handle: { type: "string" } } } } } } } },
};

const hits = new Map(); // ip -> [timestamps]
function limited(ip) {
  const now = Date.now(), keep = (hits.get(ip) || []).filter((t) => now - t < 3600e3);
  hits.set(ip, keep);
  if (keep.length >= RATE.perHour) return true;
  keep.push(now);
  return false;
}

function send(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "POST, GET, OPTIONS",
    "access-control-allow-headers": "content-type",
    "cache-control": "no-store",
  });
  res.end(JSON.stringify(body));
}

async function readBoard(image, mediaType) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({
      model: MODEL, max_tokens: 4000, system: SYSTEM,
      output_config: { format: { type: "json_schema", schema: SCHEMA }, effort: "medium" },
      messages: [{ role: "user", content: [
        { type: "image", source: { type: "base64", media_type: mediaType, data: image } },
        { type: "text", text: "Transcribe this scoreboard." },
      ] }],
    }),
  });
  const body = await r.json();
  if (!r.ok) throw Object.assign(new Error((body.error && body.error.message) || ("API " + r.status)), { status: 502 });
  if (body.stop_reason === "refusal") throw Object.assign(new Error("The model declined to read this image."), { status: 422 });
  const text = (body.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
  return { board: JSON.parse(text), usage: body.usage || {}, model: body.model || MODEL };
}

http.createServer((req, res) => {
  if (req.method === "OPTIONS") return send(res, 204, {});
  if (req.method === "GET" && req.url === "/health") return send(res, 200, { ok: true, model: MODEL });
  if (req.method !== "POST" || req.url !== "/read") return send(res, 404, { error: "not found" });
  const ip = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();
  if (limited(ip)) return send(res, 429, { error: "Too many reads from this address; try again in an hour." });
  let size = 0; const chunks = [];
  req.on("data", (c) => { size += c.length; if (size > MAX_BODY) { send(res, 413, { error: "image too large" }); req.destroy(); } else chunks.push(c); });
  req.on("end", async () => {
    if (res.writableEnded) return;
    let body;
    try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch (e) { return send(res, 400, { error: "invalid JSON" }); }
    if (!body || typeof body.image !== "string" || !ALLOWED_MEDIA.has(body.media_type)) return send(res, 400, { error: "expected {image: base64, media_type: image/png|jpeg|webp|gif}" });
    const t0 = Date.now();
    try {
      const out = await readBoard(body.image, body.media_type);
      console.log(new Date().toISOString(), ip, "ok", Date.now() - t0 + "ms", "in=" + out.usage.input_tokens, "out=" + out.usage.output_tokens);
      send(res, 200, out);
    } catch (e) {
      console.log(new Date().toISOString(), ip, "error", e.message);
      send(res, e.status || 500, { error: e.message });
    }
  });
}).listen(PORT, () => console.log("scan proxy listening on " + PORT + " (model " + MODEL + ")"));
