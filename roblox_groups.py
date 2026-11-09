"""Settle look-alike pairs that are two real Roblox accounts: which one is the clanner?

Capital-I / lowercase-l / digit-1 lookalike accounts are common (impersonation alts and name squats). When both
spellings exist on Roblox, the scoreboard text cannot tell them apart, but Roblox group memberships can: the
account that is in clan groups (VAK, RoA, SOL, TCAR, ...) is the player; an account with no groups at all is a
bystander. Public endpoints, no auth:

  GET https://users.roblox.com/v1/users/{id}                 -> created date
  GET https://groups.roblox.com/v2/users/{id}/groups/roles   -> group memberships

Results are cached in RobloxGroups.csv (tracked): RobloxId, Username, Created, GroupCount, ClanGroups, CheckedAt.

usage: python -I roblox_groups.py                 # every SPLIT row in NameMergeReport.csv
       python -I roblox_groups.py id1 id2 ...     # specific accounts
Prints one decision line per pair: WINNER <- loser (evidence) or UNDECIDED.
"""
import csv, os, sys, re, time, json, datetime
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'RobloxGroups.csv')
FIELDS = ['RobloxId', 'Username', 'Created', 'GroupCount', 'ClanGroups', 'CheckedAt']
CLAN = re.compile(r'vaktov|aerius|avian|sol imperialis|solar militarum|imperial insurgence|snow core|blackwater|royales|clone army|'
                  r'outlaw posse|surge|robloxian army|vultar|imperium|legion|regime|collective|coalition|federation|military|'
                  r'army|corps|republic|empire|clan|raid|defen|war|guard|battalion|division|command|forces|order\b|concord|'
                  r'accord|dominion|dynasty|union|alliance|syndicate|brigade|marines|navy|airforce|regiment', re.I)
PRIVATE = re.compile(r'treasury|fund|awaiting', re.I)


def load_cache():
    if not os.path.exists(CACHE):
        return {}
    return {r['RobloxId']: r for r in csv.DictReader(open(CACHE, newline='', encoding='utf-8'))}


def fetch(s, uid):
    u = s.get(f'https://users.roblox.com/v1/users/{uid}', timeout=20)
    g = s.get(f'https://groups.roblox.com/v2/users/{uid}/groups/roles', timeout=20)
    if u.status_code == 429 or g.status_code == 429:
        time.sleep(20); return fetch(s, uid)
    uj = u.json() if u.status_code == 200 else {}
    gj = g.json().get('data', []) if g.status_code == 200 else []
    clan = [f"{x['group']['name']} ({x['role']['name']})" for x in gj if CLAN.search(x['group']['name']) and not PRIVATE.search(x['group']['name'])]
    return {'RobloxId': str(uid), 'Username': uj.get('name', ''), 'Created': str(uj.get('created', ''))[:10], 'GroupCount': len(gj),
            'ClanGroups': ' | '.join(clan)[:400], 'CheckedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()}


def decide(a, b):
    """a, b: cache rows. Returns (winner, loser, reason) or (None, None, reason)."""
    ga, gb = int(a['GroupCount']), int(b['GroupCount']); ca, cb = bool(a['ClanGroups']), bool(b['ClanGroups'])
    if ca and not cb and gb <= 2:
        return a, b, f"{a['Username']} is in clan groups ({a['ClanGroups'][:70]}); {b['Username']} has {gb} groups"
    if cb and not ca and ga <= 2:
        return b, a, f"{b['Username']} is in clan groups ({b['ClanGroups'][:70]}); {a['Username']} has {ga} groups"
    if ga >= 5 and gb == 0:
        return a, b, f"{a['Username']} has {ga} groups; {b['Username']} has none"
    if gb >= 5 and ga == 0:
        return b, a, f"{b['Username']} has {gb} groups; {a['Username']} has none"
    return None, None, f"both plausible: {a['Username']} {ga} groups (clan: {ca}), {b['Username']} {gb} groups (clan: {cb})"


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cache = load_cache()
    s = requests.Session(); s.headers.update({'User-Agent': 'ClanDraft identity check (+https://github.com/acepilot147)'})
    pairs = []
    if len(sys.argv) > 1:
        ids = sys.argv[1:]
    else:
        ids = []
        for r in csv.DictReader(open(os.path.join(ROOT, 'NameMergeReport.csv'), newline='', encoding='utf-8')):
            if r['Status'] == 'SPLIT':
                found = re.findall(r'(\S+) = roblox (\d+)', r['Evidence'])
                if len(found) == 2:
                    pairs.append(found); ids += [found[0][1], found[1][1]]
    new = not os.path.exists(CACHE)
    fh = open(CACHE, 'a', newline='', encoding='utf-8'); w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader()
    for uid in dict.fromkeys(ids):
        if uid in cache:
            continue
        row = fetch(s, uid); cache[uid] = row; w.writerow(row); fh.flush(); time.sleep(0.8)
    fh.close()
    decisions = []
    for (na, ia), (nb, ib) in pairs:
        win, lose, why = decide(cache[ia], cache[ib])
        if win:
            print(f"DECIDED  {win['Username']:18} <- {lose['Username']:18}  {why}")
            decisions.append({'winner': win['Username'], 'winner_id': win['RobloxId'], 'loser': lose['Username'], 'loser_id': lose['RobloxId'],
                              'loser_created': lose['Created'], 'why': why, 'handles': [na, nb]})
        else:
            print(f"UNDECIDED {na} / {nb}: {why}")
    json.dump(decisions, open(os.path.join(ROOT, 'sources', 'lookalike_decisions.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'{len(decisions)} decided of {len(pairs)} pairs -> sources/lookalike_decisions.json')


if __name__ == '__main__':
    main()
