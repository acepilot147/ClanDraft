"""Resolve scoreboard handles to their real Roblox username casing (and confirm the account exists).

Scoreboards that print names in capitals (Skydock, some Docks layouts) lose the casing, so a player seen only
there ends up as an all-caps key. Roblox usernames are case-insensitive, so one batch lookup of the printed
string returns the canonical spelling. Results are cached in RobloxCasing.csv (tracked, like RobloxNames.csv):

  Handle, RobloxId, Username, DisplayName, Status (found | notfound | error), CheckedAt

Endpoint: POST https://users.roblox.com/v1/usernames/users, 100 names per call, paced (the endpoint meters by
usernames requested; see README on check-roblox-names.js). 429 -> back off and retry the same batch.

usage: python -I roblox_casing.py <names.txt>      # one handle per line; already-cached handles are skipped
       python -I roblox_casing.py --from-db          # every rated player key not covered by an authoritative casing
"""
import csv, os, sys, time, json, datetime, re
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'RobloxCasing.csv')
FIELDS = ['Handle', 'RobloxId', 'Username', 'DisplayName', 'Status', 'CheckedAt']
URL = 'https://users.roblox.com/v1/usernames/users'
PACE = 6.0


def load_cache():
    if not os.path.exists(CACHE):
        return {}
    return {r['Handle'].lower(): r for r in csv.DictReader(open(CACHE, newline='', encoding='utf-8'))}


def names_from_db():
    sys.path.insert(0, ROOT)
    import raid_db
    con = raid_db.connect()
    rid = con.execute("SELECT max(run_id) FROM runs WHERE kind='score'").fetchone()[0]
    keys = [r[0] for r in con.execute('SELECT player_key FROM ratings WHERE run_id=?', (rid,)).fetchall()]
    known = set()
    for r in csv.DictReader(open(os.path.join(ROOT, 'CombinedLists.csv'), newline='', encoding='utf-8-sig')):
        known.add(r['LegacyName'].lower())
    for r in csv.DictReader(open(os.path.join(ROOT, 'RobloxNames.csv'), newline='', encoding='utf-8-sig')):
        for n in [r['LegacyName'], r['CurrentName']] + (r['PastNames'] or '').split('|'):
            if n.strip():
                known.add(n.strip().lower())
    return [k for k in keys if k.lower() not in known and re.fullmatch(r'[A-Za-z0-9_]{3,20}', k)]


def variants(name, limit=16):
    """I/l (and 1) are confusable in scoreboard fonts: every spelling that swaps those letters, excluding the original."""
    import itertools
    pos = [i for i, ch in enumerate(name) if ch in 'IiLl1']
    if not pos or len(pos) > 4:
        return []
    out = []
    for combo in itertools.product('IL1', repeat=len(pos)):
        v = list(name)
        for i, ch in zip(pos, combo):
            v[i] = ch if name[i].isupper() or name[i] == '1' else ch.lower().replace('1', '1')
        v = ''.join(v)
        if v.lower() != name.lower() and v not in out:
            out.append(v)
    return out[:limit]


