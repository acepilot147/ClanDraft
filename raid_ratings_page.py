"""Generate ratings.html - the data-only OVR site page (table, player profiles, match boards, board scanner).

  python -I raid_ratings_page.py

Reads the latest non-retired scoring run per label from raids.sqlite and embeds
everything inline (no server, same as list.html). The <style> block is copied
verbatim from list.html at generation time so the pages stay visually in sync.

Embedded tables:
  ROWS      one row per (run, player): OVR, tier, games, z, per-map OVR/games/shrunk z, per-side (Docks/Skydock attacker vs
            defender: n_da/z_da/ovr_da ...) ratings shrunk toward that side's average, clan, identity
  RUNS      per run: id, dates, scale constants, shrinkage constants, summary counts
  GAMES     per player: every scored game [game id, composite z, kills, dmg, side role, lobby z, 1 when discarded as a late-join suspect]  (z is per game, era-independent)
  GAMEMETA  per game id: [date, map, type, opponent clan, result, score L, score R, banner, match time, source url, status]
  BOARDS    per game id: the full leaderboard - teams (label, role, side, totals) and every printed row with its z / flag
  RESOLVE   handle (lower-case) -> player name, for every handle ever seen on a board (scans snap misreads to the nearest one)
  MAPSTATS  per map (and Docks side): mean / sd of kills and dmg over scored rows, for projections

Tier letters use the OVR thresholds from generate.js. The Clan column is a label
only (CombinedLists.csv clan for matched names, VAK for regular Docks defenders);
no hand rating enters any number on the page. The scanner tab posts screenshots
to scan-proxy/server.js (which holds the API key); everything after the read is
deterministic table lookup in the page.
"""
import os, sys, csv, json, re, collections, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # survives python -I
import raid_db

ROOT = raid_db.ROOT
OUT = os.path.join(ROOT, 'ratings.html')
PROXIES = ['https://clandraft-scan.onrender.com/read', 'http://localhost:8787/read']


def tier(ovr):
    return 'X' if ovr >= 97 else 'S+' if ovr >= 93 else 'S' if ovr >= 89 else 'A' if ovr >= 80 else 'B' if ovr >= 70 else 'C' if ovr >= 65 else 'D'


def latest_runs(con):
    runs = {}
    for r in con.execute("SELECT * FROM runs WHERE kind='score' ORDER BY run_id").fetchall():
        s = json.loads(r['summary_json'] or '{}')
        if 'retired' in s or not s:
            continue
        p = json.loads(r['params_json'])
        runs[p.get('label') or f"run{r['run_id']}"] = (r, p, s)
    return runs


def clan_labels(con):
    latest = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'CombinedLists.csv'), newline='', encoding='utf-8-sig')):
        y = int(r['Year'] or 0)
        if r['Clan'] and (r['LegacyName'] not in latest or y > latest[r['LegacyName']][0]):
            latest[r['LegacyName']] = (y, r['Clan'])
    docks = collections.defaultdict(lambda: [0, 0])
    for r in con.execute('''SELECT z.player_key, t.role FROM z_scores z JOIN player_games pg USING(pg_id) JOIN teams t ON t.team_id=pg.team_id
                            JOIN games g ON g.game_id=z.game_id WHERE z.flag IS NULL AND g.map='Docks' ''').fetchall():
        docks[r['player_key']][0 if r['role'] == 'defender' else 1] += 1
    sky = collections.defaultdict(lambda: [0, 0])
    for r in con.execute('''SELECT z.player_key, t.role FROM z_scores z JOIN player_games pg USING(pg_id) JOIN teams t ON t.team_id=pg.team_id
                            JOIN games g ON g.game_id=z.game_id WHERE z.flag IS NULL AND g.map='Skydock' ''').fetchall():
        sky[r['player_key']][0 if r['role'] == 'defender' else 1] += 1
    for r in []:
        docks[r['player_key']][0 if r['role'] == 'defender' else 1] += 1
    return latest, docks, sky


