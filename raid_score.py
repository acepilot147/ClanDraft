"""Score raids.sqlite: within-lobby z per player-game, z average per player, and a
data-only OVR (no hand-crafted rating is used anywhere in this file).

  python -I raid_score.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--label text]

Each invocation writes one row in `runs` (parameters, script, git revision,
summary) and tags every z_scores / ratings row with that run_id, so a rating
is always traceable to the games, images and rules that produced it.

Rules (all recorded in the run's params_json):
  grouping   Warehouse / Ordana: the whole lobby is one group (symmetric maps).
             Docks and Skydock likewise since 2026-10-24 (a_cemaster: all
             four are mirrored fairzones with equal numbers), with the
             defending side's shared edge taken out by a per-map home term
             fitted jointly with the ratings (summary home_term, in lobby z).
             RAID-mode repo games (:asym) and games from win-only sources
             (sources.result_selected: Discord victory channels) stay per
             team: conditioning on the win lifts the posting clan's whole
             side, so only the within-team ranking is taken from them. A
             board with one truncated side is scored per team (the complete
             side ranked within itself).
  eligibility only games that are not duplicates and whose transcription is
             verified or partial; a group is scored only if its team(s) are
             complete (not truncated) and the header checks passed, and it has
             >= MIN_GROUP scoreable rows.
  row flags  obscured (name unreadable): excluded entirely (a_cemaster, 2026-10-24).
             not_in_totals / spectator, afk (0 kills & 0 dmg), partial (kills
             AND dmg under PARTIAL_FRAC of the group median), unreadable (a
             null kills or dmg): excluded entirely.
             late_join_suspect: boards carry no time-played column, so a late
             join can only be inferred. After a first full pass, a game more
             than OUTLIER_GAP (z) below the median of the player's other
             lobby-adjusted games (OUTLIER_MIN_GAMES or more) is discarded
             from both the player and the lobby, and the scoring is repeated
             once without those rows. Observed low-side gaps beyond 2 z run
             ~6x what a normal spread predicts while the high side does not,
             which is the partial-game signature. The pass-1 point and the
             gap are kept on the row so the profile can show what was dropped.
  z          z_kills, z_dmg within the group (population sd); composite =
             0.5*z_kills + 0.5*z_dmg re-standardized within the group and
             winsorized at +-WINSOR_Z.
  identity   handle -> canonical via ALIASES.md / CombinedLists names /
             Roblox rename history (same order as resolve-handles.js); a
             handle with no MATCH keeps its own name (case-insensitive key).
  shrinkage  z_shrunk = z_mean * n / (n + k), k = within-player variance /
             between-player variance, both estimated from this run's data.
  strength   of schedule: ratings are solved jointly so that a game's expected
             z is the player's rating minus the mean rating of the others in
             the same lobby group. Each game's lobby-adjusted value is
             y = z + lobby mean (stored as z_scores.lobby_z); the rating z_sos
             is the shrunk mean of y, iterated to convergence and centred so
             the appearance-weighted average player sits at 0 (= OVR_MEAN).
             Shrinkage constants are re-estimated on y. ovr uses z_sos; the
             unadjusted ovr_unadj is kept for comparison.
  OVR        OVR_MEAN + OVR_SD * z_shrunk / sd_between, capped at 96 (97+ is
             the hand-assigned all-time-great tier) with no floor. The scale is
             a convention (average lobby participant = OVR_MEAN); nothing from
             CombinedLists.csv OVR values enters the computation.
  per map    ovr_<map> applies the same shrinkage and scale to that map's games
             alone (null when the player has none there).
"""
import os, sys, csv, re, json, math, argparse, collections, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # survives python -I
import raid_db

ROOT = raid_db.ROOT
SYMMETRIC_MAPS = {'Warehouse', 'Ordana', 'Docks', 'Skydock'}   # a_cemaster 2026-10-24: mirrored fairzones with equal numbers - one lobby per board
HOME_MAPS = {'Docks', 'Skydock'}                                 # base maps: the defenders' shared edge is a fitted per-map term, not skill
MIN_GROUP = 5
WINSOR_Z = 2.5
PARTIAL_FRAC = 0.25          # under a quarter of the lobby median in BOTH kills and dmg: clearly not a full game
OUTLIER_GAP = 2.0            # z below the median of the player's other games (about 3 within-player sd) -> late-join suspect
OUTLIER_MIN_GAMES = 4        # the player needs this many scored games before one of them can be judged against the rest
OVR_MEAN, OVR_SD, OVR_CLAMP = 80.0, 6.0, (-math.inf, 96.0)   # 97+ stays the hand-assigned all-time-great tier; no floor
MIN_RATED_GAMES = 1