def variant_pass(cache, s, w, fh):
    """For cached notfound handles, look up their I/l/1 swaps; a hit is stored as Status found_variant with the
    ORIGINAL handle so the resolver can map the misread spelling to the real account."""
    nf = [r['Handle'] for r in cache.values() if r['Status'] == 'notfound']
    cand = {}
    for h in nf:
        for v in variants(h):
            cand.setdefault(v.lower(), (v, h))
    print(f'{len(nf)} notfound handles -> {len(cand)} variant lookups', flush=True)
    items = list(cand.values()); hits = 0
    for i in range(0, len(items), 100):
        batch = items[i:i + 100]
        for attempt in range(6):
            r = s.post(URL, data=json.dumps({'usernames': [v for v, _ in batch], 'excludeBannedUsers': False}), timeout=40)
            if r.status_code == 429:
                wait = 30 * (attempt + 1); print(f'  429: waiting {wait}s', flush=True); time.sleep(wait); continue
            break
        if r.status_code != 200:
            print(f'  batch HTTP {r.status_code}', flush=True); time.sleep(PACE); continue
        got = {d['requestedUsername'].lower(): d for d in r.json().get('data', [])}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        by_handle = {}
        for v, h in batch:
            d = got.get(v.lower())
            if d:
                by_handle.setdefault(h, []).append(d)
        for h, ds in by_handle.items():
            if len(ds) == 1:          # exactly one spelling exists: that is the account
                d = ds[0]; hits += 1
                w.writerow({'Handle': h, 'RobloxId': d['id'], 'Username': d['name'], 'DisplayName': d.get('displayName', ''), 'Status': 'found_variant', 'CheckedAt': now})
            else:                     # several real accounts differ only by I/l: ambiguous, leave for a human
                w.writerow({'Handle': h, 'RobloxId': '', 'Username': ' | '.join(d['name'] for d in ds), 'DisplayName': '', 'Status': 'ambiguous_variant', 'CheckedAt': now})
        fh.flush(); time.sleep(PACE)
    print(f'DONE variants: {hits} handles recovered', flush=True)


def main():
    if '--variants' in sys.argv:
        cache = load_cache()
        fh = open(CACHE, 'a', newline='', encoding='utf-8'); w = csv.DictWriter(fh, fieldnames=FIELDS)
        s = requests.Session(); s.headers.update({'User-Agent': 'ClanDraft casing lookup (+https://github.com/acepilot147)', 'Content-Type': 'application/json'})
        variant_pass(cache, s, w, fh); fh.close(); return
    if '--from-db' in sys.argv:
        names = names_from_db()
    else:
        names = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip()]
    cache = load_cache()
    todo = []
    seen = set()
    for n in names:
        k = n.lower()
        if k in cache or k in seen:
            continue
        seen.add(k); todo.append(n)
    print(f'{len(names)} handles, {len(names) - len(todo)} cached, {len(todo)} to look up', flush=True)
    new = not os.path.exists(CACHE)
    fh = open(CACHE, 'a', newline='', encoding='utf-8'); w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader()
    s = requests.Session(); s.headers.update({'User-Agent': 'ClanDraft casing lookup (+https://github.com/acepilot147)', 'Content-Type': 'application/json'})
    found = nf = 0
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        for attempt in range(6):
            r = s.post(URL, data=json.dumps({'usernames': batch, 'excludeBannedUsers': False}), timeout=40)
            if r.status_code == 429:
                wait = 30 * (attempt + 1); print(f'  429: waiting {wait}s', flush=True); time.sleep(wait); continue
            break
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if r.status_code != 200:
            for n in batch:
                w.writerow({'Handle': n, 'RobloxId': '', 'Username': '', 'DisplayName': '', 'Status': f'error_{r.status_code}', 'CheckedAt': now})
            fh.flush(); print(f'  batch {i // 100 + 1}: HTTP {r.status_code}', flush=True); time.sleep(PACE); continue
        got = {d['requestedUsername'].lower(): d for d in r.json().get('data', [])}
        for n in batch:
            d = got.get(n.lower())
            if d:
                found += 1
                w.writerow({'Handle': n, 'RobloxId': d['id'], 'Username': d['name'], 'DisplayName': d.get('displayName', ''), 'Status': 'found', 'CheckedAt': now})
            else:
                nf += 1
                w.writerow({'Handle': n, 'RobloxId': '', 'Username': '', 'DisplayName': '', 'Status': 'notfound', 'CheckedAt': now})
        fh.flush()
        print(f'  {min(i + 100, len(todo))}/{len(todo)} found={found} notfound={nf}', flush=True)
        time.sleep(PACE)
    fh.close(); print('DONE', found, 'found,', nf, 'not found', flush=True)


if __name__ == '__main__':
    main()