def build(con):
    runs = latest_runs(con)
    latest, docks, sky = clan_labels(con)
    rows = []; meta = {}
    for label, (run, params, summ) in runs.items():
        k = summ.get('shrink_k', 1.0)
        # per-side ratings: a raider and a defender on Docks / Skydock are drawn from different populations, so a player's
        # record in each role is shrunk toward that side's average appearance (not toward the global 0), and an unknown
        # player on a side counts as that side's average
        role_y = collections.defaultdict(list)                     # (player, map, role) -> lobby-adjusted game values
        for rr in con.execute('''SELECT z.player_key, g.map, t.role, z.z_comp, z.lobby_z FROM z_scores z JOIN player_games pg USING(pg_id)
                                 JOIN teams t ON t.team_id=pg.team_id JOIN games g ON g.game_id=z.game_id
                                 WHERE z.run_id=? AND z.flag IS NULL AND g.map IN ('Docks','Skydock') AND t.role IN ('attacker','defender')''', (run['run_id'],)).fetchall():
            role_y[(rr['player_key'], rr['map'], rr['role'])].append(rr['z_comp'] + (rr['lobby_z'] or 0.0))
        role_mean = {}
        for m_ in ('Docks', 'Skydock'):
            for role_ in ('defender', 'attacker'):
                allv = [v for (pk_, mm, ro), vs in role_y.items() if mm == m_ and ro == role_ for v in vs]
                role_mean[m_ + '/' + role_] = round(sum(allv) / len(allv), 4) if allv else 0.0
        sd_b_run = math.sqrt(summ.get('var_between', 0.44)); cap_run = params['ovr_clamp'][1]
        ovr_mean_run = params.get('ovr_mean', 80.0); ovr_sd_run = params.get('ovr_sd', 6.0)
        meta[label] = {'run_id': run['run_id'], 'created': run['created_at'][:10], 'git': run['git_rev'], 'games': summ.get('games_scored'),
                       'player_games': summ.get('player_games_scored'), 'players': summ.get('players_rated'), 'ge5': summ.get('players_ge5'),
                       'icc': summ.get('icc_1game'), 'ovr_mean': params.get('ovr_mean'), 'ovr_sd': params.get('ovr_sd'), 'ovr_cap': params['ovr_clamp'][1], 'outlier_gap': params.get('outlier_gap'), 'discarded': summ.get('discarded_outliers'),
                       'k': k, 'var_w': summ.get('var_within'), 'sd_b': round(math.sqrt(summ.get('var_between', 0.44)), 4),
                       'since': params.get('since') or '', 'until': params.get('until') or '', 'role_mean': role_mean}
        for r in con.execute('SELECT * FROM ratings WHERE run_id=? ORDER BY ovr DESC, n_games DESC', (run['run_id'],)).fetchall():
            d = docks.get(r['player_key'], [0, 0])
            clan = latest.get(r['canonical'], (0, ''))[1] if r['canonical'] else ''
            if not clan and d[0] + d[1] >= 2 and d[0] > d[1]:
                clan = 'VAK'
            sk = sky.get(r['player_key'], [0, 0])
            if not clan and sk[0] + sk[1] >= 2 and sk[0] > sk[1]:
                clan = 'RoA'
            row = {'run': label, 'name': r['player_key'], 'ovr': round(r['ovr'], 1), 'tier': tier(r['ovr']), 'games': r['n_games'],
                   'z': round(r['z_mean'], 2), 'zs': round(r['z_sos'] if r['z_sos'] is not None else r['z_shrunk'], 3), 'sigma': round(r['ovr_sigma'], 2),
                   'zsd': round(r['z_sd'], 3) if r['z_sd'] is not None else None, 'ovr_unadj': round(r['ovr_unadj'], 1) if r['ovr_unadj'] is not None else None,
                   'last': (r['last_date'] or '')[:10], 'first': (r['first_date'] or '')[:10], 'clan': clan,
                   'id': {'MATCH': 'match', 'CANDIDATE': 'candidate', 'repo': 'match'}.get(r['resolution'], 'unknown')}
            for key, m in (('d', 'docks'), ('w', 'warehouse'), ('o', 'ordana'), ('s', 'skydock')):
                n_m = r['n_' + m]
                row[key] = n_m
                row['ovr_' + key] = round(r['ovr_' + m], 1) if r['ovr_' + m] is not None else None
                zs_m = r['zs_' + m] if r['zs_' + m] is not None else (r['z_' + m] * n_m / (n_m + k) if r['z_' + m] is not None else None)
                row['z_' + key] = round(zs_m, 3) if zs_m is not None else None
            for key, m in (('d', 'Docks'), ('s', 'Skydock')):
                for role_, suf in (('attacker', 'a'), ('defender', 'd')):
                    vs = role_y.get((r['player_key'], m, role_)); rk_ = key + suf; mu = role_mean[m + '/' + role_]
                    row['n_' + rk_] = len(vs) if vs else 0
                    if vs:
                        zs_r = mu + (sum(vs) / len(vs) - mu) * len(vs) / (len(vs) + k)
                        row['z_' + rk_] = round(zs_r, 3); row['ovr_' + rk_] = round(min(cap_run, ovr_mean_run + ovr_sd_run * zs_r / sd_b_run), 1)
                    else:
                        row['z_' + rk_] = None; row['ovr_' + rk_] = None
            rows.append(row)
    base = runs['all-years'][0]['run_id'] if 'all-years' in runs else max(v[0]['run_id'] for v in runs.values())
    # games + full boards (every printed row, scored or not) for eligible, non-duplicate games
    gmeta = {}; boards = {}
    keyed = {r['handle_key']: (r['canonical'] or r['handle']) for r in con.execute('SELECT handle_key, handle, canonical FROM handle_resolutions').fetchall()}
    zmap = {r['pg_id']: (r['z_comp'], r['flag'], r['player_key'], r['lobby_z']) for r in con.execute('SELECT pg_id, z_comp, flag, player_key, lobby_z FROM z_scores WHERE run_id=?', (base,)).fetchall()}
    gq = '''SELECT g.*, i.audit_result res, i.url src FROM games g LEFT JOIN images i ON i.image_id=g.image_id
            WHERE g.duplicate_of IS NULL AND g.verified_status IN ('verified','kd_verified','consensus','partial') ORDER BY g.date, g.game_id'''
    games = collections.defaultdict(list)
    for g in con.execute(gq).fetchall():
        gid = g['game_id']
        gmeta[gid] = [g['date'] or '', g['map'] or '', g['event_type'] or '', raid_db.clean_clan(g['opp_clan']) or '', g['res'] or '', g['score_left'], g['score_right'],
                      g['banner'] or '', g['match_time'] or '', g['src'] or '', g['verified_status'], g['ext_id'] or '']
        teams = con.execute('SELECT * FROM teams WHERE game_id=? ORDER BY team_id', (gid,)).fetchall()
        tidx = {t['team_id']: i for i, t in enumerate(teams)}
        b = {'t': [[t['label'] or '', t['role'] or '', t['side'] or '', t['declared_size'], t['tot_kills'], t['tot_deaths'], t['tot_dmg'], t['tot_heals'], t['tot_caps'], t['truncated']] for t in teams], 'p': []}
        for r in con.execute('SELECT * FROM player_games WHERE game_id=? ORDER BY pg_id', (gid,)).fetchall():
            if r['obscured']:
                continue                                    # a_cemaster: unreadable names are neither tracked nor shown
            z, flag, pk, lz = zmap.get(r['pg_id'], (None, 'unscored', None, None))
            if pk is None and not r['obscured']:
                note = r['note'] or ''
                pk = note[len('canonical='):] if note.startswith('canonical=') else keyed.get(r['handle'].strip().lower(), r['handle'])
            b['p'].append([tidx[r['team_id']], r['handle'], pk or '', r['kills'], r['deaths'], r['dmg'], r['heals'], r['caps'],
                           round(z, 3) if z is not None else None, flag or ''])
            if z is not None and pk and (not flag or flag == 'late_join_suspect'):
                games[pk].append([gid, round(z, 3), r['kills'], r['dmg'], teams[tidx[r['team_id']]]['role'] or '', round(lz, 3) if lz is not None else 0.0, 1 if flag else 0])
        boards[gid] = b
    resolve = dict(keyed)
    for name in set(keyed.values()):               # a player's current (canonical) name resolves to them even when no board printed it (an identity refresh renamed the account)
        k = (name or '').strip().lower()
        if k and k not in resolve:
            resolve[k] = name
    by = collections.defaultdict(lambda: {'k': [], 'd': []})
    for r in con.execute('''SELECT g.map, t.role, pg.kills, pg.dmg FROM z_scores z JOIN player_games pg USING(pg_id) JOIN teams t ON t.team_id=pg.team_id
                            JOIN games g ON g.game_id=z.game_id WHERE z.run_id=? AND z.flag IS NULL AND g.map IS NOT NULL''', (base,)).fetchall():
        key = r['map'] + ('/' + r['role'] if r['map'] in ('Docks', 'Skydock') and r['role'] in ('attacker', 'defender') else '')
        by[key]['k'].append(r['kills']); by[key]['d'].append(r['dmg'])
    def ms(x):
        m = sum(x) / len(x); return [round(m, 1), round(math.sqrt(sum((v - m) ** 2 for v in x) / len(x)), 1)]
    mapstats = {key: {'k': ms(v['k']), 'd': ms(v['d']), 'n': len(v['k'])} for key, v in by.items()}
    # pace: Warehouse / Ordana output scales with the end score total (points, finished games only), Docks with the match timer (minutes)
    CAP = {'Warehouse': 1200, 'Ordana': 1000}      # finished hardpoint / foundry games: a side reached the cap
    def clock(g):
        if g['map'] in CAP and g['score_left'] is not None and g['score_right'] is not None and max(g['score_left'], g['score_right']) >= CAP[g['map']] and g['score_left'] + g['score_right'] > 0:
            return (g['score_left'] + g['score_right']) / 1000.0, 'per 1000 pts'
        if g['map'] == 'Docks':
            m = re.match(r'^(\d{1,2}):(\d{2})', g['match_time'] or '')
            if m and int(m.group(1)) >= 5:
                return int(m.group(1)) + int(m.group(2)) / 60.0, 'per minute'
        return None, None
    rate = collections.defaultdict(lambda: {'k': [], 'd': [], 'len': []}); seen_len = set()
    for r in con.execute('''SELECT g.game_id, g.map, g.score_left, g.score_right, g.match_time, t.role, pg.kills, pg.dmg FROM z_scores z JOIN player_games pg USING(pg_id)
                            JOIN teams t ON t.team_id=pg.team_id JOIN games g ON g.game_id=z.game_id WHERE z.run_id=? AND z.flag IS NULL AND g.map IS NOT NULL''', (base,)).fetchall():
        L, unit = clock(r)
        if not L:
            continue
        key = r['map'] + ('/' + r['role'] if r['map'] in ('Docks', 'Skydock') and r['role'] in ('attacker', 'defender') else '')
        rate[key]['k'].append(r['kills'] / L); rate[key]['d'].append(r['dmg'] / L); rate[key]['unit'] = unit
        if (key, r['game_id']) not in seen_len:
            seen_len.add((key, r['game_id'])); rate[key]['len'].append(L)
    for key, v in rate.items():
        ln = sorted(v['len'])
        mapstats.setdefault(key, {})['rate'] = {'k': ms(v['k']), 'd': ms(v['d']), 'unit': v['unit'], 'len': round(ln[len(ln) // 2], 2),
                                                'len_p10': round(ln[len(ln) // 10], 2), 'len_p90': round(ln[9 * len(ln) // 10], 2), 'n': len(v['k'])}
    base_label = next(l for l, v in runs.items() if v[0]['run_id'] == base)
    byname = {row['name']: row for row in rows if row['run'] == base_label}
    outcome = outcome_models(con, base, resolve, lambda pk, mp, role: rating_for(byname.get(pk), mp, role, meta[base_label]['role_mean']))
    # single-game scale: percentile breakpoints (0..100) of lobby-adjusted game values per era, so a game reads as "P97"
    for label, (run, params, summ) in runs.items():
        ys = []
        for pk, gs in games.items():
            for g in gs:
                if g[6]:
                    continue
                dt = gmeta[g[0]][0]
                if (not params.get('since') or dt >= params['since']) and (not params.get('until') or dt <= params['until']):
                    ys.append(g[1] + g[5])
        ys.sort()
        meta[label]['gameq'] = [round(ys[min(len(ys) - 1, int(round(q / 100 * (len(ys) - 1))))], 3) for q in range(101)] if ys else []
        meta[label]['n_game_values'] = len(ys)
    return rows, meta, dict(games), gmeta, boards, resolve, mapstats, outcome


CAPS = {'Warehouse': 1200, 'Ordana': 1000, 'Docks': 1800, 'Skydock': 900}


MK = {'Docks': 'd', 'Warehouse': 'w', 'Ordana': 'o', 'Skydock': 's'}


def rating_for(p, mp, role, role_mean):
    """The rating a scan (and the outcome fit) uses for a player row p on map mp: on Docks / Skydock the record in this
    role, else on this map, else overall; an unknown player is the average of that side (0 on symmetric maps). Same rule
    as the scan tab and the bot."""
    sided = mp in ('Docks', 'Skydock') and role in ('attacker', 'defender')
    if sided and p and p.get('z_' + MK[mp] + role[0]) is not None and p.get('n_' + MK[mp] + role[0], 0) > 0:
        return p['z_' + MK[mp] + role[0]]
    mk = MK.get(mp)
    if p and mk and p.get('z_' + mk) is not None and p.get(mk, 0) > 0:
        return p['z_' + mk]
    if p:
        return p['zs']
    return role_mean.get(mp + '/' + role, 0.0) if sided else 0.0


def mat_inv(M):
    """Inverse of a small square matrix by Gauss-Jordan (None when singular)."""
    n = len(M); A = [list(map(float, M[i])) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(A[r][i])); A[i], A[piv] = A[piv], A[i]
        if abs(A[i][i]) < 1e-12:
            return None
        f = A[i][i]; A[i] = [v / f for v in A[i]]
        for r in range(n):
            if r != i and A[r][i]:
                g = A[r][i]; A[r] = [a - g * b for a, b in zip(A[r], A[i])]
    return [row[n:] for row in A]


def logit_cov(X, w, beta, ridge=0.05):
    """Covariance of the logistic coefficients: inverse of the ridged Hessian logit_fit converged on."""
    k = len(beta); rows = [[1.0] + list(x) for x in X]
    H = [[0.0] * k for _ in range(k)]
    for x in rows:
        eta = sum(b * v for b, v in zip(beta, x)); pr = 1 / (1 + math.exp(-eta)); v = pr * (1 - pr)
        for i in range(k):
            for j in range(k):
                H[i][j] += v * x[i] * x[j]
    for i in range(1, k):
        H[i][i] += ridge
    return mat_inv(H) or [[0.0] * k for _ in range(k)]


def side_of(t, mp):
    lab = ((t['label'] or '') + ' ' + (t['sublabel'] or '')).upper()
    if mp == 'Ordana':
        return 'A' if ('ASTARTES' in lab or 'IMPERIALIS' in lab) else ('B' if ('XENOS' in lab or 'INSURGENT' in lab) else None)
    if mp in ('Docks', 'Skydock'):
        return 'A' if t['role'] == 'defender' else ('B' if t['role'] == 'attacker' else None)
    return 'A' if t['side'] == 'left' else 'B'


def logit_fit(X, w, ridge=0.05):
    """Logistic regression by Newton steps on columns X (list of feature lists, no intercept column) with a small ridge
    on the slopes so a sparse home-clan indicator cannot run away. Returns [intercept, coef...]."""
    k = len(X[0]) + 1
    beta = [0.0] * k
    rows = [[1.0] + list(x) for x in X]
    for _ in range(100):
        grad = [0.0] * k; H = [[0.0] * k for _ in range(k)]
        for x, y in zip(rows, w):
            eta = sum(b * v for b, v in zip(beta, x)); pr = 1 / (1 + math.exp(-eta)); v = pr * (1 - pr)
            for i in range(k):
                grad[i] += (y - pr) * x[i]
                for j in range(k):
                    H[i][j] += v * x[i] * x[j]
        for i in range(1, k):
            grad[i] -= ridge * beta[i]; H[i][i] += ridge
        # solve H d = grad (Gaussian elimination)
        A = [H[i][:] + [grad[i]] for i in range(k)]
        for i in range(k):
            piv = max(range(i, k), key=lambda r: abs(A[r][i])); A[i], A[piv] = A[piv], A[i]
            if abs(A[i][i]) < 1e-12:
                return beta
            for r in range(k):
                if r != i:
                    f = A[r][i] / A[i][i]
                    for cidx in range(i, k + 1):
                        A[r][cidx] -= f * A[i][cidx]
        d = [A[i][k] / A[i][i] for i in range(k)]
        beta = [b + dd for b, dd in zip(beta, d)]
        if sum(abs(dd) for dd in d) < 1e-9:
            break
    return beta


HOME = {'Docks': ('VAK', ('VAKTOVIAN',)), 'Ordana': ('SOL', ('SOL IMPERIALIS', 'IMPERIALIS'))}   # home clan on side A, by label


def outcome_models(con, run_id, resolve, rating_for_pk):
    """Per map: P(side A wins) as a logistic in the team-strength difference (mean rating of A minus B, each player's
    rating as the scan would use it: per-side record on Docks / Skydock, else per map, else overall), the loser's
    expected score (linear in |diff|), the game length, and the strength-difference clusters behind them. Coefficient
    covariances and the loser-score residual spread are kept so a consumer can put error bars on a projection.
    Side A = left panel on Warehouse, the Astartes faction on Ordana, the defenders on Docks. Finished games on the
    capped scoring system only, both panels complete, and only sources that record losses as well as wins: a victory
    channel (sources.result_selected) is a win-only sample and says nothing about win probability."""
    selected = raid_db.result_selected(con)
    rows = []
    for g in con.execute('''SELECT * FROM games WHERE duplicate_of IS NULL AND verified_status IN ('verified','kd_verified','consensus','partial')
                            AND map IS NOT NULL AND score_left IS NOT NULL AND score_right IS NOT NULL''').fetchall():
        if g['source_id'] in selected:
            continue
        mp = g['map']; cap = CAPS.get(mp)
        teams = con.execute('SELECT * FROM teams WHERE game_id=? ORDER BY team_id', (g['game_id'],)).fetchall()
        sc = [g['score_left'], g['score_right']]
        if not cap or len(teams) != 2 or any(t['truncated'] for t in teams) or max(sc) != cap or min(sc) >= cap:
            continue
        info = []
        for t, s_ in zip(teams, sc):
            pl = con.execute('SELECT handle, obscured FROM player_games WHERE team_id=?', (t['team_id'],)).fetchall()
            zs = [rating_for_pk(resolve.get(x['handle'].strip().lower(), x['handle']), mp, t['role']) for x in pl if not x['obscured']]
            if len(zs) < 5:
                break
            info.append((side_of(t, mp), sum(zs) / len(zs), s_))
        if len(info) != 2 or None in [i[0] for i in info] or info[0][0] == info[1][0]:
            continue
        a, b = (info if info[0][0] == 'A' else info[::-1])
        m = re.match(r'^(\d{1,2}):(\d{2})', g['match_time'] or '')
        ta = [t for t in teams if side_of(t, mp) == 'A'][0]; lab = ((ta['label'] or '') + ' ' + (ta['sublabel'] or '')).upper()
        # home clan on side A: VAK defending its own base (a real Defense, not VAK-vs-VAK training), Sol as the Astartes on Ordana
        home = 1.0 if (mp in HOME and any(k in lab for k in HOME[mp][1]) and not (mp == 'Docks' and (g['event_type'] or '') == 'Defense Training')) else 0.0
        rows.append(dict(diff=a[1] - b[1], a_win=a[2] > b[2], loser=min(a[2], b[2]), total=a[2] + b[2], home=home,
                         mins=(int(m.group(1)) + int(m.group(2)) / 60.0) if m and int(m.group(1)) >= 5 else None, map=mp))
    out = {}
    for mp, cap in CAPS.items():
        R = [r for r in rows if r['map'] == mp]
        if len(R) < 20:
            continue
        d = [r['diff'] for r in R]; w = [1.0 if r['a_win'] else 0.0 for r in R]; hm = [r['home'] for r in R]
        if mp in HOME and 0 < sum(hm) < len(hm):
            la, lb, lh = logit_fit([[x, h] for x, h in zip(d, hm)], w)      # [intercept, strength slope, home-clan effect]
            lcov = logit_cov([[x, h] for x, h in zip(d, hm)], w, [la, lb, lh])
        else:
            la, lb = logit_fit([[x] for x in d], w); lh = 0.0
            c2 = logit_cov([[x] for x in d], w, [la, lb])
            lcov = [[c2[0][0], c2[0][1], 0.0], [c2[1][0], c2[1][1], 0.0], [0.0, 0.0, 0.0]]
        n_home = int(sum(hm)); home_rate = (sum(y for y, h in zip(w, hm) if h) / n_home) if n_home else None
        away_rate = (sum(y for y, h in zip(w, hm) if not h) / (len(hm) - n_home)) if len(hm) - n_home else None
        ad = [abs(x) for x in d]; ls = [r['loser'] for r in R]; ma = sum(ad) / len(ad); ml = sum(ls) / len(ls)
        sxx = sum((x - ma) ** 2 for x in ad); slope = sum((x - ma) * (y - ml) for x, y in zip(ad, ls)) / sxx if sxx else 0.0
        icpt = ml - slope * ma; n_r = len(R)
        rse = math.sqrt(sum((y - icpt - slope * x) ** 2 for x, y in zip(ad, ls)) / max(n_r - 2, 1))
        lxx = mat_inv([[n_r, sum(ad)], [sum(ad), sum(x * x for x in ad)]]) or [[0.0, 0.0], [0.0, 0.0]]
        lcov_loser = [[rse * rse * v for v in row] for row in lxx]
        qs = sorted(d); edges = [qs[int(len(qs) * q)] for q in (0.2, 0.4, 0.6, 0.8)]
        bins = collections.defaultdict(list)
        for r in R:
            bins[sum(r['diff'] > e for e in edges)].append(r)
        mins = [r['mins'] for r in R if r['mins']]
        out[mp] = {'cap': cap, 'n': len(R), 'side_a': {'Warehouse': 'left panel', 'Ordana': 'Astartes', 'Docks': 'defenders', 'Skydock': 'Avians'}.get(mp, 'left panel'),
                   'logit': [round(la, 4), round(lb, 4)], 'home_logit': round(lh, 4), 'home_clan': HOME[mp][0] if mp in HOME else None,
                   'home_labels': list(HOME[mp][1]) if mp in HOME else [], 'n_home': n_home,
                   'home_rate': round(home_rate, 3) if home_rate is not None else None, 'away_rate': round(away_rate, 3) if away_rate is not None else None,
                   'sources': 'two-sided sources only (victory channels left out)', 'base_rate': round(sum(w) / len(w), 3),
                   'loser': [round(ml - slope * ma, 1), round(slope, 1)], 'loser_sd': round(math.sqrt(sum((y - ml) ** 2 for y in ls) / len(ls)), 1),
                   'logit_cov': [[round(v, 5) for v in row] for row in lcov], 'loser_rse': round(rse, 1),
                   'loser_cov': [[round(v, 4) for v in row] for row in lcov_loser],
                   'minutes': round(sum(mins) / len(mins), 2) if mins else None,
                   'bins': [{'lo': round(min(r['diff'] for r in B), 2), 'hi': round(max(r['diff'] for r in B), 2), 'n': len(B),
                             'win': round(sum(r['a_win'] for r in B) / len(B), 2), 'loser': round(sum(r['loser'] for r in B) / len(B)),
                             'total': round(sum(r['total'] for r in B) / len(B))} for k, B in sorted(bins.items())]}
    return out


EXTRA_CSS = """
#scan-unrated { width: 74px; padding: 3px 6px; font: inherit; color: var(--text); background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.14); border-radius: 6px; }

  td.games, td.z, td.sigma, td.last { color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }
  td.z { color: var(--text); }
  td.sigma { color: var(--faint); }
  td.map { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
  td.map small { font-weight: 400; font-size: 9.5px; color: var(--faint); margin-left: 4px; }
  td.map.empty { color: var(--faint); font-weight: 400; }
  td.id { font-size: 9px; letter-spacing: 1px; text-transform: uppercase; color: var(--faint); }
  td.id.match { color: var(--cyan); }
  td.id.candidate { color: var(--gold); }
  tr.prov td.ovr, tr.prov td.tier .tier-pill { opacity: 0.45; }
  tbody tr.row, tbody tr.grow { cursor: pointer; }
  tbody tr.grow.discarded td { opacity: .45; text-decoration: line-through; }
  .note-line { font-size: 10px; color: var(--faint); margin: -6px 0 12px; line-height: 1.5; }
  .note-line b { color: var(--muted); font-weight: 400; }
  .tabs { display: flex; gap: 4px; max-width: 1180px; margin: 10px auto 0; padding: 0 20px; }
  .tab { all: unset; cursor: pointer; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; color: var(--muted);
         padding: 9px 14px; border: 1px solid var(--line); border-bottom: none; border-radius: 3px 3px 0 0; background: var(--bg2); }
  .tab.active { color: var(--cyan); background: var(--surface); border-color: var(--line2); }
  .panel { display: none; } .panel.active { display: block; }
  .modal-bg { position: fixed; inset: 0; background: rgba(3,4,8,0.78); display: none; z-index: 20; }
  .modal-bg.open { display: block; }
  .modal { position: fixed; top: 4vh; left: 50%; transform: translateX(-50%); width: min(1180px, 96vw); max-height: 92vh; overflow: auto;
           background: var(--surface); border: 1px solid var(--line2); border-radius: 4px; z-index: 21; display: none; padding: 18px 20px 20px; }
  .modal.open { display: block; }
  .modal-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 18px; margin-bottom: 6px; }
  .modal-head .pname { font-family: var(--display); font-size: 26px; font-weight: 600; letter-spacing: 1px; }
  .modal-head .povr { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .modal-head .pci { color: var(--muted); font-size: 11px; }
  .modal-close { all: unset; cursor: pointer; position: absolute; top: 12px; right: 16px; color: var(--muted); font-size: 18px; padding: 4px 8px; }
  .modal-close:hover { color: var(--cyan); }
  .back { all: unset; cursor: pointer; font-size: 9px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; display: inline-block; }
  .back:hover { color: var(--cyan); }
  .facts { display: flex; flex-wrap: wrap; gap: 6px 22px; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--faint); margin-bottom: 14px; }
  .facts b { color: var(--text); font-weight: 400; letter-spacing: 0; text-transform: none; font-size: 12px; }
  .facts a { color: var(--cyan); text-decoration: none; letter-spacing: 0; text-transform: none; font-size: 12px; }
  .chart-wrap { border: 1px solid var(--line); border-radius: 3px; padding: 10px 8px 4px; background: var(--bg); position: relative; margin-bottom: 14px; }
  .chart-title { font-size: 9px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--faint); padding: 0 10px 6px; }
  .chart-title b { color: var(--muted); font-weight: 400; }
  svg text { font-family: var(--mono); }
  .tip { position: fixed; pointer-events: none; background: var(--surface2); border: 1px solid var(--line2); border-radius: 3px; padding: 6px 9px;
         font-size: 11px; color: var(--text); z-index: 30; display: none; white-space: nowrap; }
  .tip small { color: var(--muted); }
  .glist { max-height: 34vh; }
  .glist table, .board table { font-size: 11.5px; }
  .glist td { padding: 6px 10px; }
  .board td { padding: 5px 7px; font-size: 11px; }
  .board thead th button { padding: 8px 7px; font-size: 8.5px; letter-spacing: 1px; }
  td.gz { font-variant-numeric: tabular-nums; text-align: right; font-weight: 700; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  .board-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 860px) { .board-grid { grid-template-columns: 1fr; } }
  .board .team-title { margin: 4px 0 6px; }
  .board tr.me td { background: rgba(100,209,193,0.10); }
  .board td.pl { font-family: var(--display); font-size: 13px; letter-spacing: 0.3px; cursor: pointer; max-width: 170px; overflow: hidden; text-overflow: ellipsis; }
  .board td.pl:hover { color: var(--cyan); }
  .board td.pl small { font-family: var(--mono); font-size: 9px; color: var(--faint); margin-left: 5px; letter-spacing: 0; }
  .board tr.tot td { color: var(--muted); border-top: 1px solid var(--line2); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }
  .board td.flag { font-size: 9px; color: var(--faint); letter-spacing: 0.5px; text-transform: uppercase; }
  .scan-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 760px) { .scan-grid { grid-template-columns: 1fr; } }
  .drop { border: 1px dashed var(--line2); border-radius: 3px; min-height: 220px; display: flex; align-items: center; justify-content: center;
          text-align: center; color: var(--faint); font-size: 11px; letter-spacing: 1px; text-transform: uppercase; padding: 14px; background: var(--bg); position: relative; }
  .drop.over { border-color: var(--cyan); color: var(--cyan); }
  .drop img { max-width: 100%; max-height: 360px; display: block; }
  .drop input[type=file] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .scan-side .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
  .btn { all: unset; cursor: pointer; background: var(--cyan); color: var(--bg); font-size: 10px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; padding: 9px 14px; border-radius: 3px; }
  .btn[disabled] { opacity: 0.4; cursor: default; }
  .status { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--faint); min-height: 14px; }
  .status.err { color: #f08a8a; text-transform: none; letter-spacing: 0; font-size: 11px; }
  .team-title { font-family: var(--display); font-size: 15px; letter-spacing: 1px; text-transform: uppercase; margin: 14px 0 6px; }
  .team-title small { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 1px; margin-left: 10px; }
  td.proj { text-align: right; font-variant-numeric: tabular-nums; }
  td.proj small { color: var(--faint); margin-left: 4px; font-size: 9.5px; }
  td.unr { color: var(--faint); font-style: italic; }
  .teamsum { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--faint); margin: 6px 0 2px; }
  th.rm, td.rm { width: 24px; text-align: center; padding-left: 2px; padding-right: 2px; }
  td.rm button { all: unset; cursor: pointer; color: var(--faint); font-size: 15px; line-height: 1; padding: 2px 6px; border-radius: 3px; }
  td.rm button:hover { color: #f08a8a; background: rgba(240, 138, 138, 0.12); }
  .removed { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--faint); margin: 10px 0 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .removed button { all: unset; cursor: pointer; font-family: var(--mono); font-size: 10.5px; letter-spacing: 0; text-transform: none; color: var(--muted); border: 1px solid var(--line2); border-radius: 3px; padding: 2px 7px; }
  .removed button:hover { color: var(--cyan); border-color: var(--cyan); }
  .removed button.all { text-transform: uppercase; letter-spacing: 1px; font-size: 9.5px; }
  .teamsum b { color: var(--text); font-weight: 400; letter-spacing: 0; text-transform: none; font-size: 12px; }
  @media (max-width: 640px) { td.last, td.id, td.sigma, td.z { display: none; } }
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#05060b">
<title>Raid Ratings | raids.sqlite</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>&#127919;</text></svg>">
</head>
<body>
__STYLE__

<div class="topbar">
  <div class="brand">Raid<em>Ratings</em></div>
  <div class="src">raids.sqlite &middot; data-only OVR &middot; <span id="total-count"></span> players rated &middot; <span id="run-info"></span></div>
</div>

<div class="tabs">
  <button type="button" class="tab active" data-tab="ratings">Ratings</button>
  <button type="button" class="tab" data-tab="scan">Scan a board</button>
</div>

<main class="wrap">
<section class="panel active" id="panel-ratings">
  <div class="controls">
    <div class="search-box">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="search" placeholder="Search player or clan&hellip;" autocomplete="off">
    </div>
    <select id="filter-run" aria-label="Era"></select>
    <select id="filter-games" aria-label="Minimum games">
      <option value="1">1+ games</option>
      <option value="5" selected>5+ games</option>
      <option value="10">10+ games</option>
      <option value="20">20+ games</option>
    </select>
    <select id="filter-tier" aria-label="Filter by tier">
      <option value="">All tiers</option>
    </select>
    <select id="filter-id" aria-label="Identity">
      <option value="">All identities</option>
      <option value="match">Known names</option>
      <option value="candidate">Candidates</option>
      <option value="unknown">Unresolved</option>
    </select>
    <button type="button" class="btn-clear" id="btn-clear">Clear filters</button>
  </div>

  <p class="count-line" id="visible-count"></p>
  <p class="note-line">OVR comes from scoreboard data only: each game's kills and damage are z-scored within the lobby
  (within each side on Docks), averaged per player, shrunk toward the mean by the data's own noise ratio, and placed on
  a scale where the average lobby participant is <b id="scale-mean"></b> and one between-player spread is <b id="scale-sd"></b>
  points, capped at <b id="scale-cap"></b> (97+ stays hand-assigned). Map columns apply the same formula to that map's games alone, with
  the game count beside each. <b>&plusmn;</b> is the rating's standard error. Dimmed rows have fewer than 5 games. No hand rating is used.
  Click a row for the player's profile, then any game for its full board.</p>

  <div class="table-shell">
    <table>
      <thead>
        <tr id="head-row"></tr>
      </thead>
      <tbody id="body"></tbody>
    </table>
  </div>
</section>

<section class="panel" id="panel-scan">
  <div class="controls">
    <div class="scan-side" style="flex:1 1 100%">
      <div class="row">
        <select id="scan-run" aria-label="Era"></select>
        <select id="scan-map" aria-label="Map">
          <option value="Docks">Docks</option>
          <option value="Warehouse">Warehouse</option>
          <option value="Ordana">Ordana</option>
          <option value="Skydock">Skydock</option>
        </select>
        <button type="button" class="btn" id="btn-read" disabled>Read board</button>
        <span class="status" id="scan-status" style="flex:1 1 240px">Paste a screenshot (Ctrl+V), drop one here, or pick a file.</span>
      </div>
    </div>
  </div>
  <div class="scan-grid">
    <div>
      <div class="drop" id="drop"><span id="drop-text">Drop / paste a scoreboard screenshot<br>or click to choose a file</span><input type="file" id="file" accept="image/*"></div>
    </div>
    <div>
      <p class="note-line">The board is read once by Claude through the site's reader service, names and sides only. Everything after
      that is a projection from the players' histories: each handle resolves to its rating, the two teams' mean ratings give a win
      probability, a projected final score and the game's length, and each player's expected kills and damage follow from their
      expected z in this room over that length. Unrated players count as __UNRATED__ OVR, a less experienced player rather than the lobby average, unless the result is told otherwise (the box above the teams).</p>
      <div id="scan-out"></div>
    </div>
  </div>
</section>
</main>

<div class="modal-bg" id="modal-bg"></div>
<div class="modal" id="modal" role="dialog" aria-modal="true">
  <button type="button" class="modal-close" id="modal-close" aria-label="Close">&times;</button>
  <div id="modal-body"></div>
</div>
<div class="tip" id="tip"></div>

<script>
  var ROWS = __ROWS__;
  var RUNS = __RUNS__;
  var GAMES = __GAMES__;
  var GAMEMETA = __GAMEMETA__;
  var BOARDS = __BOARDS__;
  var RESOLVE = __RESOLVE__;
  var MAPSTATS = __MAPSTATS__;
  var PROXIES = __PROXIES__;
  var OUTCOME = __OUTCOME__;

  var TIER_COLOR = { S: "#e8c878", X: "#b58cf0", A: "#4fc6f0", B: "#5fd6a0", C: "#8a98a6", D: "#5c6975" };
  function tierColor(t) { return TIER_COLOR[t.charAt(0)] || "#8a98a6"; }
  function tierOf(o) { return o >= 97 ? "X" : o >= 93 ? "S+" : o >= 89 ? "S" : o >= 80 ? "A" : o >= 70 ? "B" : o >= 65 ? "C" : "D"; }
  var TIER_ORDER = ["S+", "S", "X", "A", "B", "C", "D"];
  var MAPS = [["d", "Docks"], ["w", "Warehouse"], ["o", "Ordana"], ["s", "Skydock"]];

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmt(x, d) { return x === null || x === undefined ? "—" : Number(x).toFixed(d === undefined ? 1 : d); }
  function n0(x) { return x === null || x === undefined ? "—" : Number(x).toLocaleString(); }

  // ---------- indexes
  var runLabels = Object.keys(RUNS);
  var byRun = {};          // run -> lower(name) -> row
  var pct = {};            // run -> { all: sorted OVRs (n>=5), d/w/o: sorted map OVRs (n_map>=3) }
  runLabels.forEach(function (r) { byRun[r] = {}; pct[r] = { all: [] }; MAPS.forEach(function (m) { pct[r][m[0]] = []; }); });
  ROWS.forEach(function (p) {
    byRun[p.run][p.name.toLowerCase()] = p;
    if (p.games >= 5) pct[p.run].all.push(p.ovr);
    MAPS.forEach(function (m) { if (p[m[0]] >= 3 && p["ovr_" + m[0]] !== null) pct[p.run][m[0]].push(p["ovr_" + m[0]]); });
  });
  runLabels.forEach(function (r) { Object.keys(pct[r]).forEach(function (k) { pct[r][k].sort(function (a, b) { return a - b; }); }); });
  function percentile(arr, v) {
    if (!arr.length) return null;
    var lo = 0, hi = arr.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (arr[mid] < v) lo = mid + 1; else hi = mid; }
    var below = lo; hi = arr.length; var lo2 = lo;
    while (lo2 < hi) { var m2 = (lo2 + hi) >> 1; if (arr[m2] <= v) lo2 = m2 + 1; else hi = m2; }
    return Math.round(100 * (below + 0.5 * (lo2 - below)) / arr.length);
  }
  // ---------- nearest known handle. A model reading a 10-px condensed font confuses glyphs far more than it invents letters, so
  // a read snaps to the closest handle ever seen on a board under a glyph-aware edit distance: look-alike swaps (I/l/1, O/0,
  // S/5, B/8, Z/2) are nearly free, similar shapes (C/G, E/F, U/V, ...) cost half, a dropped or doubled repeated letter costs
  // half, rn~m / vv~w merges cost 0.75, anything else a full edit. Accepted within an allowance that grows with length when no
  // other player is as close; ties go to whoever plays more. An exact hit on a one-off identity yields to a look-alike regular
  // (the database holds ODOCY beside OD0CY). Identical to agentic/namematch.py in the Avian bot - keep the two in step.
  var NM = { CLASSES: ["1il|!", "0o", "5s", "8b", "2z"],
             SIMILAR: ["cg", "ef", "uv", "mn", "kx", "pr", "pb", "bd", "qo", "qd", "4a", "7t", "3e", "6g", "9g", "9q", "co", "go", "rn", "ij", "yv", "aq", "ao", "hn"],
             MERGES: [["rn", "m"], ["vv", "w"], ["cl", "d"], ["nn", "m"], ["ri", "n"]],
             NEAR_FREE: 0.2, HALF: 0.5, MERGE: 0.75, FULL: 1, PREFIX_MIN: 7, LOOKALIKE_MAX: 0.5, REGULAR_MIN: 5, REGULAR_RATIO: 4 };
  var FOLDMAP = {}; NM.CLASSES.forEach(function (cls) { for (var i = 0; i < cls.length; i++) FOLDMAP[cls[i]] = cls[cls.length - 1]; });
  var SIMSET = {}; NM.SIMILAR.forEach(function (p) { SIMSET[p] = true; SIMSET[p[1] + p[0]] = true; });
  function fold(s) { var o = ""; for (var i = 0; i < s.length; i++) o += FOLDMAP[s[i]] || s[i]; return o; }
  function bagOf(s) { var b = {}; for (var i = 0; i < s.length; i++) b[s[i]] = (b[s[i]] || 0) + 1; return b; }
  function bagDiff(x, y) { var d = 0, c; for (c in x) d += Math.abs(x[c] - (y[c] || 0)); for (c in y) if (!(c in x)) d += y[c]; return d; }
  function subCost(a, b) {
    if (a === b) return 0;
    var fa = FOLDMAP[a] || a, fb = FOLDMAP[b] || b;
    if (fa === fb) return NM.NEAR_FREE;
    if (SIMSET[fa + fb] || SIMSET[a + b]) return NM.HALF;
    return NM.FULL;
  }
  function hdist(a, b, cutoff) {           // glyph-weighted Damerau-Levenshtein, read a vs known b; > cutoff once it cannot fit
    var la = a.length, lb = b.length, INF = cutoff + 1, H = NM.HALF, F = NM.FULL, i, j, t;
    if (Math.abs(la - lb) * H > cutoff) return INF;
    var D = []; for (i = 0; i <= la; i++) { D.push(new Array(lb + 1)); }
    D[0][0] = 0;
    for (i = 1; i <= la; i++) D[i][0] = D[i - 1][0] + (i > 1 && a[i - 1] === a[i - 2] ? H : F);
    for (j = 1; j <= lb; j++) D[0][j] = D[0][j - 1] + (j > 1 && b[j - 1] === b[j - 2] ? H : F);
    for (i = 1; i <= la; i++) {
      var ca = a[i - 1], row = D[i], up = D[i - 1], up2 = i > 1 ? D[i - 2] : null, bestRow = row[0];
      for (j = 1; j <= lb; j++) {
        var cb = b[j - 1], v = up[j - 1] + subCost(ca, cb);
        t = up[j] + (i > 1 && ca === a[i - 2] ? H : F); if (t < v) v = t;
        t = row[j - 1] + (j > 1 && cb === b[j - 2] ? H : F); if (t < v) v = t;
        if (up2 && j > 1 && ca === b[j - 2] && cb === a[i - 2] && ca !== cb) { t = up2[j - 2] + F; if (t < v) v = t; }
        for (var m = 0; m < NM.MERGES.length; m++) {
          var x = NM.MERGES[m][0], y = NM.MERGES[m][1];
          if (j > 1 && ca === y && b.substr(j - 2, 2) === x) { t = up[j - 2] + NM.MERGE; if (t < v) v = t; }
          if (up2 && cb === y && a.substr(i - 2, 2) === x) { t = up2[j - 1] + NM.MERGE; if (t < v) v = t; }
        }
        row[j] = v; if (v < bestRow) bestRow = v;
      }
      if (bestRow > cutoff) return INF;
    }
    return D[la][lb];
  }
  function allowance(n) { return n <= 4 ? 0.5 : n <= 6 ? 1 : n <= 9 ? 1.25 : n <= 13 ? 1.5 : 2; }
  var HANDLES = Object.keys(RESOLVE).map(function (k) { var f = fold(k); return { key: k, f: f, bag: bagOf(f), name: RESOLVE[k] }; });
  var BYFOLD = {}; HANDLES.forEach(function (e) { (BYFOLD[e.f] = BYFOLD[e.f] || {})[e.name] = true; });
  var GAMES_RUN = byRun["all-years"] ? "all-years" : runLabels[0];
  function gamesOf(name) { var p = byRun[GAMES_RUN][name.toLowerCase()]; return p ? p.games : 0; }
  function lookalikeRegular(h, name) {
    var g = gamesOf(name), best = null;
    HANDLES.forEach(function (e) {
      if (e.name === name || Math.abs(e.key.length - h.length) > 1) return;
      var go = gamesOf(e.name);
      if (go < NM.REGULAR_MIN || go < NM.REGULAR_RATIO * Math.max(g, 1)) return;
      var dd = hdist(h, e.key, NM.LOOKALIKE_MAX);
      if (dd <= NM.LOOKALIKE_MAX + 1e-9 && (best === null || dd < best.dist || (dd === best.dist && go > gamesOf(best.name)))) best = { name: e.name, key: e.key, dist: dd, how: "regular" };
    });
    return best;
  }
  function nearestHandle(handle) {
    var raw = handle.trim().toLowerCase();
    if (RESOLVE[raw]) { var hit0 = { name: RESOLVE[raw], key: raw, dist: 0, how: "known" }; return lookalikeRegular(raw, hit0.name) || hit0; }
    var h = raw, truncated = /(\.\.\.|\u2026)$/.test(h);
    h = h.replace(/[.\u2026]+$/, "").trim();
    if (!h) return null;
    if (RESOLVE[h]) { var hit = { name: RESOLVE[h], key: h, dist: 0, how: "known" }; return lookalikeRegular(h, hit.name) || hit; }
    var names = BYFOLD[fold(h)] ? Object.keys(BYFOLD[fold(h)]) : [];
    if (names.length === 1) return { name: names[0], key: h, dist: NM.NEAR_FREE, how: "look-alike" };
    if (truncated || h.length >= NM.PREFIX_MIN) {
      var hits = {};
      HANDLES.forEach(function (e) { if (e.key.length > h.length && e.key.indexOf(h) === 0) hits[e.name] = true; });
      var hn = Object.keys(hits);
      if (hn.length === 1) return { name: hn[0], key: h + "...", dist: 0, how: "prefix" };
      if (truncated) return null;
    }
    var allow = allowance(h.length), bag = bagOf(fold(h)), best = [];
    HANDLES.forEach(function (e) {
      if (Math.abs(e.f.length - h.length) * NM.HALF > allow) return;
      if (bagDiff(bag, e.bag) * 0.25 > allow + 1e-9) return;
      var dd = hdist(h, e.key, allow);
      if (dd <= allow + 1e-9) best.push({ dist: dd, key: e.key, name: e.name });
    });
    if (!best.length) return null;
    best.sort(function (p, q) { return p.dist - q.dist || gamesOf(q.name) - gamesOf(p.name) || (p.key < q.key ? -1 : p.key > q.key ? 1 : 0); });
    var b0 = best[0], rival = null, how = "nearest";
    for (var r = 1; r < best.length; r++) if (best[r].name !== b0.name) { rival = best[r]; break; }
    if (rival && rival.dist - b0.dist < 0.3) {
      if (gamesOf(b0.name) <= gamesOf(rival.name) * 2) return null;         // two players equally close, neither clearly the regular
      how = "nearest?";
    }
    return { name: b0.name, key: b0.key, dist: b0.dist, how: how };
  }
  function resolveHandle(h) {
    var m = nearestHandle(h);
    return m ? { name: m.name, how: m.how, key: m.key, dist: m.dist } : { name: h.trim(), how: "new" };
  }

  // ---------- ratings table
  var COLUMNS = [
    { key: "ovr",   label: "OVR",       numeric: true },
    { key: "tier",  label: "Tier",      numeric: false, sortFn: function (p) { return TIER_ORDER.indexOf(p.tier); } },
    { key: "name",  label: "Name",      numeric: false },
    { key: "games", label: "Games",     numeric: true },
    { key: "z",     label: "Z avg",     numeric: true },
    { key: "sigma", label: "±",     numeric: true },
    { key: "ovr_d", label: "Docks",     numeric: true, sortFn: function (p) { return p.ovr_d === null ? -Infinity : p.ovr_d; }, tie: "z_d" },
    { key: "ovr_w", label: "Warehouse", numeric: true, sortFn: function (p) { return p.ovr_w === null ? -Infinity : p.ovr_w; }, tie: "z_w" },
    { key: "ovr_o", label: "Ordana",    numeric: true, sortFn: function (p) { return p.ovr_o === null ? -Infinity : p.ovr_o; }, tie: "z_o" },
    { key: "ovr_s", label: "Skydock",   numeric: true, sortFn: function (p) { return p.ovr_s === null ? -Infinity : p.ovr_s; }, tie: "z_s" },
    { key: "last",  label: "Last game", numeric: true },
    { key: "clan",  label: "Clan",      numeric: false },
    { key: "id",    label: "ID",        numeric: false }
  ];
  var sortKey = "ovr", sortDir = -1;
  var els = {};
  ["search", "filter-run", "filter-games", "filter-tier", "filter-id", "btn-clear", "head-row", "body", "visible-count", "total-count", "run-info",
   "scale-mean", "scale-sd", "scale-cap", "modal", "modal-bg", "modal-close", "modal-body", "tip", "scan-run", "scan-map", "btn-read",
   "scan-status", "drop", "drop-text", "file", "scan-out"].forEach(function (id) { els[id] = document.getElementById(id); });

  runLabels.forEach(function (r) {
    [els["filter-run"], els["scan-run"]].forEach(function (sel) { var o = document.createElement("option"); o.value = r; o.textContent = r; sel.appendChild(o); });
  });
  var defaultRun = runLabels.indexOf("2025-2026") !== -1 ? "2025-2026" : runLabels[0];
  els["filter-run"].value = defaultRun; els["scan-run"].value = defaultRun;
  TIER_ORDER.forEach(function (t) {
    if (!ROWS.some(function (p) { return p.tier === t; })) return;
    var o = document.createElement("option"); o.value = t; o.textContent = t + " tier"; els["filter-tier"].appendChild(o);
  });

  function renderHead() {
    var html = '<th class="rank"></th>';
    COLUMNS.forEach(function (col) {
      var isSorted = sortKey === col.key;
      html += '<th class="' + (col.numeric ? "num " : "") + (isSorted ? "sorted" : "") + '" data-key="' + col.key + '"><button type="button">' + col.label;
      if (isSorted) html += '<span class="arrow">' + (sortDir === 1 ? "↑" : "↓") + "</span>";
      html += "</button></th>";
    });
    els["head-row"].innerHTML = html;
    var ths = els["head-row"].querySelectorAll("th[data-key] button");
    for (var i = 0; i < ths.length; i++) {
      ths[i].addEventListener("click", function () {
        var key = this.parentElement.getAttribute("data-key");
        if (sortKey === key) sortDir = -sortDir;
        else { sortKey = key; sortDir = key === "name" || key === "clan" || key === "id" ? 1 : -1; }
        render();
      });
    }
  }
  function sortRows(rows) {
    var col = COLUMNS.filter(function (c) { return c.key === sortKey; })[0];
    var getVal = col.sortFn || function (p) { return p[sortKey]; };
    var tie = col.tie || "zs";
    return rows.slice().sort(function (a, b) {
      var av = getVal(a), bv = getVal(b);
      if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      var at = a[tie] === null || a[tie] === undefined ? -Infinity : a[tie];
      var bt = b[tie] === null || b[tie] === undefined ? -Infinity : b[tie];
      return (bt - at) || (b.zs - a.zs) || (b.games - a.games);
    });
  }
  function filterRows() {
    var q = els.search.value.trim().toLowerCase(), run = els["filter-run"].value, minGames = Number(els["filter-games"].value);
    var tier = els["filter-tier"].value, id = els["filter-id"].value;
    return ROWS.filter(function (p) {
      if (p.run !== run || p.games < minGames) return false;
      if (tier && p.tier !== tier) return false;
      if (id && p.id !== id) return false;
      if (q && p.name.toLowerCase().indexOf(q) === -1 && p.clan.toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }
  function renderBody(rows) {
    if (!rows.length) { els.body.innerHTML = '<tr><td colspan="13"><div class="empty-state">No players match these filters</div></td></tr>'; return; }
    var html = "";
    rows.forEach(function (p, i) {
      var color = tierColor(p.tier);
      html += '<tr class="row ' + (p.games < 5 ? "prov" : "") + '" data-name="' + esc(p.name) + '">';
      html += '<td class="rank">' + (i + 1) + "</td>";
      html += '<td class="ovr" style="color:' + color + '">' + p.ovr.toFixed(1) + "</td>";
      html += '<td class="tier"><span class="tier-pill" style="color:' + color + '">' + esc(p.tier) + "</span></td>";
      html += '<td class="name">' + esc(p.name) + "</td>";
      html += '<td class="games">' + p.games + "</td>";
      html += '<td class="z">' + (p.z > 0 ? "+" : "") + p.z.toFixed(2) + "</td>";
      html += '<td class="sigma">±' + p.sigma.toFixed(1) + "</td>";
      MAPS.forEach(function (m) {
        var v = p["ovr_" + m[0]];
        if (v === null) { html += '<td class="map empty">&mdash;</td>'; return; }
        html += '<td class="map" style="color:' + tierColor(tierOf(v)) + '">' + v.toFixed(1) + "<small>&times;" + p[m[0]] + "</small></td>";
      });
      html += '<td class="last">' + (p.last || "&mdash;") + "</td>";
      html += '<td class="clan' + (p.clan ? "" : " empty") + '">' + (p.clan ? esc(p.clan) : "&mdash;") + "</td>";
      html += '<td class="id ' + p.id + '">' + p.id + "</td>";
      html += "</tr>";
    });
    els.body.innerHTML = html;
    var trs = els.body.querySelectorAll("tr.row");
    for (var i = 0; i < trs.length; i++) trs[i].addEventListener("click", function () { openProfile(this.getAttribute("data-name"), els["filter-run"].value); });
  }
  function render() {
    renderHead();
    var sorted = sortRows(filterRows());
    renderBody(sorted);
    var run = RUNS[els["filter-run"].value];
    var inRun = ROWS.filter(function (p) { return p.run === els["filter-run"].value; }).length;
    els["visible-count"].innerHTML = "showing <b>" + sorted.length + "</b> of " + inRun + " players in " + esc(els["filter-run"].value) +
      " &middot; " + run.games + " games &middot; " + run.player_games + " player-games";
    els["total-count"].textContent = inRun;
    els["run-info"].textContent = "run " + run.run_id + " (" + run.created + ", " + run.git + ")";
    els["scale-mean"].textContent = run.ovr_mean; els["scale-sd"].textContent = run.ovr_sd; els["scale-cap"].textContent = run.ovr_cap;
  }
  els.search.addEventListener("input", render);
  ["filter-run", "filter-games", "filter-tier", "filter-id"].forEach(function (id) { els[id].addEventListener("change", render); });
  els["btn-clear"].addEventListener("click", function () { els.search.value = ""; els["filter-games"].value = "5"; els["filter-tier"].value = ""; els["filter-id"].value = ""; render(); });

  // ---------- tabs
  var tabs = document.querySelectorAll(".tab");
  for (var t = 0; t < tabs.length; t++) tabs[t].addEventListener("click", function () {
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle("active", tabs[i] === this);
    document.getElementById("panel-ratings").classList.toggle("active", this.getAttribute("data-tab") === "ratings");
    document.getElementById("panel-scan").classList.toggle("active", this.getAttribute("data-tab") === "scan");
  });

  // ---------- per-table sorting (scan teams, match boards): th[data-key] headers, tr[data-s-<key>] values
  function makeSortable(table) {
    var ths = table.querySelectorAll("thead th[data-key]");
    for (var i = 0; i < ths.length; i++) ths[i].addEventListener("click", function () {
      var key = this.getAttribute("data-key"), tbody = table.querySelector("tbody");
      var dir = this.classList.contains("sorted") && this.getAttribute("data-dir") === "desc" ? "asc" : "desc";
      var all = table.querySelectorAll("thead th[data-key]");
      for (var j = 0; j < all.length; j++) { all[j].classList.remove("sorted"); all[j].removeAttribute("data-dir"); var a = all[j].querySelector(".arrow"); if (a) a.remove(); }
      this.classList.add("sorted"); this.setAttribute("data-dir", dir);
      this.querySelector("button").insertAdjacentHTML("beforeend", '<span class="arrow">' + (dir === "asc" ? "\u2191" : "\u2193") + "</span>");
      var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr[data-s-" + key + "]"));
      var fixed = Array.prototype.slice.call(tbody.querySelectorAll("tr.tot"));
      rows.sort(function (ra, rb) {
        var va = ra.getAttribute("data-s-" + key), vb = rb.getAttribute("data-s-" + key);
        var na = parseFloat(va), nb = parseFloat(vb), num = !isNaN(na) && !isNaN(nb);
        if (va === "" && vb !== "") return 1; if (vb === "" && va !== "") return -1;
        var c = num ? na - nb : va.toLowerCase().localeCompare(vb.toLowerCase());
        return dir === "asc" ? c : -c;
      });
      rows.forEach(function (r, k) { var rk = r.querySelector("td.rank"); if (rk) rk.textContent = k + 1; tbody.appendChild(r); });
      fixed.forEach(function (r) { tbody.appendChild(r); });
    });
  }

  // ---------- modal plumbing
  function openModal(html) { els["modal-body"].innerHTML = html; els.modal.classList.add("open"); els["modal-bg"].classList.add("open"); els.modal.scrollTop = 0; }
  function closeModal() { els.modal.classList.remove("open"); els["modal-bg"].classList.remove("open"); els.tip.style.display = "none"; }
  els["modal-close"].addEventListener("click", closeModal);
  els["modal-bg"].addEventListener("click", closeModal);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });
  function gameOvr(z, run) { return run.ovr_mean + run.ovr_sd * z / run.sd_b; }
  function gamePct(y, run) {            // percentile of a lobby-adjusted single-game value among all games in the era
    var q = run.gameq; if (!q || !q.length) return null;
    var lo = 0, hi = q.length - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (q[mid] < y) lo = mid + 1; else hi = mid; }
    return Math.max(0, Math.min(99, lo - (lo > 0 && q[lo] > y ? 1 : 0)));
  }
  function pctColor(pc) { return pc >= 95 ? "#e8c878" : pc >= 80 ? "#64d1c1" : pc >= 40 ? "#f7fbf9" : "#8496ad"; }
  function inEra(meta, run) { return (!run.since || meta[0] >= run.since) && (!run.until || meta[0] <= run.until); }
  function quantile(sorted, q) {
    if (!sorted.length) return null;
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  // ---------- profile
  function openProfile(name, runLabel) {
    var run = RUNS[runLabel], p = byRun[runLabel][name.toLowerCase()];
    if (!p) return;
    var games = (GAMES[name] || []).filter(function (g) { return inEra(GAMEMETA[g[0]], run); });
    var ci = 1.96 * p.sigma, lo = p.ovr - ci, hi = Math.min(run.ovr_cap, p.ovr + ci);
    var pAll = p.games >= 5 ? percentile(pct[runLabel].all, p.ovr) : null;
    var color = tierColor(p.tier);
    var html = '<div class="modal-head"><span class="pname">' + esc(p.name) + '</span>' +
      '<span class="povr" style="color:' + color + '">' + p.ovr.toFixed(1) + '</span><span class="tier-pill" style="color:' + color + '">' + esc(p.tier) + '</span>' +
      '<span class="pci">95% interval ' + fmt(lo) + ' – ' + fmt(hi) + (p.ovr + ci > run.ovr_cap ? ' (capped)' : '') + '</span></div>';
    html += '<div class="facts">' +
      '<span>Percentile <b>' + (pAll === null ? 'n/a (under 5 games)' : 'P' + pAll + ' \u00b7 top ' + (100 - pAll) + '%') + '</b></span>' +
      '<span>Games <b>' + p.games + '</b></span><span>Rating z <b>' + (p.zs > 0 ? '+' : '') + p.zs.toFixed(2) + '</b></span>' +
      (p.ovr_unadj !== null && p.ovr_unadj !== undefined ? '<span>Unadjusted <b>' + p.ovr_unadj.toFixed(1) + '</b></span>' : '') +
      '<span>Era <b>' + esc(runLabel) + '</b></span><span>Span <b>' + esc(p.first || '?') + ' → ' + esc(p.last || '?') + '</b></span>' +
      '<span>Clan <b>' + (p.clan ? esc(p.clan) : '—') + '</b></span><span>Identity <b>' + p.id + '</b></span></div>';
    html += '<div class="chart-wrap"><div class="chart-title">Games on the rating scale (lobby-adjusted) \u00b7 <b>dots</b> games, hollow at the edge when a game outruns the scale, dashed red when discarded as a suspected late join \u00b7 <b>box</b> middle half \u00b7 <b>bar</b> rating with 95% interval \u00b7 <b>P</b> percentile among rated players</div>' + boxChart(p, games, run, runLabel) + '</div>';
    html += '<p class="note-line">Lobby is the mean rating of the other players in that game\'s group (both teams of a two-sided board, own team in victory-channel games), less the map\'s home-side term for the defenders on Docks / Skydock; Adjusted = Z + Lobby is what the game says about the player once the room is accounted for; Game is where that single game ranks among all ' + (run.n_game_values || 0).toLocaleString() + ' player-games of this era (P99 = top 1%). Single games are not ratings: a rating is the shrunk average of many of them. A struck-through game sat more than ' + run.outlier_gap + ' z below the median of the other games of this player and is discarded as a suspected late join (boards carry no time-played column): it counts neither for the player nor for the lobby. Click a game for its full board.</p>';
    html += '<div class="table-shell glist"><table><thead><tr><th><button type="button">Date</button></th><th><button type="button">Map</button></th><th><button type="button">Event</button></th><th><button type="button">Opponent</button></th><th><button type="button">Result</button></th><th class="num"><button type="button">Kills</button></th><th class="num"><button type="button">DMG</button></th><th class="num"><button type="button">Z</button></th><th class="num"><button type="button">Lobby</button></th><th class="num"><button type="button">Adjusted</button></th><th class="num"><button type="button">Game</button></th></tr></thead><tbody>';
    games.slice().reverse().forEach(function (g) {
      var m = GAMEMETA[g[0]], adj = g[1] + g[5], gp = gamePct(adj, run);
      html += '<tr class="grow' + (g[6] ? ' discarded' : '') + '" data-gid="' + g[0] + '"' + (g[6] ? ' title="discarded as a suspected late join: more than ' + run.outlier_gap + ' z below the median of the other games of this player"' : '') + '><td>' + esc(m[0]) + '</td><td>' + esc(m[1]) + ((m[1] === 'Docks' || m[1] === 'Skydock') && g[4] ? ' <small style="color:var(--faint)">' + esc(g[4]) + '</small>' : '') + '</td><td>' + esc(m[2]) + '</td><td>' + esc(m[3] || '\u2014') + '</td><td>' + esc(m[4] || '\u2014') + '</td>' +
        '<td class="num">' + g[2] + '</td><td class="num">' + n0(g[3]) + '</td><td class="num">' + (g[1] > 0 ? '+' : '') + g[1].toFixed(2) + '</td><td class="num" title="mean rating of the others in the lobby">' + (g[5] > 0 ? '+' : '') + g[5].toFixed(2) + '</td><td class="gz" style="color:' + (adj >= 0 ? 'var(--cyan)' : 'var(--muted)') + '">' + (adj > 0 ? '+' : '') + adj.toFixed(2) + '</td><td class="num" style="color:' + pctColor(gp) + '" title="percentile among all games in this era">P' + gp + '</td></tr>';
    });
    html += '</tbody></table></div>';
    openModal(html);
    bindTips(els["modal-body"]);
    var trs = els["modal-body"].querySelectorAll("tr.grow");
    for (var i = 0; i < trs.length; i++) trs[i].addEventListener("click", function () { openMatch(Number(this.getAttribute("data-gid")), p.name, runLabel); });
  }

  // ---------- match board
  function openMatch(gid, highlight, runLabel) {
    var m = GAMEMETA[gid], b = BOARDS[gid], run = RUNS[runLabel];
    if (!m || !b) return;
    var html = '<button type="button" class="back" id="back-btn">← ' + (highlight ? esc(highlight) : 'close') + '</button>';
    html += '<div class="modal-head"><span class="pname">' + esc(m[1] || 'Match') + '</span><span class="pci" style="font-size:13px;color:var(--text)">' + esc(m[0]) + '</span>' +
      (m[5] !== null && m[6] !== null ? '<span class="povr" style="font-size:22px">' + m[5] + ' <span style="color:var(--faint);font-size:14px">vs</span> ' + m[6] + '</span>' : '') + '</div>';
    html += '<div class="facts"><span>Event <b>' + esc(m[2] || '—') + (m[3] ? ' vs ' + esc(m[3]) : '') + '</b></span>' +
      (m[4] ? '<span>Result <b>' + esc(m[4]) + '</b></span>' : '') + (m[7] ? '<span>Banner <b>' + esc(m[7]) + '</b></span>' : '') +
      (m[8] ? '<span>Match time <b>' + esc(m[8]) + '</b></span>' : '') + '<span>Read <b>' + esc(m[10]) + '</b></span>' +
      (m[11] ? '<span>Ref <b>' + esc(m[11]) + '</b></span>' : '') + (m[9] ? '<span>Source <a href="' + esc(m[9]) + '" target="_blank" rel="noopener">screenshot ↗</a></span>' : '') + '</div>';
    html += '<div class="board board-grid">';
    b.t.forEach(function (team, ti) {
      var rows = b.p.filter(function (r) { return r[0] === ti; });
      html += '<div><div class="team-title">' + esc(team[0] || team[2]) + '<small>' + esc(team[2]) + (team[1] && team[1] !== 'unknown' ? ' · ' + esc(team[1]) : '') + (team[3] ? ' · [' + team[3] + ']' : '') + (team[9] ? ' · cut off' : '') + '</small></div>';
      html += '<div class="table-shell" style="max-height:none"><table><thead><tr><th class="rank"></th><th data-key="name"><button type="button">Player</button></th><th class="num" data-key="k"><button type="button">K</button></th><th class="num" data-key="d"><button type="button">D</button></th><th class="num" data-key="dmg"><button type="button">DMG</button></th><th class="num" data-key="heals"><button type="button">Heals</button></th><th class="num" data-key="caps"><button type="button">Caps</button></th><th class="num" data-key="z"><button type="button">Z</button></th><th class="num" data-key="ovr"><button type="button">OVR</button></th></tr></thead><tbody>';
      rows.forEach(function (r, i) {
        var pk = r[2], rated = pk ? byRun[runLabel][pk.toLowerCase()] : null, me = highlight && pk && pk.toLowerCase() === highlight.toLowerCase();
        var sv = function (v) { return v === null || v === undefined ? "" : v; };
        html += '<tr class="' + (me ? 'me' : '') + '" data-s-name="' + esc(pk || r[1]) + '" data-s-k="' + sv(r[3]) + '" data-s-d="' + sv(r[4]) + '" data-s-dmg="' + sv(r[5]) + '" data-s-heals="' + sv(r[6]) + '" data-s-caps="' + sv(r[7]) + '" data-s-z="' + (r[8] !== null && !r[9] ? r[8] : "") + '" data-s-ovr="' + (rated ? rated.ovr : "") + '"><td class="rank">' + (i + 1) + '</td>';
        html += '<td class="pl" data-name="' + esc(pk) + '">' + esc(pk || r[1]) + (pk && pk.toLowerCase() !== r[1].toLowerCase() ? '<small>' + esc(r[1]) + '</small>' : '') + '</td>';
        html += '<td class="num">' + n0(r[3]) + '</td><td class="num">' + n0(r[4]) + '</td><td class="num">' + n0(r[5]) + '</td><td class="num">' + n0(r[6]) + '</td><td class="num">' + n0(r[7]) + '</td>';
        if (r[8] !== null && !r[9]) html += '<td class="gz" style="color:' + (r[8] >= 0 ? 'var(--cyan)' : 'var(--muted)') + '">' + (r[8] > 0 ? '+' : '') + r[8].toFixed(2) + '</td>';
        else html += '<td class="flag">' + esc((r[9] || '').replace(/_/g, ' ')) + '</td>';
        html += '<td class="num" style="color:' + (rated ? tierColor(rated.tier) : 'var(--faint)') + '">' + (rated ? rated.ovr.toFixed(1) : '—') + '</td></tr>';
      });
      html += '<tr class="tot"><td></td><td>Printed totals</td><td class="num">' + n0(team[4]) + '</td><td class="num">' + n0(team[5]) + '</td><td class="num">' + n0(team[6]) + '</td><td class="num">' + n0(team[7]) + '</td><td class="num">' + n0(team[8]) + '</td><td></td><td></td></tr>';
      html += '</tbody></table></div></div>';
    });
    html += '</div><p class="note-line" style="margin-top:10px">Z is the within-lobby composite for this game (within each side on Docks); OVR is the player\'s current ' + esc(runLabel) + ' rating. Rows without a z were not scored (cut-off panel, spectator, late join, or unreadable cell).</p>';
    openModal(html);
    document.getElementById("back-btn").addEventListener("click", function () { if (highlight && byRun[runLabel][highlight.toLowerCase()]) openProfile(highlight, runLabel); else closeModal(); });
    var pls = els["modal-body"].querySelectorAll("td.pl[data-name]");
    for (var i = 0; i < pls.length; i++) pls[i].addEventListener("click", function () { var n = this.getAttribute("data-name"); if (n && byRun[runLabel][n.toLowerCase()]) openProfile(n, runLabel); });
    var bts = els["modal-body"].querySelectorAll(".board table");
    for (var i = 0; i < bts.length; i++) makeSortable(bts[i]);
  }

  // horizontal distribution chart: one lane per scope (overall + each map)
  function boxChart(p, games, run, runLabel) {
    var W = 900, laneH = 46, left = 118, right = 64, top = 22, bottom = 26;
    var lanes = [{ key: "all", label: "Overall", gs: games, ovr: p.ovr, sigma: p.sigma, n: p.games, pc: p.games >= 5 ? percentile(pct[runLabel].all, p.ovr) : null }];
    MAPS.forEach(function (m) {
      var gs = games.filter(function (g) { return GAMEMETA[g[0]][1] === m[1]; });
      var nM = p[m[0]], sig = nM ? run.ovr_sd / run.sd_b * Math.sqrt(run.var_w * run.sd_b * run.sd_b / (nM * run.sd_b * run.sd_b + run.var_w)) : null;
      lanes.push({ key: m[0], label: m[1], gs: gs, ovr: p["ovr_" + m[0]], sigma: sig, n: nM, pc: nM >= 3 && p["ovr_" + m[0]] !== null ? percentile(pct[runLabel][m[0]], p["ovr_" + m[0]]) : null });
    });
    var H = top + lanes.length * laneH + bottom;
    var vals = games.filter(function (g) { return !g[6]; }).map(function (g) { return gameOvr(g[1] + g[5], run); });   // discarded games do not stretch the axis
    var xmin = Math.min(60, Math.floor(Math.min.apply(null, vals.concat([p.ovr - 1.96 * p.sigma])) / 5) * 5 - 5);
    var xmax = 100;                                   // the rating scale ends at 100; stronger single games sit on the edge
    if (!isFinite(xmin)) xmin = 60;
    var x = function (v) { return left + (Math.max(xmin, Math.min(xmax, v)) - xmin) / (xmax - xmin) * (W - left - right); };
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" style="display:block;overflow:visible">';
    for (var g = Math.ceil(xmin / 10) * 10; g <= xmax; g += 10) {
      s += '<line x1="' + x(g) + '" x2="' + x(g) + '" y1="' + (top - 6) + '" y2="' + (H - bottom + 4) + '" stroke="#26304e" stroke-width="1"/>';
      s += '<text x="' + x(g) + '" y="' + (H - 8) + '" fill="#5a6880" font-size="9" text-anchor="middle">' + g + '</text>';
    }
    s += '<line x1="' + x(run.ovr_mean) + '" x2="' + x(run.ovr_mean) + '" y1="' + (top - 6) + '" y2="' + (H - bottom + 4) + '" stroke="#333d5e" stroke-width="1" stroke-dasharray="3 3"/>';
    s += '<text x="' + x(run.ovr_mean) + '" y="' + (top - 10) + '" fill="#5a6880" font-size="8.5" text-anchor="middle" letter-spacing="1">LOBBY AVG</text>';
    lanes.forEach(function (L, i) {
      var cy = top + i * laneH + laneH / 2;
      s += '<text x="' + (left - 12) + '" y="' + (cy + 3) + '" fill="#f7fbf9" font-size="11" text-anchor="end" font-family="Oswald, sans-serif" letter-spacing="1">' + esc(L.label.toUpperCase()) + '</text>';
      s += '<text x="' + (left - 12) + '" y="' + (cy + 15) + '" fill="#5a6880" font-size="8.5" text-anchor="end">' + (L.n || 0) + ' game' + (L.n === 1 ? '' : 's') + '</text>';
      var keptG = L.gs.filter(function (gm) { return !gm[6]; });
      if (!keptG.length) { s += '<text x="' + x(run.ovr_mean) + '" y="' + (cy + 3) + '" fill="#5a6880" font-size="9" text-anchor="middle" letter-spacing="1">' + (L.gs.length ? 'NO KEPT GAMES' : 'NO GAMES') + '</text>'; } else {
      var v = keptG.map(function (gm) { return gameOvr(gm[1] + gm[5], run); }).sort(function (a, b) { return a - b; });
      var q1 = quantile(v, 0.25), q2 = quantile(v, 0.5), q3 = quantile(v, 0.75);
      s += '<rect x="' + x(q1) + '" y="' + (cy - 9) + '" width="' + Math.max(1, x(q3) - x(q1)) + '" height="18" fill="#64d1c1" fill-opacity="0.14" rx="2"/>';
      s += '<line x1="' + x(q2) + '" x2="' + x(q2) + '" y1="' + (cy - 9) + '" y2="' + (cy + 9) + '" stroke="#f7fbf9" stroke-width="2" stroke-opacity="0.7"/>';
      }
      L.gs.forEach(function (gm, j) {
        var adj = gm[1] + gm[5], gv = gameOvr(adj, run), over = gv > xmax, vx = x(gv), jit = ((j * 7919) % 13 - 6) * 1.1, m = GAMEMETA[gm[0]], gp = gamePct(adj, run);
        var disc = !!gm[6];
        s += '<circle cx="' + vx + '" cy="' + (cy + jit) + '" r="4" fill="' + (disc ? 'none' : over ? '#05060b' : '#8496ad') + '" stroke="' + (disc ? '#c75b5b' : over ? '#8496ad' : '#05060b') + '" stroke-width="' + (disc ? 1.5 : 2) + '"' + (disc ? ' stroke-dasharray="2 2"' : '') + ' class="dot" data-gid="' + gm[0] + '" data-tip="' + (disc ? 'DISCARDED (suspected late join) ' : '') +
          esc(m[0] + ' \u00b7 ' + m[1] + (m[2] ? ' \u00b7 ' + m[2] : '') + (m[3] ? ' vs ' + m[3] : '') + '|' + gm[2] + ' kills \u00b7 ' + gm[3] + ' dmg \u00b7 z ' + (gm[1] > 0 ? '+' : '') + gm[1].toFixed(2) + ' in a ' + (gm[5] > 0 ? '+' : '') + gm[5].toFixed(2) + ' lobby \u2192 P' + gp + ' game' + (over ? ' (beyond the scale)' : '') + ' \u00b7 click for the board') + '"/>';
      });
      if (L.ovr !== null && L.sigma) {
        var lo = L.ovr - 1.96 * L.sigma, hi = Math.min(run.ovr_cap, L.ovr + 1.96 * L.sigma);
        s += '<line x1="' + x(lo) + '" x2="' + x(hi) + '" y1="' + (cy + 16) + '" y2="' + (cy + 16) + '" stroke="#64d1c1" stroke-width="4" stroke-linecap="round"/>';
        s += '<circle cx="' + x(L.ovr) + '" cy="' + (cy + 16) + '" r="4.5" fill="#64d1c1" stroke="#05060b" stroke-width="2"/>';
        s += '<text x="' + (W - right + 10) + '" y="' + (cy + 3) + '" fill="' + tierColor(tierOf(L.ovr)) + '" font-size="13" font-weight="700">' + L.ovr.toFixed(1) + '</text>';
        s += '<text x="' + (W - right + 10) + '" y="' + (cy + 15) + '" fill="#5a6880" font-size="8.5">' + (L.pc === null ? '±' + L.sigma.toFixed(1) : 'P' + L.pc + ' · ±' + L.sigma.toFixed(1)) + '</text>';
      }
    });
    s += '</svg>';
    return s;
  }
  function bindTips(root) {
    var dots = root.querySelectorAll(".dot");
    for (var i = 0; i < dots.length; i++) {
      dots[i].style.cursor = "pointer";
      dots[i].addEventListener("mouseenter", function () {
        var parts = this.getAttribute("data-tip").split("|");
        els.tip.innerHTML = esc(parts[0]) + "<br><small>" + esc(parts[1]) + "</small>";
        els.tip.style.display = "block";
      });
      dots[i].addEventListener("mousemove", function (e) { els.tip.style.left = (e.clientX + 14) + "px"; els.tip.style.top = (e.clientY + 14) + "px"; });
      dots[i].addEventListener("mouseleave", function () { els.tip.style.display = "none"; });
      dots[i].addEventListener("click", function () {
        var name = els["modal-body"].querySelector(".pname"); els.tip.style.display = "none";
        openMatch(Number(this.getAttribute("data-gid")), name ? name.textContent : null, els["filter-run"].value);
      });
    }
  }

  // ---------- scanner (the reader service holds the API key; the page never sees it)
  var imageData = null;
  function updateReady() { els["btn-read"].disabled = !imageData; }
  function setStatus(msg, err) { els["scan-status"].textContent = msg; els["scan-status"].className = "status" + (err ? " err" : ""); }
  function loadImage(file) {
    if (!file || file.type.indexOf("image/") !== 0) { setStatus("That is not an image.", true); return; }
    imageData = null; updateReady(); setStatus("Loading image…");
    var reader = new FileReader();
    reader.onload = function () {
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, 1568 / Math.max(img.width, img.height));
        var cv = document.createElement("canvas"); cv.width = Math.round(img.width * scale); cv.height = Math.round(img.height * scale);
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
        var url = cv.toDataURL("image/png");
        imageData = { b64: url.split(",")[1], media: "image/png" };
        els.drop.innerHTML = '<img src="' + url + '" alt="scoreboard"><input type="file" id="file" accept="image/*">';
        document.getElementById("file").addEventListener("change", function () { loadImage(this.files[0]); });
        setStatus("Board loaded (" + cv.width + "×" + cv.height + "). Choose the map and press Read board.");
        updateReady();
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }
  els.file.addEventListener("change", function () { loadImage(this.files[0]); });
  document.addEventListener("paste", function (e) {
    var items = (e.clipboardData || {}).items || [];
    for (var i = 0; i < items.length; i++) if (items[i].type.indexOf("image/") === 0) { loadImage(items[i].getAsFile()); showScanTab(); break; }
  });
  ["dragenter", "dragover"].forEach(function (ev) { els.drop.addEventListener(ev, function (e) { e.preventDefault(); els.drop.classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (ev) { els.drop.addEventListener(ev, function (e) { e.preventDefault(); els.drop.classList.remove("over"); }); });
  els.drop.addEventListener("drop", function (e) { var f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) loadImage(f); });
  function showScanTab() { for (var i = 0; i < tabs.length; i++) if (tabs[i].getAttribute("data-tab") === "scan") tabs[i].click(); }

  // Reader endpoints: the deployed service for the published site; a page opened from disk tries a local proxy first.
  var LOCAL_PAGE = location.protocol === "file:" || /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  var READERS = LOCAL_PAGE ? PROXIES.slice().sort(function (a, b) { return (a.indexOf("localhost") === -1 ? 1 : 0) - (b.indexOf("localhost") === -1 ? 1 : 0); })
                           : PROXIES.filter(function (u) { return u.indexOf("localhost") === -1; });
  // Try each reader in order; a network failure or 404 (service not deployed) moves on, any other error is shown.
  function readViaProxy(i) {
    if (i >= READERS.length) return Promise.reject(new Error("No reader service reachable (" + READERS.join(", ") + "). Deploy scan-proxy or run it locally."));
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 150000) : null;
    return fetch(READERS[i], { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image: imageData.b64, media_type: imageData.media }), signal: ctl ? ctl.signal : undefined })
      .then(function (r) {
        if (r.status === 404) throw { next: true };
        return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ("Reader error " + r.status)); return j; });
      })
      .catch(function (e) { if (e && e.next) return readViaProxy(i + 1); if (e instanceof TypeError) return readViaProxy(i + 1); throw e; })
      .then(function (j) { if (timer) clearTimeout(timer); return j; });
  }
  els["btn-read"].addEventListener("click", function () {
    if (!imageData) return;
    els["btn-read"].disabled = true; setStatus("Reading the board… (20–40 s; up to a minute if the reader was asleep)"); els["scan-out"].innerHTML = "";
    readViaProxy(0).then(function (res) {
      var board = res.board;
      if (!board || !board.board_present || !board.teams.length) throw new Error("No scoreboard found in the image.");
      var u = res.usage || {};
      lastBoard = board; removedRows = [];
      setStatus("Read " + board.teams.reduce(function (n, t) { return n + t.players.length; }, 0) + " names \u00b7 " + (u.input_tokens || 0) + " in / " + (u.output_tokens || 0) + " out tokens. Everything below is a projection from ratings.");
      renderScan(board);
    }).catch(function (e) { setStatus(String(e.message || e), true); }).then(function () { updateReady(); });
  });

  function rateFor(map, role) {
    var key = (map === "Docks" || map === "Skydock") ? map + "/" + (role === "attacker" ? "attacker" : "defender") : map;
    var st = MAPSTATS[key] || MAPSTATS[map];
    return st && st.rate ? st.rate : null;
  }
  var lastBoard = null;
  var removedRows = [];        // players taken off the current scan: {t: team index, i: position, pl}
  var UNRATED_DEFAULT = __UNRATED__;   // a_cemaster 2026-10-24: an unknown name is usually a less experienced player, not an average one
  var scanUnrated = UNRATED_DEFAULT;   // OVR assumed for unrated players; null = the average (that side's average on Docks / Skydock)
  els["scan-map"].addEventListener("change", function () { if (lastBoard) renderScan(lastBoard); });
  els["scan-run"].addEventListener("change", function () { if (lastBoard) renderScan(lastBoard); });

  // Which side of the outcome model a team is: A = left panel (Warehouse), the Astartes faction (Ordana), the defenders (Docks).
  function sideA(team, map) {
    var lab = (team.label || "").toUpperCase();
    if (map === "Ordana") return /ASTARTES|IMPERIALIS/.test(lab) ? true : (/XENOS|INSURGENT/.test(lab) ? false : team.side === "left");
    if (map === "Docks" || map === "Skydock") return team.role === "defender" ? true : (team.role === "attacker" ? false : team.side === "left");
    return team.side === "left";
  }
  // End-result projection from the two teams' mean rating z: win probability (logistic), expected loser score, length.
  function projectOutcome(map, teamsInfo) {
    var om = OUTCOME[map]; if (!om || teamsInfo.length !== 2) return null;
    var A = teamsInfo[0].isA ? teamsInfo[0] : teamsInfo[1], B = A === teamsInfo[0] ? teamsInfo[1] : teamsInfo[0];
    if (A === B) return null;
    var diff = A.strength - B.strength;
    var labA = (A.team.label || "").toUpperCase(), tagged = A.rows.filter(function (x) { return x.p && x.p.clan === om.home_clan; }).length;
    var home = om.home_clan && ((om.home_labels || []).some(function (k) { return labA.indexOf(k) !== -1; }) || (A.rows.length && tagged >= A.rows.length / 2)) ? 1 : 0;
    var pA = 1 / (1 + Math.exp(-(om.logit[0] + om.home_logit * home + om.logit[1] * diff)));
    var loser = Math.max(0.25 * om.cap, Math.min(om.cap - 1, om.loser[0] + om.loser[1] * Math.abs(diff)));
    var fav = pA >= 0.5 ? A : B, dog = fav === A ? B : A, pFav = Math.max(pA, 1 - pA);
    var margin = (2 * pA - 1) * (om.cap - loser);          // expected A-minus-B score differential
    var length = map === "Docks" ? om.minutes : (om.cap + loser) / 1000;
    return { om: om, A: A, B: B, diff: diff, pA: pA, home: home, fav: fav, dog: dog, pFav: pFav, loser: Math.round(loser), margin: Math.round(margin), length: length,
             lengthText: map === "Docks" ? om.minutes.toFixed(1) + " min" : Math.round(om.cap + loser).toLocaleString() + " pts" };
  }
  // Expected stats for one game: expected z (rating minus the mean rating of the others in this lobby) applied to the
  // map's baseline - per unit of game length where the map has a clock, else per average game. The range is the
  // player's own game-to-game spread (blended toward the population spread when few games).
  function projection(zexp, p, map, role, length) {
    var key = (map === "Docks" || map === "Skydock") ? map + "/" + (role === "attacker" ? "attacker" : "defender") : map;
    var st = MAPSTATS[key] || MAPSTATS[map]; if (!st) return null;
    var run = RUNS[els["scan-run"].value], n = p ? p.games : 0, own = p && p.zsd !== null && n >= 3 ? p.zsd * p.zsd : run.var_w;
    var spread = Math.sqrt((n * own + 3 * run.var_w) / (n + 3));
    var rt = st.rate;
    if (rt && length) {
      return { k: length * (rt.k[0] + zexp * rt.k[1]), kr: length * spread * rt.k[1], d: length * (rt.d[0] + zexp * rt.d[1]), dr: length * spread * rt.d[1], key: key, spread: spread };
    }
    return { k: st.k[0] + zexp * st.k[1], kr: spread * st.k[1], d: st.d[0] + zexp * st.d[1], dr: spread * st.d[1], key: key + " (average game)", spread: spread };
  }
  function renderScan(board) {
    var runLabel = els["scan-run"].value, map = els["scan-map"].value, mk = { Docks: "d", Warehouse: "w", Ordana: "o", Skydock: "s" }[map];
    var sided = (map === "Docks" || map === "Skydock"), html = "";
    var runMeta = RUNS[runLabel], unratedZ = scanUnrated === null ? null : (scanUnrated - runMeta.ovr_mean) / runMeta.ovr_sd * runMeta.sd_b;   // the assumed OVR on the rating-z scale
    // resolve everyone first: the lobby a player is measured against is the other players on this board
    var teams = board.teams.map(function (team, ti) {
      var role = (map === "Docks" || map === "Skydock") ? (team.role === "attacker" || team.role === "defender" ? team.role : (team.side === "left" ? "defender" : "attacker")) : "neutral";
      // ti / pi point back at board.teams[ti].players[pi] so a row can be removed; unreadable names are ignored
      return { team: team, ti: ti, role: role, rows: team.players.map(function (pl, pi) { return { pl: pl, pi: pi }; })
        .filter(function (o) { var h = o.pl.handle; return h && h.trim() && h.toLowerCase().indexOf('obscured') === -1; }).map(function (o) {
        var pl = o.pl, r = resolveHandle(pl.handle), p = byRun[runLabel][r.name.toLowerCase()];
        // sided maps: the player's record in this role, else on this map, else overall; an unknown player is that side's average
        var rk = sided ? mk + (role === "attacker" ? "a" : "d") : null;
        var useRole = !!(rk && p && p["ovr_" + rk] !== null && p["n_" + rk] > 0);
        var useMap = !useRole && !!(p && p["ovr_" + mk] !== null && p[mk] > 0);
        var base = sided ? ((RUNS[runLabel].role_mean || {})[map + "/" + role] || 0) : 0;
        return { pl: pl, ti: ti, pi: o.pi, r: r, p: p, zs: p ? (useRole ? p["z_" + rk] : useMap ? p["z_" + mk] : p.zs) : (unratedZ !== null ? unratedZ : base),
                 ovr: p ? (useRole ? p["ovr_" + rk] : useMap ? p["ovr_" + mk] : p.ovr) : null, useMap: useMap, useRole: useRole, rk: rk };
      }) };
    }).filter(function (T) { return T.rows.length; });                    // a panel emptied by removals (spectators) drops out
    var all = [].concat.apply([], teams.map(function (t) { return t.rows; }));
    teams.forEach(function (T) { T.strength = T.rows.length ? T.rows.reduce(function (a, o) { return a + o.zs; }, 0) / T.rows.length : 0; T.isA = sideA(T.team, map); });
    if (teams.length === 2 && teams[0].isA === teams[1].isA) { teams[0].isA = true; teams[1].isA = false; }
    var oc = projectOutcome(map, teams);
    var length = oc ? oc.length : null;
    if (oc) {
      var om = oc.om, favName = oc.fav.team.label || oc.fav.team.side, dogName = oc.dog.team.label || oc.dog.team.side;
      html += '<div class="chart-wrap" style="padding:12px 14px"><div class="chart-title" style="padding:0 0 6px">Projected result \u00b7 from the two teams\' mean ratings</div>' +
        '<div class="modal-head" style="margin:0 0 4px"><span class="pname" style="font-size:20px">' + esc(favName) + '</span><span class="povr" style="font-size:22px;color:var(--cyan)">' + Math.round(100 * oc.pFav) + '%</span>' +
        '<span class="pci" style="font-size:13px;color:var(--text)">projected ' + om.cap.toLocaleString() + ' \u2013 ' + oc.loser.toLocaleString() + ' <span style="color:var(--muted)">vs ' + esc(dogName) + '</span></span></div>' +
        '<div class="facts" style="margin-bottom:0"><span>Strength <b>' + esc(oc.A.team.label || 'A') + ' ' + (oc.A.strength > 0 ? '+' : '') + oc.A.strength.toFixed(2) + ' vs ' + esc(oc.B.team.label || 'B') + ' ' + (oc.B.strength > 0 ? '+' : '') + oc.B.strength.toFixed(2) + ' z</b></span>' +
        '<span>Expected margin <b>' + (oc.margin > 0 ? '+' : '') + oc.margin + ' for ' + esc(oc.A.team.label || 'A') + '</b></span><span>Length <b>' + oc.lengthText + '</b></span>' +
        '<span>Home clan <b>' + (om.home_clan ? (oc.home ? esc(om.home_clan) + ' on ' + esc(om.side_a) + ' (+' + Math.round(100 * (1 / (1 + Math.exp(-(om.logit[0] + om.home_logit))) - 1 / (1 + Math.exp(-om.logit[0])))) + ' pts at even strength)' : 'none recognised \u00b7 neutral sides') : 'n/a') + '</b></span>' +
        '<span>Model <b>' + om.n + ' finished ' + esc(map) + ' games from two-sided sources' + (om.home_clan ? ' \u00b7 ' + esc(om.home_clan) + ' at home ' + om.n_home + ' (' + Math.round(100 * om.home_rate) + '% won)' + (om.away_rate !== null ? ', others ' + Math.round(100 * om.away_rate) + '%' : '') : ' \u00b7 ' + esc(om.side_a) + ' win ' + Math.round(100 * om.base_rate) + '% at even strength') + (om.loser_sd ? ' \u00b7 loser score \u00b1' + Math.round(om.loser_sd) : '') + '</b></span></div></div>';
    }
    html += '<div class="teamsum" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">Unrated players count as <input type="number" id="scan-unrated" step="0.5" min="40" max="100" value="' + (scanUnrated === null ? '' : scanUnrated) + '" placeholder="avg" aria-label="OVR assumed for unrated players"> OVR' +
      (scanUnrated === null ? ' <span style="color:var(--faint)">(the average' + (sided ? ' of their side' : '') + ')</span>' : scanUnrated === UNRATED_DEFAULT ? ' <span style="color:var(--faint)">(default: a less experienced player)</span>' : '') +
      (scanUnrated !== UNRATED_DEFAULT ? ' <button type="button" class="btn" id="scan-unrated-def">default ' + UNRATED_DEFAULT + '</button>' : '') +
      (scanUnrated !== null ? ' <button type="button" class="btn" id="scan-unrated-avg">the average</button>' : '') + '</div>';
    if (removedRows.length) {
      html += '<div class="removed">Removed from this scan' + removedRows.map(function (x, k) {
        return '<button type="button" data-restore="' + k + '" title="Put this name back">' + esc(x.pl.handle) + ' \u21ba</button>';
      }).join('') + (removedRows.length > 1 ? '<button type="button" class="all" data-restore="all">restore all</button>' : '') + '</div>';
    }
    teams.forEach(function (T) {
      var team = T.team, role = T.role, rows = T.rows;
      var lobby = all;                                                        // both teams, on every map (scored the same way since 2026-10-24)
      rows.forEach(function (x) {
        var others = lobby.filter(function (o) { return o !== x; });
        var lm = others.length ? others.reduce(function (a, o) { return a + o.zs; }, 0) / others.length : 0;   // unrated count as average (0)
        x.lobby = lm; x.zexp = x.zs - lm; x.proj = projection(x.zexp, x.p, map, role, length);
      });
      var lobbyAll = lobby.reduce(function (a, o) { return a + o.zs; }, 0) / (lobby.length || 1), unr = lobby.filter(function (o) { return !o.p; }).length;
      var rated = rows.filter(function (x) { return x.p; });
      var sumK = rows.reduce(function (a, x) { return a + (x.proj ? x.proj.k : 0); }, 0), sumD = rows.reduce(function (a, x) { return a + (x.proj ? x.proj.d : 0); }, 0);
      var meanOvr = rated.length ? rated.reduce(function (a, x) { return a + x.ovr; }, 0) / rated.length : null;
      html += '<div class="team-title">' + esc(team.label || team.side) + '<small>' + esc(team.side) + (map === "Docks" ? ' \u00b7 ' + role : '') + ' \u00b7 ' + rows.length + ' players</small></div>';
      html += '<div class="teamsum">Rated <b>' + rated.length + '/' + rows.length + '</b> &nbsp; Mean OVR <b>' + (meanOvr === null ? '\u2014' : meanOvr.toFixed(1)) + '</b> &nbsp; Lobby <b>' + (lobbyAll > 0 ? '+' : '') + lobbyAll.toFixed(2) + ' z</b>' + (unr ? ' <span style="color:var(--faint)">(' + unr + ' unrated as ' + (scanUnrated === null ? 'average' : scanUnrated + ' OVR') + ')</span>' : '') + ' &nbsp; Projected team kills <b>' + Math.round(sumK) + '</b> &nbsp; damage <b>' + Math.round(sumD).toLocaleString() + '</b>' +
        (rows[0] && rows[0].proj ? ' &nbsp; <span style="color:var(--faint)">baseline ' + esc(rows[0].proj.key) + '</span>' : '') + '</div>';
      html += '<div class="table-shell" style="max-height:none"><table><thead><tr><th class="rank"></th><th data-key="name"><button type="button">Player</button></th><th class="num" data-key="ovr"><button type="button">OVR</button></th><th class="num" data-key="z"><button type="button">Rating z</button></th><th class="num" data-key="zexp"><button type="button">vs lobby</button></th><th class="num" data-key="k"><button type="button">Proj. kills</button></th><th class="num" data-key="dmg"><button type="button">Proj. DMG</button></th><th class="rm"></th></tr></thead><tbody>';
      rows.forEach(function (x, i) {
        var p = x.p, color = p ? tierColor(tierOf(x.ovr)) : "#5c6975";
        var shown = p ? p.name : x.pl.handle, differs = p && p.name.toLowerCase() !== x.pl.handle.toLowerCase();
        html += '<tr class="row" data-name="' + (p ? esc(p.name) : '') + '" data-s-name="' + esc(shown) + '" data-s-ovr="' + (p ? x.ovr : gameOvr(x.zs, runMeta).toFixed(1)) + '" data-s-z="' + (p ? x.zs : "") + '" data-s-zexp="' + x.zexp.toFixed(3) + '" data-s-k="' + (x.proj ? x.proj.k.toFixed(2) : "") + '" data-s-dmg="' + (x.proj ? x.proj.d.toFixed(1) : "") + '"><td class="rank">' + (i + 1) + '</td>';
        html += '<td class="name" style="font-size:13.5px">' + esc(shown) + (differs ? ' <small style="font-family:var(--mono);font-size:9px;color:var(--faint)">' + esc(x.pl.handle) + (x.r.how !== "known" ? ' \u00b7 ' + esc(x.r.how) : '') + '</small>' : '') + (p ? '' : ' <small style="font-family:var(--mono);font-size:9px;color:var(--faint)">' + (scanUnrated !== null ? 'unrated \u00b7 as ' + scanUnrated : sided ? 'unrated \u00b7 side average' : 'unrated') + '</small>') + '</td>';
        html += '<td class="ovr" style="color:' + color + ';font-size:14px">' + (p ? x.ovr.toFixed(1) + ' <small style="font-size:9px;font-weight:400;color:var(--faint)">' + (x.useRole ? '\u00d7' + p["n_" + x.rk] + (role === "attacker" ? ' att' : ' def') : x.useMap ? '\u00d7' + p[mk] : 'overall') + '</small>' : '<span style="color:var(--faint)">' + gameOvr(x.zs, runMeta).toFixed(1) + '</span>') + '</td>';
        html += '<td class="num" style="color:' + (p ? 'var(--text)' : 'var(--faint)') + '">' + ((x.zs > 0 ? '+' : '') + x.zs.toFixed(2)) + '</td>';
        html += '<td class="num" style="color:' + (x.zexp >= 0 ? 'var(--cyan)' : 'var(--muted)') + '">' + (x.zexp > 0 ? '+' : '') + x.zexp.toFixed(2) + '</td>';
        if (x.proj && p) html += '<td class="proj">' + Math.round(x.proj.k) + '<small>\u00b1' + Math.round(x.proj.kr) + '</small></td><td class="proj">' + Math.round(x.proj.d).toLocaleString() + '<small>\u00b1' + Math.round(x.proj.dr).toLocaleString() + '</small></td>';
        else if (x.proj) html += '<td class="proj" style="color:var(--faint)"><i>' + Math.round(x.proj.k) + '</i><small>avg</small></td><td class="proj" style="color:var(--faint)"><i>' + Math.round(x.proj.d).toLocaleString() + '</i><small>avg</small></td>';
        else html += '<td class="num">\u2014</td><td class="num">\u2014</td>';
        html += '<td class="rm"><button type="button" data-rm="' + x.ti + ',' + x.pi + '" title="Remove ' + esc(x.pl.handle) + ' from this scan (misread or extra row)">\u00d7</button></td></tr>';
      });
      html += '</tbody></table></div>';
    });
    var rt = rateFor(map, "defender");
    html += '<p class="note-line" style="margin-top:10px">Nothing is read off the board but the names. OVR is the player\'s ' + esc(map) + ' rating (games on the map beside it) or their overall rating when they have none there. The result comes from the two teams\' mean rating z: win probability is a logistic fit with a home-clan term (VAK defending its own base on Docks, Sol as the Astartes on Ordana; that edge is applied only when the scan recognises that clan on that side, otherwise the sides are neutral), the loser\'s score a linear fit, both on finished ' + esc(map) + ' games from sources that record losses as well as wins (victory channels are left out), grouped by strength difference; that fixes the game length (' + (map === "Docks" ? 'the typical timer' : 'cap plus the loser\'s score') + '). <b>vs lobby</b> is each player\'s expected z in this room (rating minus the mean rating of both teams; unrated players count as ' + (scanUnrated === null ? 'average' : scanUnrated + ' OVR' + (scanUnrated === UNRATED_DEFAULT ? ', the default for an unknown name; the box above the teams changes it' : ', set in the box above the teams')) + '). Projected kills / damage apply that expectation to the map\'s baseline ' + (rt ? 'per ' + (rt.unit === "per minute" ? 'minute' : '1000 points') + ' times the projected length' : 'for an average game') + '; \u00b1 is the player\'s own game-to-game spread. Click a header to sort that team, a rated row for the profile; \u00d7 takes a misread or extra row (spectator, duplicate, a name from another panel) out of the scan and the lobby, result and projections recompute without it - removed names can be put back from the chips above the teams.</p>';
    els["scan-out"].innerHTML = html;
    var trs = els["scan-out"].querySelectorAll("tr.row[data-name]");
    for (var i = 0; i < trs.length; i++) trs[i].addEventListener("click", function () { var n = this.getAttribute("data-name"); if (n) openProfile(n, els["scan-run"].value); });
    var sts = els["scan-out"].querySelectorAll("table");
    for (var i = 0; i < sts.length; i++) makeSortable(sts[i]);
    var rms = els["scan-out"].querySelectorAll("td.rm button[data-rm]");
    for (var i = 0; i < rms.length; i++) rms[i].addEventListener("click", function (e) {
      e.stopPropagation();                                               // not a profile click
      var a = this.getAttribute("data-rm").split(","), t = +a[0], k = +a[1];
      var pl = lastBoard.teams[t].players.splice(k, 1)[0];
      if (pl) removedRows.push({ t: t, i: k, pl: pl });
      renderScan(lastBoard);
    });
    var rss = els["scan-out"].querySelectorAll(".removed button[data-restore]");
    for (var i = 0; i < rss.length; i++) rss[i].addEventListener("click", function () {
      var k = this.getAttribute("data-restore");
      var back = k === "all" ? removedRows.splice(0, removedRows.length) : removedRows.splice(+k, 1);
      back.forEach(function (x) { var ps = lastBoard.teams[x.t].players; ps.splice(Math.min(x.i, ps.length), 0, x.pl); });
      renderScan(lastBoard);
    });
    var ui = els["scan-out"].querySelector("#scan-unrated");                 // the OVR assumed for unrated players: result, lobby and projections recompute
    if (ui) ui.addEventListener("change", function () { var v = parseFloat(this.value); scanUnrated = isFinite(v) ? Math.max(40, Math.min(100, v)) : null; renderScan(lastBoard); });
    var ua = els["scan-out"].querySelector("#scan-unrated-avg");
    if (ua) ua.addEventListener("click", function () { scanUnrated = null; renderScan(lastBoard); });
    var ud = els["scan-out"].querySelector("#scan-unrated-def");
    if (ud) ud.addEventListener("click", function () { scanUnrated = UNRATED_DEFAULT; renderScan(lastBoard); });
  }

  render();
  updateReady();
</script>

<script>
  fetch("https://hits.sh/clandraft.onrender.com/ratings.svg", { mode: "no-cors", cache: "no-store" }).catch(function () {});
</script>

</body>
</html>
"""


# ------------------------------------------------------------------ STATS ELO tab of index.html
STATS_KEYS = ['run', 'name', 'ovr', 'games', 'sigma', 'clan', 'ovr_d', 'd', 'ovr_w', 'w', 'ovr_o', 'o', 'ovr_s', 's', 'first', 'last',
              'ev', 'evD', 'evR', 'evS', 'evT', 'evO', 'wins', 'losses']
EVENT_CLASS = {'Defense': 'D', 'Raid': 'R', 'Khritus raid': 'R', 'Scrimmage': 'S', 'Defense Training': 'T'}


def event_counts(gmeta, boards, since='', until=''):
    """The event counter: per canonical player, the boards they stand on in the era (scored or not) by event class, and
    their win / loss record on two-sided boards that carry both scores; plus the era's totals per class."""
    per = collections.defaultdict(lambda: {'ev': 0, 'D': 0, 'R': 0, 'S': 0, 'T': 0, 'O': 0, 'wins': 0, 'losses': 0})
    tot = {'games': 0, 'D': 0, 'R': 0, 'S': 0, 'T': 0, 'O': 0}
    for gid, b in boards.items():
        m = gmeta[gid]
        if (since and m[0] < since) or (until and m[0] > until):
            continue
        cls = EVENT_CLASS.get(m[2] or '', 'O')
        tot['games'] += 1
        tot[cls] += 1
        sides = [t[2] for t in b['t']]
        winner = None
        if len(sides) == 2 and set(sides) == {'left', 'right'} and m[5] is not None and m[6] is not None and m[5] != m[6]:
            winner = 'left' if m[5] > m[6] else 'right'
        seen = set()
        for r in b['p']:
            pk = r[2]
            if not pk or pk in seen:
                continue
            seen.add(pk)
            e = per[pk]
            e['ev'] += 1
            e[cls] += 1
            if winner:
                e['wins' if sides[r[0]] == winner else 'losses'] += 1
    return per, tot


def export_stats_elo(rows, meta, gmeta, boards):
    """Write the STATS ELO tab's data into index.html: the data-only ratings per era and the event counter, between the
    markers `var STATS_ELO = ...; /* /STATS_ELO */` and `var STATS_META = ...; /* /STATS_META */`. generate.js rewrites
    PLAYERS / ROWS and leaves these blocks alone; this never touches anything else. No boards, no scan: the tab is static."""
    path = os.path.join(ROOT, 'index.html')
    raw = open(path, 'rb').read()
    crlf = b'\r\n' in raw
    html = raw.decode('utf-8').replace('\r\n', '\n')
    marks = (('var STATS_ELO = ', '; /* /STATS_ELO */'), ('var STATS_META = ', '; /* /STATS_META */'))
    if any(a not in html or b not in html for a, b in marks):
        print('index.html has no STATS ELO block; tab data not written')
        return None
    out, smeta = [], {}
    for label, mt in meta.items():
        per, tot = event_counts(gmeta, boards, mt['since'], mt['until'])
        smeta[label] = {'since': mt['since'], 'until': mt['until'], 'created': mt['created'], 'games_scored': mt['games'],
                        'players': mt['players'], 'ge5': mt['ge5'], 'ovr_mean': mt['ovr_mean'], 'ovr_sd': mt['ovr_sd'], 'ovr_cap': mt['ovr_cap'],
                        'events': tot}
        for p in rows:
            if p['run'] != label:
                continue
            e = per.get(p['name'], {})
            out.append([label, p['name'], p['ovr'], p['games'], p['sigma'], p['clan'], p['ovr_d'], p['d'], p['ovr_w'], p['w'], p['ovr_o'], p['o'],
                        p['ovr_s'], p['s'], p['first'], p['last'], e.get('ev', 0), e.get('D', 0), e.get('R', 0), e.get('S', 0), e.get('T', 0),
                        e.get('O', 0), e.get('wins', 0), e.get('losses', 0)])
    j = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':'))
    for (a, b), payload in zip(marks, (j({'keys': STATS_KEYS, 'rows': out}), j(smeta))):
        i = html.index(a) + len(a)
        html = html[:i] + payload + html[html.index(b, i):]
    open(path, 'wb').write(html.replace('\n', '\r\n' if crlf else '\n').encode('utf-8'))
    print(f'wrote index.html STATS ELO block: {len(out)} rating rows over {len(smeta)} eras; index.html is {os.path.getsize(path)//1024} KB')
    return path


def main():
    con = raid_db.connect()
    rows, meta, games, gmeta, boards, resolve, mapstats, outcome = build(con)
    html = open(os.path.join(ROOT, 'list.html'), encoding='utf-8').read()
    m = re.search(r'<style>.*?</style>', html, re.S)
    style = m.group(0).replace('</style>', EXTRA_CSS + '</style>')
    j = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':'))
    page = (PAGE.replace('__STYLE__', style).replace('__ROWS__', j(rows)).replace('__RUNS__', j(meta)).replace('__GAMES__', j(games))
                .replace('__GAMEMETA__', j(gmeta)).replace('__BOARDS__', j(boards)).replace('__RESOLVE__', j(resolve))
                .replace('__MAPSTATS__', j(mapstats)).replace('__PROXIES__', j(PROXIES)).replace('__OUTCOME__', j(outcome)).replace('__UNRATED__', str(UNRATED_DEFAULT)))
    open(OUT, 'w', encoding='utf-8').write(page)
    print(f'wrote ratings.html: {len(rows)} rating rows, {len(gmeta)} games, {sum(len(b["p"]) for b in boards.values())} board rows, {len(resolve)} handles; {os.path.getsize(OUT)//1024} KB')
    export_stats_elo(rows, meta, gmeta, boards)
    p = export_predict(rows, meta, resolve, mapstats, outcome)
    print(f'wrote {os.path.basename(p)}: {os.path.getsize(p)//1024} KB (scan-tab data for external consumers, e.g. the Avian bot\'s !predict)')


PREDICT_OUT = os.path.join(ROOT, 'predict_data.json')
UNRATED_DEFAULT = 74   # OVR assumed for a player with no rating. a_cemaster 2026-10-24: an unknown name is usually a less experienced
                       # player, not an average one; 74 is the 25th percentile of rated players (16th of appearances) in 2025-26


def export_predict(rows, meta, resolve, mapstats, outcome):
    """Compact bundle of what the scan tab needs, for consumers outside the page (the Avian Discord bot's !predict is a
    port of renderScan over this file): per-era player rows (OVR, rating z, per-map ratings, game counts, own spread, clan),
    the handle -> canonical-name map, per-map kill/damage baselines and the fitted outcome models. Same numbers as the page."""
    import datetime
    keep = ('name', 'ovr', 'zs', 'games', 'zsd', 'clan', 'd', 'w', 'o', 's', 'ovr_d', 'ovr_w', 'ovr_o', 'ovr_s', 'z_d', 'z_w', 'z_o', 'z_s',
            'n_da', 'n_dd', 'n_sa', 'n_sd', 'z_da', 'z_dd', 'z_sa', 'z_sd', 'ovr_da', 'ovr_dd', 'ovr_sa', 'ovr_sd')
    players = {}
    for r in rows:
        players.setdefault(r['run'], {})[r['name'].lower()] = {k: r[k] for k in keep}
    bundle = {'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
              'default_run': '2025-2026' if '2025-2026' in meta else next(iter(meta)),
              'runs': {label: {k: v for k, v in m.items() if k != 'gameq'} for label, m in meta.items()},
              'players': players, 'resolve': resolve, 'mapstats': mapstats, 'outcome': outcome, 'caps': CAPS, 'unrated_default': UNRATED_DEFAULT}
    with open(PREDICT_OUT, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(',', ':'))
    return PREDICT_OUT


if __name__ == '__main__':
    main()