# ---------------------------------------------------------------- identity
# Resolution order (strongest evidence first), per scoreboard handle:
#   1. ALIASES.md alias table / CombinedLists.csv name           -> canonical name        (hand-confirmed)
#   2. Roblox account: the handle is a current/past username of a cached account (RobloxNames.csv rename
#      histories, RobloxCasing.csv username lookups incl. I/l-swap variants) -> that account's display name
#      (its CombinedLists/ALIASES name if it has one, else its current Roblox username with real casing)
#   3. I/l look-alike groups (I and l share a glyph in the mixed-case fonts; capital boards misread L as I):
#      members merge onto the resolved member; when two members resolve to DIFFERENT names, the one backed by a
#      real Roblox account wins over one that Roblox does not know; two real accounts stay split and are reported.
# "Do NOT merge" bullets in ALIASES.md block any pair they name at every step.
# Display casing for handles with no account: RoA registry / roster spelling, else the most-attested mixed-case
# board spelling, else as printed. Every decision lands in handle_resolutions.via and NameMergeReport.csv.
def exact_key(n): return n.strip().lower()
def confusable_key(n): return n.strip().lower().replace('i', 'l').replace('1', 'l')

# Cache rows ALIASES.md documents as pointing at the wrong person (the literal "Tenshi" account; the literal
# "EvilWesly" account - scoreboard "evilwesly" is the capital-I clanner yxng_wes; the literal "Valitron" account -
# scoreboard "Valitron" is the capital-I clanner VaIitron).
WRONG_CACHE_ROWS = {'tenshi', 'evilwesly', 'valitron'}
PROSE_ALIASES = {'evilwesly': 'yxng_wes'}


def load_identity():
    canon = {}; canon_conf = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'CombinedLists.csv'), newline='', encoding='utf-8-sig')):
        n = r['LegacyName']
        if n:
            canon.setdefault(exact_key(n), n); canon_conf.setdefault(confusable_key(n), n)
    alias = {}; no_merge = set()
    for line in open(os.path.join(ROOT, 'ALIASES.md'), encoding='utf-8'):
        if line.startswith('|'):
            cells = [c.replace('`', '').strip() for c in line.split('|')]
            if len(cells) < 3 or not cells[1] or re.fullmatch(r'-+', cells[1]) or cells[1].lower().startswith('canonical'):
                continue
            for a in [x.strip() for x in cells[2].split(',') if x.strip()]:
                alias[exact_key(a)] = cells[1]
            alias[exact_key(cells[1])] = cells[1]
        elif line.startswith('- ') and ('\u2260' in line or ' vs ' in line):
            names = [exact_key(x) for x in re.findall(r'`([^`]+)`', line)]
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    no_merge.add(frozenset((names[i], names[j])))
    alias.update(PROSE_ALIASES)
    alias_conf = {confusable_key(k): v for k, v in alias.items()}
    # Roblox accounts: every name an account has answered to -> account id
    accounts = {}; name_to_id = {}; ambiguous = set(); notfound = set()
    def add_account(aid, legacy, current, names):
        acc = accounts.setdefault(aid, {'legacy': legacy, 'current': current or legacy, 'names': set()})
        if current:
            acc['current'] = current
        for n in names:
            if n and n.strip():
                k = exact_key(n); acc['names'].add(k)
                if k in name_to_id and name_to_id[k] != aid:
                    ambiguous.add(k)          # two cached accounts answered to this name: not evidence
                name_to_id.setdefault(k, aid)
    rn = os.path.join(ROOT, 'RobloxNames.csv')
    if os.path.exists(rn):
        for r in csv.DictReader(open(rn, newline='', encoding='utf-8-sig')):
            if not r.get('RobloxId') or exact_key(r['LegacyName']) in WRONG_CACHE_ROWS:
                continue
            add_account(r['RobloxId'], r['LegacyName'], r.get('CurrentName') or '', [r['LegacyName'], r.get('CurrentName') or ''] + (r.get('PastNames') or '').split('|'))
    rc = os.path.join(ROOT, 'RobloxCasing.csv')
    if os.path.exists(rc):
        rows = {}
        for r in csv.DictReader(open(rc, newline='', encoding='utf-8')):
            rows[exact_key(r['Handle'])] = r                       # last row per handle wins (variant pass appends)
        for k, r in rows.items():
            if r['Status'] in ('found', 'found_variant') and r['RobloxId'] and k not in WRONG_CACHE_ROWS:
                add_account(r['RobloxId'], r['Username'], r['Username'], [r['Handle'], r['Username']])
            elif r['Status'] in ('notfound', 'ambiguous_variant'):
                notfound.add(k)
    for k in ambiguous:
        name_to_id.pop(k, None)
    # casing hints for handles without an account: RoA registry / roster spellings
    casing = {}
    reg = os.path.join(ROOT, 'sources', 'RoA AMCOM Registry - Events.csv')
    if os.path.exists(reg):
        for r in csv.DictReader(open(reg, newline='', encoding='utf-8-sig')):
            for col in ("Attendees' Usernames", "Latecomers' Usernames", "Penders' Usernames", 'Username'):
                for n in re.split(r'[,\s]+', r.get(col) or ''):
                    if re.fullmatch(r'[A-Za-z0-9_]{3,20}', n) and not n.isupper():
                        casing.setdefault(exact_key(n), n)
    return dict(canon=canon, canon_conf=canon_conf, alias=alias, alias_conf=alias_conf, no_merge=no_merge,
                accounts=accounts, name_to_id=name_to_id, notfound=notfound, casing=casing)


