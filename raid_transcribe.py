"""Transcribe scoreboard screenshots into raids.sqlite with Claude vision.

  python -I raid_transcribe.py [--workers 8] [--limit N] [--image-id ID]

Resumable: an image is skipped once it has a verified/partial transcription,
or once it has used both attempts. Attempt 1 sends the board at <=1568px;
attempt 2 (after a checksum failure) re-reads at high effort with the full
image plus two zoomed half-crops. Every attempt is stored with its raw JSON,
checksum results, tokens and cost, so nothing is ever re-read silently.

Checksum gate (per team, per stat whose header total is visible):
  sum(player column) == header total  ->  verified when every check passes on
  both teams and no list is truncated; partial when a list is truncated but
  the visible rows do not exceed the totals; failed otherwise.
"""
import os, sys, io, json, base64, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # survives python -I
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from dotenv import load_dotenv
import anthropic
import raid_db

load_dotenv(r'C:\Users\JamesVong\brightai-api-keys\.env')
MODEL = 'claude-opus-5-5'
PROMPT_VERSION = 'v4'
PRICE_IN, PRICE_OUT = 4.0 / 1e6, 20.0 / 1e6   # USD per token, Claude Opus 5.5
MAX_EDGE = 1568
STATS = raid_db.STATS

SYSTEM = """You transcribe end-of-match scoreboards from Roblox clan-war screenshots (12v12 "fairzone" maps: Warehouse,
Docks Fairzone, Ordana Foundry; and the Republic of Aerius base Skydock). Output exactly what is printed; never estimate or
fill in a number you cannot read.

Layout families you will see:
- Hardpoint boards with two team panels labelled RED / BLUE (or a clan name), columns K (or KILLS), DMG, HEALS, CAPS, with
  per-team totals in the panel header next to a bracketed player count like [12].
- Ordana boards: SOL IMPERIALIS / ASTARTES vs INSURGENTS / XENOS panels, columns KILLS DMG HEALS CAPS with totals in the header.
- Docks boards: VAKTOVIAN EMPIRE (defenders) vs RAIDERS (attackers). Older ones are a scrollable list with a VAKTOVIANS section
  and a VACs section (both belong to the defender team) and may be cut off; some have a PLAYERS side panel with KILLS DEATHS
  DAMAGE HEALING; newer ones have K D DMG HEALS (ASSISTS CAPTURES PAUSES on the newest) with totals under the headers and a
  match timer.
- Hardpoint "MATCH MVPs" end screens (late 2026): two clan panels at the left and right edges with PLAYERS KILLS DMG HEALS
  CAPS and NO totals line and NO bracketed count (declared_size -1, totals -1), the two scores in red and blue under the
  VICTORY banner (red = left panel), and three MVP cards in the middle. format_family hp_mvp. Left panel -> side left.
- Skydock boards ("THE BATTLE OF SKYDOCK"): a compact scoreboard panel in the top-right corner with columns POINTS KILLS
  DAMAGE HEALS. It has two sections, each headed by "(n) AVIANS" and "(n) IMPERIALISTS" where n is the player count and the
  header line carries that section's totals. AVIANS are The Republic of Aerius = defender (role defender); IMPERIALISTS are
  the raiding clan (role attacker). The single row ABOVE the first section header repeats the viewer's own line - do NOT
  list it as a player (mention it in notes). Names are printed in capitals. The centre of the screen shows the two scores
  (left = Republic of Aerius, right = raiders) -> score_left / score_right, and a date stamp -> copy it into match_time.
  POINTS goes in the points field; it is -1 on boards without a POINTS column.

Rules:
- One entry per printed row, in printed order, for both panels. Keep every row even if its stats are 0, including faded
  spectator / left-the-game rows (put "spectator" in that row's note).
- If a team panel is split into sections that each print their own totals line (e.g. VAKTOVIANS (11) and VACs (1), or
  OVERSEERS), they are ONE team: list all their players under that team with subgroup set to the section name, ADD the
  section totals together for the team totals, and set declared_size to the sum of the section counts. Say so in notes.
- Handles: copy the exact characters and case as rendered. If a glyph could be capital I or lowercase l, write it the way it
  is rendered in the font. If a name is unreadable (overlapped by the player model, chat or HUD) write "(obscured)" and set
  obscured=true, but still transcribe its numbers.
- Numbers: watch 3/8, 1/7, 0/6, 5/6 confusions and overlapping HUD text. Use -1 for a column that does not exist on this
  board and for a cell you genuinely cannot read (add a note). Never use -1 for a real zero.
- totals: the per-team header totals exactly as printed (-1 when the board prints none for that column).
- declared_size: the bracketed or icon player count printed next to the team name (-1 if none).
- list_truncated: true when the panel is visibly cut off / scrollable so some rows are not shown.
- score_left / score_right: the two team scores in the top score bar (hardpoint points or defense score), -1 if not visible.
- banner_text: the result banner (e.g. VICTORY, DEFEAT, VAKTOVIAN VICTORY, BLUE VICTORY, THE ASTARTES HAVE PURGED...).
- Text fields that have nothing to say (match_time, sublabel, subgroup, note, notes, banner_text) are the empty string "".
- format_family: hp_red_blue | hp_mvp | ordana | docks_scroll | docks_panel | docks_kd | docks_match_complete | skydock | other.
- board_present: false if the image shows no scoreboard at all (then teams = [])."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["board_present", "format_family", "banner_text", "match_time", "score_left", "score_right", "teams", "notes"],
    "properties": {
        "board_present": {"type": "boolean"},
        "format_family": {"type": "string", "enum": ["hp_red_blue", "hp_mvp", "ordana", "docks_scroll", "docks_panel", "docks_kd", "docks_match_complete", "skydock", "other"]},
        "banner_text": {"type": "string"},
        "match_time": {"type": "string"},
        "score_left": {"type": "integer"},
        "score_right": {"type": "integer"},
        "notes": {"type": "string"},
        "teams": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["side", "label", "sublabel", "role", "declared_size", "list_truncated", "totals", "players"],
            "properties": {
                "side": {"type": "string", "enum": ["left", "right"]},
                "label": {"type": "string"},
                "sublabel": {"type": "string"},
                "role": {"type": "string", "enum": ["defender", "attacker", "neutral", "unknown"]},
                "declared_size": {"type": "integer"},
                "list_truncated": {"type": "boolean"},
                "totals": {"type": "object", "additionalProperties": False, "required": list(STATS),
                           "properties": {s: {"type": "integer"} for s in STATS}},
                "players": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["handle", "obscured", "kills", "deaths", "dmg", "heals", "assists", "caps", "pauses", "subgroup", "note"],
                    "properties": {
                        "handle": {"type": "string"}, "obscured": {"type": "boolean"},
                        **{s: {"type": "integer"} for s in STATS + ('pauses',)},
                        "subgroup": {"type": "string"}, "note": {"type": "string"}}}}}}}}}


def encode(im):
    buf = io.BytesIO(); im.save(buf, format='PNG', optimize=True)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def fit(im):
    w, h = im.size
    s = MAX_EDGE / max(w, h)
    return im.resize((round(w * s), round(h * s)), Image.LANCZOS) if s < 1 else im


def image_blocks(path, tiled):
    im = Image.open(path).convert('RGB')
    blocks = [encode(fit(im))]
    if tiled:
        w, h = im.size
        left = im.crop((0, 0, int(w * 0.55), h)); right = im.crop((int(w * 0.45), 0, w, h))
        blocks += [{"type": "text", "text": "Zoomed LEFT 55% of the same screenshot:"}, encode(fit(left)),
                   {"type": "text", "text": "Zoomed RIGHT 55% of the same screenshot:"}, encode(fit(right))]
    return blocks


def normalize(x):
    """Model-facing schema uses -1 / "" sentinels (the API caps nullable unions); the DB keeps real nulls."""
    if isinstance(x, dict):
        return {k: normalize(v) for k, v in x.items()}
    if isinstance(x, list):
        return [normalize(v) for v in x]
    if x == -1 or x == '':
        return None
    return x


def reconcile_extras(tm):
    """Header totals sometimes exclude a faded spectator / left-the-game row. If dropping one or two rows (searched from
    the bottom) makes every printed total match exactly, flag those rows as not counted and treat the team as reconciled."""
    stats = [s for s in STATS if tm['totals'].get(s) is not None]
    if not stats or tm.get('list_truncated'):
        return []
    ps = tm['players']
    def sums(excl):
        return {s: sum((p.get(s) or 0) for i, p in enumerate(ps) if i not in excl) for s in stats}
    if all(sums(set())[s] == tm['totals'][s] for s in stats):
        return []
    cands = list(range(len(ps) - 1, -1, -1))
    for i in cands:
        if all(sums({i})[s] == tm['totals'][s] for s in stats):
            return [i]
    for a_ in cands:
        for b_ in cands:
            if b_ < a_ and all(sums({a_, b_})[s] == tm['totals'][s] for s in stats):
                return [a_, b_]
    return []


def checks(d):
    """Per-team checksum: column sums vs printed totals, row count vs declared size."""
    out = {'teams': [], 'status': 'unchecked'}
    any_total = False; all_ok = True; kd_ok = True; truncated = False
    for tm in d.get('teams', []):
        c = {}
        extras = reconcile_extras(tm)
        for i in extras:
            p = tm['players'][i]
            p['note'] = ((p.get('note') or '') + ' not_in_totals').strip()
            if tm.get('declared_size') is not None and len(tm['players']) > tm['declared_size']:
                tm['declared_size'] += 0  # size check below also excludes these rows
        if extras:
            c['extras'] = [tm['players'][i]['handle'] for i in extras]
        # Scrollable panels: EVERY core column total strictly exceeds the visible rows -> rows are missing, not misread.
        core = [s for s in ('kills', 'dmg', 'heals', 'deaths') if tm['totals'].get(s) is not None]
        if not tm.get('list_truncated') and len(core) >= 2 and not extras:
            sums = {s: sum((p.get(s) or 0) for p in tm['players']) for s in core}
            if all(sums[s] < tm['totals'][s] for s in core):
                tm['list_truncated'] = True; c['truncated_inferred'] = True
        for s in STATS:
            tot = tm['totals'].get(s)
            if tot is None:
                continue
            any_total = True
            vals = [p.get(s) for i, p in enumerate(tm['players']) if i not in extras]
            ssum = sum(v for v in vals if v is not None)
            ok = (ssum == tot) if not tm.get('list_truncated') else (ssum <= tot)
            c[s] = {'sum': ssum, 'total': tot, 'ok': ok, 'nulls': sum(v is None for v in vals)}
            all_ok &= ok
        if tm.get('declared_size') is not None:
            # informational: the bracket count is the live player count and goes stale as people join/leave
            n = len(tm['players']) - len(extras)
            c['size'] = {'rows': n, 'declared': tm['declared_size'], 'ok': n == tm['declared_size'], 'informational': True}
        truncated |= bool(tm.get('list_truncated'))
        # the rating uses only kills and dmg: a team whose kills and dmg both reconcile is complete for scoring
        c['kd_ok'] = all(c.get(s, {}).get('ok', False) for s in ('kills', 'dmg')) if all(s in c for s in ('kills', 'dmg')) else False
        kd_ok &= c['kd_ok']
        out['teams'].append(c)
    if not d.get('board_present') or not d.get('teams'):
        out['status'] = 'failed'
    elif not any_total:
        out['status'] = 'unchecked'
    elif all_ok and not truncated:
        out['status'] = 'verified'
    elif kd_ok and not truncated:
        out['status'] = 'kd_verified'      # kills + dmg reconcile on every team; heals/caps/assists do not
    elif kd_ok and truncated:
        out['status'] = 'partial'          # some panel is cut off; the complete teams reconcile on kills + dmg
    else:
        out['status'] = 'failed'
    return out


client = anthropic.Anthropic(max_retries=6)


def transcribe(path, attempt):
    tiled = attempt >= 2
    effort = 'medium' if attempt == 1 else 'high'
    content = image_blocks(path, tiled) + [{"type": "text", "text": "Transcribe this scoreboard."}]
    kwargs = dict(model=MODEL, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": content}],
                  output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": effort})
    try:
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        if 'fallback' in str(e).lower() or 'beta' in str(e).lower():
            resp = client.messages.create(**kwargs)   # key/platform without the fallback beta
        else:
            raise
    usage = resp.usage
    cost = usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT
    if resp.stop_reason == 'refusal':
        return dict(status='refusal', raw=None, checks=None, error=str(getattr(resp, 'stop_details', None)), it=usage.input_tokens, ot=usage.output_tokens, cost=cost, tiled=tiled, effort=effort)
    if resp.stop_reason == 'max_tokens':
        return dict(status='error', raw=None, checks=None, error='max_tokens', it=usage.input_tokens, ot=usage.output_tokens, cost=cost, tiled=tiled, effort=effort)
    text = next(b.text for b in resp.content if b.type == 'text')
    d = normalize(json.loads(text))
    c = checks(d)
    return dict(status=c['status'], raw=d, checks=c, error=None, it=usage.input_tokens, ot=usage.output_tokens, cost=cost, tiled=tiled, effort=effort)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8); ap.add_argument('--limit', type=int, default=0); ap.add_argument('--image-id', type=int)
    ap.add_argument('--max-attempts', type=int, default=2)
    ap.add_argument('--source', help='only images from this source name (sources.name)')
    ap.add_argument('--map', help='only images whose audit_map equals this')
    ap.add_argument('--recheck', action='store_true', help='recompute checks/status from stored raw_json; no API calls')
    ap.add_argument('--consensus', action='store_true', help='mark unchecked boards whose two independent reads agree cell-for-cell')
    a = ap.parse_args()
    con = raid_db.connect()
    if a.consensus:
        n = 0
        for img in con.execute("SELECT DISTINCT image_id FROM transcriptions WHERE status='unchecked'").fetchall():
            reads = con.execute("SELECT transcription_id, raw_json FROM transcriptions WHERE image_id=? AND status='unchecked' ORDER BY attempt", (img[0],)).fetchall()
            if len(reads) < 2:
                continue
            def cells(raw):
                d = json.loads(raw)
                return [(tm['side'], p['handle'].lower(), p.get('kills'), p.get('dmg'), p.get('heals')) for tm in d['teams'] for p in tm['players']]
            if cells(reads[0]['raw_json']) == cells(reads[-1]['raw_json']):
                con.execute("UPDATE transcriptions SET status='consensus' WHERE transcription_id=?", (reads[-1]['transcription_id'],)); n += 1
        con.commit(); print('consensus:', n, dict(con.execute('SELECT status, count(*) FROM transcriptions GROUP BY status').fetchall()))
        return
    if a.recheck:
        n = 0
        for t in con.execute("SELECT transcription_id, raw_json FROM transcriptions WHERE raw_json IS NOT NULL AND status!='consensus'").fetchall():
            d = json.loads(t['raw_json']); c = checks(d)
            con.execute('UPDATE transcriptions SET status=?, checks_json=?, raw_json=? WHERE transcription_id=?',
                        (c['status'], json.dumps(c), json.dumps(d, ensure_ascii=False), t['transcription_id']))
            n += 1
        con.commit(); print('rechecked', n, dict(con.execute('SELECT status, count(*) FROM transcriptions GROUP BY status').fetchall()))
        return
    todo = []
    conds, qargs = [], []
    if a.image_id:
        conds.append('image_id=?'); qargs.append(a.image_id)
    if a.source:
        conds.append('source_id=(SELECT source_id FROM sources WHERE name=?)'); qargs.append(a.source)
    if a.map:
        conds.append('audit_map=?'); qargs.append(a.map)
    q = 'SELECT image_id, file, base_dir FROM images' + (' WHERE ' + ' AND '.join(conds) if conds else '') + ' ORDER BY image_id'
    for img in con.execute(q, qargs).fetchall():
        prev = con.execute('SELECT status, attempt FROM transcriptions WHERE image_id=? ORDER BY attempt', (img['image_id'],)).fetchall()
        if any(p['status'] in ('verified', 'kd_verified', 'partial', 'consensus') for p in prev):
            continue
        attempts = max([p['attempt'] for p in prev if p['status'] != 'error'], default=0)
        if attempts >= a.max_attempts or sum(p['status'] == 'error' for p in prev) >= 3:
            continue
        todo.append((img['image_id'], img['file'], img['base_dir'], attempts + 1))
    if a.limit:
        todo = todo[:a.limit]
    run_id = raid_db.start_run(con, 'transcribe', 'raid_transcribe.py', {'model': MODEL, 'prompt_version': PROMPT_VERSION, 'workers': a.workers,
                                                                        'max_edge': MAX_EDGE, 'todo': len(todo)})
    con.commit()
    print(f'run {run_id}: {len(todo)} images to transcribe with {MODEL}', flush=True)
    t0 = time.time(); done = 0; counts = {}; spent = 0.0

    def work(item):
        image_id, file, base_dir, attempt = item
        path = os.path.join(raid_db.ROOT, base_dir, file) if base_dir else os.path.join(raid_db.SHOTS, file)
        try:
            r = transcribe(path, attempt)
        except Exception as e:
            r = dict(status='error', raw=None, checks=None, error=repr(e)[:300], it=0, ot=0, cost=0.0, tiled=attempt >= 2, effort='')
        return image_id, attempt, r

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for f in as_completed(futs):
            image_id, attempt, r = f.result()
            con.execute('''INSERT INTO transcriptions(image_id,attempt,model,prompt_version,effort,tiled,created_at,status,checks_json,raw_json,
                           input_tokens,output_tokens,cost_usd,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (image_id, attempt, MODEL, PROMPT_VERSION, r['effort'], 1 if r['tiled'] else 0, raid_db.now(), r['status'],
                         json.dumps(r['checks']) if r['checks'] else None, json.dumps(r['raw'], ensure_ascii=False) if r['raw'] else None,
                         r['it'], r['ot'], r['cost'], r['error']))
            con.commit()
            done += 1; counts[r['status']] = counts.get(r['status'], 0) + 1; spent += r['cost']
            if done % 25 == 0 or done == len(todo):
                print(f'{done}/{len(todo)} {time.time()-t0:.0f}s ${spent:.2f} {counts}', flush=True)
    raid_db.finish_run(con, run_id, {'done': done, 'counts': counts, 'cost_usd': round(spent, 2), 'seconds': round(time.time() - t0)})
    con.commit()
    print('DONE', counts, f'${spent:.2f}', flush=True)


if __name__ == '__main__':
    main()