def blocked(a, b, ctx):
    return frozenset((exact_key(a), exact_key(b))) in ctx['no_merge']


def account_display(aid, ctx):
    """Name to show for a Roblox account: its CombinedLists/ALIASES name if it has one, else its current username."""
    acc = ctx['accounts'][aid]
    for k in [exact_key(acc['legacy'])] + sorted(acc['names']):
        if k in ctx['alias']:
            return ctx['alias'][k]
        if k in ctx['canon']:
            return ctx['canon'][k]
    return acc['current'] or acc['legacy']


def resolve(handle, ctx):
    ek = exact_key(handle)
    if ek in ctx['alias']:
        return 'MATCH', ctx['alias'][ek], [], 'ALIASES.md'
    if ek in ctx['canon']:
        return 'MATCH', ctx['canon'][ek], [], 'CombinedLists'
    aid = ctx['name_to_id'].get(ek)
    if aid:
        disp = account_display(aid, ctx)
        if not blocked(handle, disp, ctx):
            return 'MATCH', disp, [], 'roblox account %s' % aid
        return 'CANDIDATE', None, [disp], 'roblox account %s but ALIASES.md says do not merge' % aid
    cands = set()
    ck = confusable_key(handle)
    if ck in ctx['canon_conf']:
        cands.add(ctx['canon_conf'][ck])
    if ck in ctx['alias_conf']:
        cands.add(ctx['alias_conf'][ck])
    if cands:
        return 'CANDIDATE', None, sorted(cands), 'I-l look-alike'
    return 'UNKNOWN', None, [], ''


def backed(name, ctx):
    """Is this display name backed by a real Roblox account (cached id) or a hand-confirmed table?"""
    k = exact_key(name)
    return k in ctx['alias'] or k in ctx['name_to_id']


def resolve_all(con):
    """Returns {exact_key(handle): (status, player_key)} and writes handle_resolutions + NameMergeReport.csv."""
    ctx = load_identity()
    spellings = collections.defaultdict(collections.Counter); first = {}
    for r in con.execute('SELECT handle, count(*) n FROM player_games WHERE obscured=0 GROUP BY handle').fetchall():
        h = r['handle'].strip(); spellings[exact_key(h)][h] += r['n']; first.setdefault(exact_key(h), h)
    games_by_key = {k: sum(v.values()) for k, v in spellings.items()}
    for r in con.execute("SELECT DISTINCT substr(note, 11) c FROM player_games WHERE note LIKE 'canonical=%'").fetchall():
        first.setdefault(exact_key(r['c']), r['c']); games_by_key.setdefault(exact_key(r['c']), 0)
    def best_spelling(k):
        """Display spelling for a handle with no account: registry casing, else most-attested mixed-case board spelling."""
        if k in ctx['casing']:
            return ctx['casing'][k]
        mixed = [(n, c) for n, c in spellings.get(k, {}).items() if not n.isupper()]
        if mixed:
            return max(mixed, key=lambda x: x[1])[0]
        return first[k]
    result = {}
    for k, h in first.items():
        st, canon, cands, via = resolve(h, ctx)
        result[k] = [st, canon or best_spelling(k), cands, via]
    # look-alike groups
    groups = collections.defaultdict(list)
    for k in result:
        groups[confusable_key(k)].append(k)
    split_report = []
    for ck, keys in groups.items():
        if len(keys) < 2:
            continue
        resolved = [k for k in keys if result[k][0] == 'MATCH']
        targets = {}
        for k in resolved:
            targets.setdefault(result[k][1], []).append(k)
        if len(targets) > 1:
            strong = [t for t in targets if backed(t, ctx) and not any(exact_key(t) in ctx['notfound'] for _ in [0])]
            weak = [t for t in targets if t not in strong]
            if len(strong) == 1 and weak:
                target = strong[0]; via = 'I-l look-alike of ' + target + ' (only account-backed spelling)'
                for t in weak:
                    for k in targets[t]:
                        if not any(blocked(first[k], first[o], ctx) for o in keys if o != k):
                            result[k] = ['MATCH', target, [], via]
            else:
                split_report.append({'Handle': ' / '.join(sorted(targets)), 'Games': sum(games_by_key.get(k, 0) for k in keys), 'MergedInto': '',
                                     'Status': 'SPLIT', 'Evidence': 'two Roblox accounts differ only by I/l: ' + '; '.join(
                                         f"{t} = roblox {ctx['name_to_id'].get(exact_key(t), '?')}" for t in sorted(targets)) + ' - decide in ALIASES.md'})
            continue
        if targets:
            target = next(iter(targets))
        else:
            # no member resolved: collapse onto the account-backed / best-attested spelling
            cand = [k for k in keys if exact_key(result[k][1]) not in ctx['notfound']] or keys
            best = max(cand, key=lambda k: (not first[k].isupper(), games_by_key.get(k, 0)))
            target = result[best][1]
        via = 'I-l look-alike of ' + target
        for k in keys:
            if result[k][0] == 'MATCH' or exact_key(result[k][1]) == exact_key(target):
                continue
            if any(blocked(first[k], first[o], ctx) or blocked(first[k], target, ctx) for o in keys if o != k):
                result[k][3] = (result[k][3] + '; look-alike merge blocked by ALIASES.md').strip('; ')
                continue
            result[k] = ['MATCH', target, [], via]
    # persist + review report
    con.execute('DELETE FROM handle_resolutions')
    report = []
    for k, (st, pk, cands, via) in result.items():
        con.execute('INSERT INTO handle_resolutions VALUES(?,?,?,?,?,?,?)', (k, first[k], st, pk if st == 'MATCH' else None, json.dumps(cands), via, raid_db.now()))
        if exact_key(pk) != k or (st == 'MATCH' and pk != first[k]):
            report.append({'Handle': first[k], 'Games': games_by_key.get(k, 0), 'MergedInto': pk, 'Status': st, 'Evidence': via or 'casing'})
        elif st != 'MATCH' and (cands or 'blocked' in via):
            report.append({'Handle': first[k], 'Games': games_by_key.get(k, 0), 'MergedInto': '', 'Status': st, 'Evidence': via + (' candidates: ' + ', '.join(cands) if cands else '')})
    report += split_report
    report.sort(key=lambda r: (r['Status'] != 'SPLIT', -int(r['Games']), r['Handle'].lower()))
    with open(os.path.join(ROOT, 'NameMergeReport.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['Handle', 'Games', 'MergedInto', 'Status', 'Evidence']); w.writeheader(); w.writerows(report)
    con.commit()
    return {k: (v[0], v[1]) for k, v in result.items()}


# ---------------------------------------------------------------- scoring
def mean(x): return sum(x) / len(x)
def psd(x):
    m = mean(x); return math.sqrt(sum((v - m) ** 2 for v in x) / len(x))
def ssd(x):
    if len(x) < 2: return None
    m = mean(x); return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))
def zs(x):
    s = psd(x); m = mean(x)
    return [((v - m) / s) if s > 1e-9 else 0.0 for v in x]
def clamp(v, lo, hi): return max(lo, min(hi, v))
def median(x):
    y = sorted(x); n = len(y); return y[n // 2] if n % 2 else (y[n // 2 - 1] + y[n // 2]) / 2


def team_complete(team):
    """Scoreable team: not cut off, and its kills and dmg columns reconcile with the printed totals (repo games and
    consensus boards carry no checks and are trusted as a whole)."""
    if team['truncated']:
        return False
    c = json.loads(team['checks_json'] or '{}')
    if not c:
        return True
    if 'kd_ok' in c:
        return bool(c['kd_ok'])
    return all(v['ok'] for k, v in c.items() if isinstance(v, dict) and 'ok' in v and not v.get('informational'))


def score_game(con, game, keyed, drop=frozenset(), selected=frozenset()):
    """Yield (pg_id, player_key, group_key, group_n, zk, zd, zc, flag, home) for one game; home is 1 for the defending side
    and 0 for the attackers when both sides of a HOME_MAPS board share the lobby, else None."""
    teams = con.execute('SELECT * FROM teams WHERE game_id=? ORDER BY team_id', (game['game_id'],)).fetchall()
    rows = con.execute('SELECT * FROM player_games WHERE game_id=? ORDER BY pg_id', (game['game_id'],)).fetchall()
    tmap = {t['team_id']: t for t in teams}
    asym = (game['map'] not in SYMMETRIC_MAPS) or (game['format'] or '').endswith(':asym') or game['source_id'] in selected   # win-only source: per team
    if not asym and not all(team_complete(t) for t in teams):
        asym = True                                            # a truncated side: the complete side is still ranked within itself
    groups = [[t['team_id']] for t in teams] if asym else [[t['team_id'] for t in teams]]
    home_map = game['map'] in HOME_MAPS and not asym            # both sides in one lobby on a base map: the defenders are the home side
    out = []
    for g in groups:
        if not all(team_complete(tmap[t]) for t in g):
            for r in rows:
                if r['team_id'] in g:
                    out.append((r['pg_id'], None, None, 0, None, None, None, 'team_incomplete', None))
            continue
        gkey = f"{game['game_id']}:" + '+'.join(str(t) for t in g)
        members = [r for r in rows if r['team_id'] in g]
        flagged = {}
        for r in members:
            note = (r['note'] or '').lower()
            if r['pg_id'] in drop:
                flagged[r['pg_id']] = 'late_join_suspect'
            elif r['obscured']:
                flagged[r['pg_id']] = 'obscured'
            elif 'not_in_totals' in note or 'spectator' in note:
                flagged[r['pg_id']] = 'not_in_totals'
            elif r['kills'] is None or r['dmg'] is None:
                flagged[r['pg_id']] = 'unreadable'
            elif r['kills'] == 0 and r['dmg'] == 0:
                flagged[r['pg_id']] = 'afk'
        core = [r for r in members if r['pg_id'] not in flagged]
        if len(core) >= MIN_GROUP:
            mk, md = median([r['kills'] for r in core]), median([r['dmg'] for r in core])
            for r in core:
                if r['kills'] < PARTIAL_FRAC * mk and r['dmg'] < PARTIAL_FRAC * md:
                    flagged[r['pg_id']] = 'partial'
            core = [r for r in members if r['pg_id'] not in flagged]
        if len(core) < MIN_GROUP:
            for r in members:
                out.append((r['pg_id'], None, gkey, len(core), None, None, None, flagged.get(r['pg_id'], 'group_too_small'), None))
            continue
        zk = zs([r['kills'] for r in core]); zd = zs([r['dmg'] for r in core])
        zc = [clamp(v, -WINSOR_Z, WINSOR_Z) for v in zs([0.5 * a + 0.5 * b for a, b in zip(zk, zd)])]
        for r, a, b, c in zip(core, zk, zd, zc):
            note = r['note'] or ''
            if note.startswith('canonical='):               # repo games carry a_cemaster's hand-verified identity
                canon_name = note[len('canonical='):]
                pk = keyed.get(exact_key(canon_name), ('MATCH', canon_name))[1]
            else:
                pk = keyed.get(exact_key(r['handle']), ('UNKNOWN', r['handle']))[1]
            out.append((r['pg_id'], pk, gkey, len(core), a, b, c, None, (1 if tmap[r['team_id']]['role'] == 'defender' else 0) if home_map else None))
        for r in members:
            if r['pg_id'] in flagged:
                out.append((r['pg_id'], None, gkey, len(core), None, None, None, flagged[r['pg_id']], None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since'); ap.add_argument('--until'); ap.add_argument('--label', default='')
    a = ap.parse_args()
    con = raid_db.connect()
    params = dict(since=a.since, until=a.until, label=a.label, sos=True, symmetric_maps=sorted(SYMMETRIC_MAPS), home_maps=sorted(HOME_MAPS),
                  grouping='both sides of a two-sided board are one lobby on every map (a_cemaster 2026-10-24: mirrored fairzones, equal numbers); '
                           'win-only sources and :asym formats per team; a truncated side leaves the other side ranked within itself; '
                           'on home_maps a fitted per-map home term is taken off the defending side', min_group=MIN_GROUP,
                  winsor_z=WINSOR_Z, partial_frac=PARTIAL_FRAC, outlier_gap=OUTLIER_GAP, outlier_min_games=OUTLIER_MIN_GAMES, ovr_mean=OVR_MEAN, ovr_sd=OVR_SD, ovr_clamp=OVR_CLAMP,
                  result_selected='win-only sources (' + ', '.join(sorted(raid_db.RESULT_SELECTED_SOURCES)) + ') scored per team: within-team ranking only',
                  obscured='excluded from lobby statistics and ratings',
                  composite='0.5*z_kills+0.5*z_dmg re-standardized', eligible_status=['verified', 'kd_verified', 'consensus', 'partial'],
                  identity='ALIASES.md > CombinedLists > Roblox account (RobloxNames + RobloxCasing lookups) > I-l look-alike groups (account-backed spelling wins; two accounts stay split); casing from accounts/registry; see NameMergeReport.csv')
    run_id = raid_db.start_run(con, 'score', 'raid_score.py', params)
    keyed = resolve_all(con)
    selected = raid_db.result_selected(con)
    q = "SELECT * FROM games WHERE duplicate_of IS NULL AND verified_status IN ('verified','kd_verified','consensus','partial')"
    args = []
    if a.since: q += ' AND date >= ?'; args.append(a.since)
    if a.until: q += ' AND date <= ?'; args.append(a.until)
    games = con.execute(q + ' ORDER BY date, game_id', args).fetchall()
    con.execute('DELETE FROM z_scores WHERE run_id=?', (run_id,))

    def pass_scores(drop):
        """Score every eligible game, with the pg_ids in `drop` treated as late-join suspects (out of their lobby)."""
        per = collections.defaultdict(list); flags = collections.Counter(); scored_games = set(); grp = collections.defaultdict(list); zrows = []
        homes = collections.defaultdict(list)
        for g in games:
            for pg_id, pk, gkey, gn, zk, zd, zc, flag, home in score_game(con, g, keyed, drop, selected):
                zrows.append((g['game_id'], pg_id, pk, gkey, gn, zk, zd, zc, flag))
                if flag:
                    flags[flag] += 1
                else:
                    per[pk].append((g['game_id'], g['date'] or '', g['map'] or '', zc, zk, zd, gkey, pg_id)); scored_games.add(g['game_id'])
                    grp[gkey].append((pk, zc)); homes[gkey].append((pg_id, home))
        # home-side contrast per row: the home flag minus the lobby's home share, so the term moves the sides apart, not the lobby
        cmap = {}
        for gkey, hs in homes.items():
            known = [h for _, h in hs if h is not None]
            if known and 0 < sum(known) < len(known):
                frac = sum(known) / len(known)
                for pg_id, h in hs:
                    cmap[pg_id] = (h - frac) if h is not None else 0.0
        return per, flags, scored_games, grp, zrows, cmap

    def anova(values_by_player):
        multi = [v for v in values_by_player if len(v) >= 2]
        allv = [x for v in multi for x in v]; N = len(allv); K = len(multi)
        if K < 2 or N <= K:
            return 1.0, 0.5
        gm = mean(allv)
        msb = sum(len(v) * (mean(v) - gm) ** 2 for v in multi) / (K - 1)
        msw = sum((x - mean(v)) ** 2 for v in multi for x in v) / (N - K)
        n0 = (N - sum(len(v) ** 2 for v in multi) / N) / (K - 1)
        return msw, max((msb - msw) / n0, 0.05)

    def lobby_mean(gkey, pk, s, grp):
        o = [s[q] for q, _ in grp[gkey] if q != pk and q in s]
        return sum(o) / len(o) if o else 0.0

    def home_adj(v, h):
        """The home term's share of a row's z: h_map times the row's home contrast (0 outside two-sided HOME_MAPS boards)."""
        return h.get(v[2], 0.0) * cmap.get(v[7], 0.0)

    def sos_fit(k, per, grp):
        """Joint fit: s_i = shrink(mean over games of (z_ig - home_ig + mean of the other players' s in that lobby)), where the
        home term h_map is the least-squares excess of the defending side over what the ratings predict (HOME_MAPS, two-sided
        boards only); s and h are updated alternately until both settle."""
        s = {pk: 0.0 for pk in per}; h = {m: 0.0 for m in HOME_MAPS}
        total = sum(len(v) for v in per.values())
        for it in range(200):
            new = {}
            for pk, vs in per.items():
                vals = [v[3] - home_adj(v, h) + lobby_mean(v[6], pk, s, grp) for v in vs]
                n = len(vals); new[pk] = (sum(vals) / n) * n / (n + k)
            centre = sum(new[pk] * len(per[pk]) for pk in new) / total     # appearance-weighted: the average player-game is the lobby average
            new = {pk: v - centre for pk, v in new.items()}
            num = {m: 0.0 for m in HOME_MAPS}; den = {m: 0.0 for m in HOME_MAPS}
            for pk, vs in per.items():
                for v in vs:
                    c = cmap.get(v[7], 0.0)
                    if c and v[2] in num:
                        num[v[2]] += (v[3] - (new[pk] - lobby_mean(v[6], pk, new, grp))) * c; den[v[2]] += c * c
            hnew = {m: (num[m] / den[m] if den[m] else 0.0) for m in HOME_MAPS}
            delta = max([abs(new[pk] - s[pk]) for pk in new] + [abs(hnew[m] - h[m]) for m in HOME_MAPS]); s = new; h = hnew
            if delta < 1e-6:
                break
        return s, h, it + 1

    def solve(per, grp):
        """Shrinkage constants first on raw z, then re-estimated on lobby-adjusted values and the fit repeated."""
        var_w, var_b = anova([[v[3] for v in vs] for vs in per.values()])
        k = var_w / var_b
        for _ in range(2):
            s_sos, home, iters = sos_fit(k, per, grp)
            adj = {pk: [v[3] - home_adj(v, home) + lobby_mean(v[6], pk, s_sos, grp) for v in vs] for pk, vs in per.items()}
            var_w, var_b = anova(list(adj.values()))
            k = var_w / var_b
        s_sos, home, iters = sos_fit(k, per, grp)
        adj = {pk: [v[3] - home_adj(v, home) + lobby_mean(v[6], pk, s_sos, grp) for v in vs] for pk, vs in per.items()}
        return s_sos, adj, var_w, var_b, k, iters, home

    # pass 1 scores everything; a game more than OUTLIER_GAP below the median of the player's other lobby-adjusted games
    # (OUTLIER_MIN_GAMES or more) is a late join / partial game as far as the data can tell and is discarded from the
    # player and the lobby; pass 2 rescores without those rows (one pass only, so discards cannot cascade).
    per, flags, scored_games, grp, zrows, cmap = pass_scores(frozenset())
    s_sos, adj, var_w, var_b, k, iters, home = solve(per, grp)
    drop = {}
    for pk, vs in per.items():
        if len(vs) < OUTLIER_MIN_GAMES:
            continue
        ys = adj[pk]
        for i, v in enumerate(vs):
            gap = median(ys[:i] + ys[i + 1:]) - ys[i]
            if gap > OUTLIER_GAP and v[3] < 0:                     # and below the lobby average: a late joiner cannot be above it
                drop[v[7]] = (pk, v[3], ys[i] - v[3], gap)          # pg_id -> (player, pass-1 z, pass-1 lobby, gap)
    per, flags, scored_games, grp, zrows, cmap = pass_scores(frozenset(drop))
    s_sos, adj, var_w, var_b, k, iters, home = solve(per, grp)
    for game_id, pg_id, pk, gkey, gn, zk, zd, zc, flag in zrows:
        if flag == 'late_join_suspect':
            dpk, dz, dl, dg = drop[pg_id]                            # the pass-1 point stays on the row so the profile can show it
            con.execute('INSERT INTO z_scores(run_id,pg_id,game_id,player_key,group_key,group_n,z_kills,z_dmg,z_comp,flag,lobby_z,discard_gap) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (run_id, pg_id, game_id, dpk, gkey, gn, None, None, round(dz, 4), flag, round(dl, 4), round(dg, 3)))
        else:
            con.execute('INSERT INTO z_scores(run_id,pg_id,game_id,player_key,group_key,group_n,z_kills,z_dmg,z_comp,flag) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (run_id, pg_id, game_id, pk, gkey, gn, zk, zd, zc, flag))
    for pk, vs in per.items():
        for v in vs:
            # lobby_z carries the home term too, so z + lobby_z is always the game's value on the rating scale
            con.execute('UPDATE z_scores SET lobby_z=? WHERE run_id=? AND pg_id=?', (round(lobby_mean(v[6], pk, s_sos, grp) - home_adj(v, home), 4), run_id, v[7]))
    sd_b = math.sqrt(var_b)
    con.execute('DELETE FROM ratings WHERE run_id=?', (run_id,))
    res = {r['handle_key']: r for r in con.execute('SELECT * FROM handle_resolutions').fetchall()}
    n_rated = 0
    for pk, vs in per.items():
        n = len(vs)
        if n < MIN_RATED_GAMES:
            continue
        z = [v[3] for v in vs]; zm = mean(z); y = adj[pk]
        shr = zm * n / (n + k)                       # unadjusted (kept for comparison)
        zsos = s_sos[pk]                             # strength-of-schedule adjusted rating
        ovr = clamp(OVR_MEAN + OVR_SD * zsos / sd_b, *OVR_CLAMP)
        ovr_unadj = clamp(OVR_MEAN + OVR_SD * shr / sd_b, *OVR_CLAMP)
        ovr_raw = clamp(OVR_MEAN + OVR_SD * mean(y) / sd_b, *OVR_CLAMP)
        sig = OVR_SD / sd_b * math.sqrt(var_w * var_b / (n * var_b + var_w))
        bym = collections.defaultdict(list); bya = collections.defaultdict(list)
        for v, yv in zip(vs, y):
            bym[v[2]].append(v[3]); bya[v[2]].append(yv)
        def map_zs(m):
            """Map rating: shrunk mean of that map's lobby-adjusted values, toward the lobby average (maps stay independent)."""
            if not bya.get(m):
                return None
            n_m = len(bya[m]); return mean(bya[m]) * n_m / (n_m + k)
        def map_ovr(m):
            zs_m = map_zs(m)
            return None if zs_m is None else round(clamp(OVR_MEAN + OVR_SD * zs_m / sd_b, *OVR_CLAMP), 2)
        r = res.get(exact_key(pk))
        con.execute('''INSERT INTO ratings(run_id,player_key,canonical,resolution,n_games,n_maps,first_date,last_date,z_mean,z_sd,z_shrunk,zk_mean,zd_mean,
                       ovr,ovr_raw,ovr_sigma,n_warehouse,z_warehouse,n_docks,z_docks,n_ordana,z_ordana,ovr_warehouse,ovr_docks,ovr_ordana,
                       z_sos,ovr_unadj,zs_warehouse,zs_docks,zs_ordana,n_skydock,z_skydock,ovr_skydock,zs_skydock) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (run_id, pk, r['canonical'] if r and r['status'] == 'MATCH' else None, r['status'] if r else 'repo', n, len(bym),
                     min(v[1] for v in vs), max(v[1] for v in vs), zm, ssd(y), shr, mean([v[4] for v in vs]), mean([v[5] for v in vs]),
                     round(ovr, 2), round(ovr_raw, 2), round(sig, 2),
                     len(bym.get('Warehouse', [])), mean(bym['Warehouse']) if bym.get('Warehouse') else None,
                     len(bym.get('Docks', [])), mean(bym['Docks']) if bym.get('Docks') else None,
                     len(bym.get('Ordana', [])), mean(bym['Ordana']) if bym.get('Ordana') else None,
                     map_ovr('Warehouse'), map_ovr('Docks'), map_ovr('Ordana'),
                     round(zsos, 4), round(ovr_unadj, 2), map_zs('Warehouse'), map_zs('Docks'), map_zs('Ordana'),
                     len(bym.get('Skydock', [])), mean(bym['Skydock']) if bym.get('Skydock') else None, map_ovr('Skydock'), map_zs('Skydock')))
        n_rated += 1
    summary = dict(games_eligible=len(games), games_scored=len(scored_games), player_games_scored=sum(len(v) for v in per.values()),
                   players_rated=n_rated, players_ge5=sum(1 for v in per.values() if len(v) >= 5),
                   players_ge10=sum(1 for v in per.values() if len(v) >= 10), flags=dict(flags), discarded_outliers=len(drop),
                   var_within=round(var_w, 4), var_between=round(var_b, 4), shrink_k=round(k, 3), icc_1game=round(var_b / (var_b + var_w), 3),
                   sos_iterations=iters, sos='joint fit, appearance-weighted centring; z_sd and map ratings on lobby-adjusted values',
                   home_term={m: round(home[m], 4) for m in sorted(HOME_MAPS)},
                   resolutions=dict(con.execute('SELECT status, count(*) FROM handle_resolutions GROUP BY status').fetchall()))
    raid_db.finish_run(con, run_id, summary)
    con.commit()
    print(f'run {run_id} ({a.label or "all"}):', json.dumps(summary, indent=1))
    print('\nTop 25 by OVR (n>=5):')
    for r in con.execute('SELECT player_key, canonical, n_games, round(z_mean,2), round(z_sos,2), ovr, ovr_unadj, ovr_sigma FROM ratings WHERE run_id=? AND n_games>=5 ORDER BY ovr DESC LIMIT 25', (run_id,)).fetchall():
        print('  ', r[:])


if __name__ == '__main__':
    main()
