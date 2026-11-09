"""Render an explainer animation: how one player's scoreboard rows become a z, a rating, an OVR, and how two teams'
ratings become a win probability and a projected score. Every number on screen is read from raids.sqlite and the
fitted models embedded in ratings.html, so the film always matches the live page.

usage: python -I raid_explain_anim.py magnetpilot147 --game 1980 --out sources/explainers/magnetpilot147_ovr.mp4
       python -I raid_explain_anim.py magnetpilot147 --game 1980 --preview DIR     # a few PNG frames per scene

Output is H.264 yuv420p with +faststart (plays in VS Code and browsers); ffmpeg comes from imageio-ffmpeg.
"""
import argparse, collections, datetime, json, math, os, re, sqlite3, sys, textwrap
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.animation import FFMpegWriter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from raid_ratings_page import side_of, CAPS, HOME   # noqa: E402  (same side convention as the page's outcome fit)

# ---- look: the site's dark theme; two categorical series (player's side / opponents), validated on the #05060b surface
BG, SURF, SURF2, LINE, LINE2 = '#05060b', '#131a2b', '#1b2440', '#26304e', '#333d5e'
TEXT, MUTED, FAINT = '#f7fbf9', '#8496ad', '#5a6880'
A_COL, B_COL, DISCARD = '#3987e5', '#d95926', '#e66767'
SANS, MONO = 'Segoe UI', 'Cascadia Mono'
plt.rcParams.update({'font.family': SANS, 'text.color': TEXT, 'axes.edgecolor': LINE2, 'axes.labelcolor': MUTED, 'xtick.color': MUTED,
                     'ytick.color': MUTED, 'axes.facecolor': SURF, 'figure.facecolor': BG, 'axes.grid': False, 'mathtext.default': 'regular'})
W, H, DPI, FPS = 16, 9, 100, 30


def clamp(v, lo, hi): return max(lo, min(hi, v))
def seg(t, a, b):
    """0..1 progress of the sub-stage [a, b] of a scene at time t, eased (smoothstep)."""
    u = clamp((t - a) / (b - a), 0.0, 1.0); return u * u * (3 - 2 * u)
def psd(x): m = np.mean(x); return float(np.sqrt(np.mean((np.asarray(x) - m) ** 2)))
def sgn(v, nd=2): return f'{v:+.{nd}f}'
def fmt_int(v): return f'{int(round(v)):,}'


# ---------------------------------------------------------------- data
def load(player, game_id, label):
    page = open(os.path.join(ROOT, 'ratings.html'), encoding='utf-8').read()
    grab = lambda name: json.loads(re.search(r'var ' + name + r' = (\{.*?\});\n', page).group(1))
    OUTCOME, MAPSTATS, RUNS = grab('OUTCOME'), grab('MAPSTATS'), grab('RUNS')
    run = RUNS[label]; run_id = run['run_id']
    con = sqlite3.connect('file:' + os.path.join(ROOT, 'raids.sqlite').replace('\\', '/') + '?mode=ro', uri=True); con.row_factory = sqlite3.Row
    rating = con.execute('SELECT * FROM ratings WHERE run_id=? AND player_key=?', (run_id, player)).fetchone()
    if not rating:
        sys.exit(f'{player} has no rating in run {run_id} ({label})')
    hist = [dict(r) for r in con.execute('''SELECT z.*, g.date, g.map FROM z_scores z JOIN games g USING(game_id)
                                            WHERE z.run_id=? AND z.player_key=? ORDER BY g.date, g.game_id''', (run_id, player))]
    zr = {r['player_key']: dict(r) for r in con.execute('SELECT player_key, z_sos, ovr, n_games, z_sd FROM ratings WHERE run_id=?', (run_id,))}
    res = {r['handle_key']: r['canonical'] for r in con.execute('SELECT handle_key, canonical FROM handle_resolutions')}
    game = dict(con.execute('SELECT * FROM games WHERE game_id=?', (game_id,)).fetchone())
    teams = []
    for t in con.execute('SELECT * FROM teams WHERE game_id=? ORDER BY team_id', (game_id,)):
        rows = []
        for pg in con.execute('''SELECT pg.*, z.z_kills, z.z_dmg, z.z_comp, z.flag, z.player_key, z.group_n FROM player_games pg
                                 LEFT JOIN z_scores z ON z.pg_id=pg.pg_id AND z.run_id=? WHERE pg.team_id=? ORDER BY pg.pg_id''', (run_id, t['team_id'])):
            pk = pg['player_key'] or res.get(pg['handle'].strip().lower(), pg['handle'])
            r = zr.get(pk)
            rows.append(dict(handle=pg['handle'], kills=pg['kills'], dmg=pg['dmg'], zk=pg['z_kills'], zd=pg['z_dmg'], zc=pg['z_comp'], flag=pg['flag'],
                             key=pk, zs=r['z_sos'] if r else None, ovr=r['ovr'] if r else None, n=r['n_games'] if r else 0, is_player=(pk == player)))
        teams.append(dict(team=dict(t), side=side_of(t, game['map']), rows=rows))
    return dict(player=player, run=run, run_label=label, rating=dict(rating), hist=hist, game=game, teams=teams, OUTCOME=OUTCOME, MAPSTATS=MAPSTATS)


def derive(D):
    """Everything the scenes print, computed once (and cross-checked against the stored values)."""
    g, T = D['game'], D['teams']; mp = g['map']; R = D['rating']; run = D['run']
    mine = [t for t in T if any(r['is_player'] for r in t['rows'])][0]
    me = [r for r in mine['rows'] if r['is_player']][0]
    core = [r for r in mine['rows'] if r['flag'] is None]              # his comparison group: the scored rows of his group
    asym = mp not in ('Warehouse', 'Ordana')
    if not asym:                                                        # symmetric map: both teams are one group
        core = [r for t in T for r in t['rows'] if r['flag'] is None]
    ks, ds = np.array([r['kills'] for r in core], float), np.array([r['dmg'] for r in core], float)
    zk, zd = (ks - ks.mean()) / psd(ks), (ds - ds.mean()) / psd(ds)
    comp = 0.5 * zk + 0.5 * zd; sdc = psd(comp); zc = np.clip(comp / sdc, -2.5, 2.5)
    i_me = [i for i, r in enumerate(core) if r['is_player']][0]
    ex = dict(core=core, i=i_me, k_mean=ks.mean(), k_sd=psd(ks), d_mean=ds.mean(), d_sd=psd(ds), zk=zk, zd=zd, comp=comp, sdc=sdc, zc=zc, asym=asym)
    assert abs(zc[i_me] - me['zc']) < 0.02, (zc[i_me], me['zc'])
    # history
    kept = [h for h in D['hist'] if h['flag'] is None]; dropped = [h for h in D['hist'] if h['flag'] == 'late_join_suspect']
    z = np.array([h['z_comp'] for h in kept]); lob = np.array([h['lobby_z'] for h in kept]); y = z + lob
    n, k = len(kept), run['k']
    shr = z.mean() * n / (n + k); y_shr = y.mean() * n / (n + k); zsos = R['z_sos']; centre = y_shr - zsos
    ovr = lambda v: min(run['ovr_cap'], run['ovr_mean'] + run['ovr_sd'] * v / run['sd_b'])
    hist = dict(kept=kept, dropped=dropped, z=z, lob=lob, y=y, n=n, k=k, z_mean=z.mean(), lob_mean=lob.mean(), y_mean=y.mean(), shr=shr, y_shr=y_shr,
                centre=centre, zsos=zsos, ovr=ovr, ovr_unadj=ovr(shr), ovr_final=ovr(zsos))
    assert abs(hist['ovr_final'] - R['ovr']) < 0.02 and abs(hist['ovr_unadj'] - R['ovr_unadj']) < 0.02
    # outcome: side A vs B of this game, mean z_sos (unrated = 0), the page's model
    om = D['OUTCOME'].get(mp)
    sideA = [t for t in T if t['side'] == 'A'][0]; sideB = [t for t in T if t['side'] == 'B'][0]
    strength = lambda t: float(np.mean([r['zs'] or 0.0 for r in t['rows'] if not r.get('obscured')]))
    sA, sB = strength(sideA), strength(sideB); diff = sA - sB
    labA = ((sideA['team']['label'] or '') + ' ' + (sideA['team']['sublabel'] or '')).upper()
    home = 1.0 if (mp in HOME and any(x in labA for x in HOME[mp][1])) else 0.0
    pA = 1 / (1 + math.exp(-(om['logit'][0] + om['home_logit'] * home + om['logit'][1] * diff)))
    loser = clamp(om['loser'][0] + om['loser'][1] * abs(diff), 0.25 * om['cap'], om['cap'] - 1)
    margin = (2 * pA - 1) * (om['cap'] - loser)
    sc = [g['score_left'], g['score_right']]; left_is_A = (T[0]['side'] == 'A')
    actA, actB = (sc[0], sc[1]) if left_is_A else (sc[1], sc[0])
    # his projected stats in this room, the page's way (lobby = both teams except himself; average-game baseline when no clock)
    others = [r['zs'] or 0.0 for t in T for r in t['rows'] if not r['is_player']]
    zexp = zsos - float(np.mean(others))
    role = mine['team']['role']
    key = mp + '/' + ('attacker' if role == 'attacker' else 'defender') if mp in ('Docks', 'Skydock') else mp
    st = D['MAPSTATS'].get(key) or D['MAPSTATS'][mp]
    own = R['z_sd'] ** 2 if R['z_sd'] is not None and n >= 3 else run['var_w']
    spread = math.sqrt((n * own + 3 * run['var_w']) / (n + 3))
    length = (om['cap'] + loser) / 1000.0 if st.get('rate') and st['rate']['unit'] == 'per 1000 pts' else (om.get('minutes') if st.get('rate') else None)
    if st.get('rate') and length:
        rt = st['rate']; proj = dict(k=length * (rt['k'][0] + zexp * rt['k'][1]), kr=length * spread * rt['k'][1], d=length * (rt['d'][0] + zexp * rt['d'][1]), dr=length * spread * rt['d'][1], base=f'{key} per {rt["unit"][4:]} × projected length')
    else:
        proj = dict(k=st['k'][0] + zexp * st['k'][1], kr=spread * st['k'][1], d=st['d'][0] + zexp * st['d'][1], dr=spread * st['d'][1], base=f'{key} average game')
    out = dict(om=om, A=sideA, B=sideB, sA=sA, sB=sB, diff=diff, home=home, pA=pA, loser=loser, margin=margin, actA=actA, actB=actB, zexp=zexp,
               others_mean=float(np.mean(others)), proj=proj, st=st, spread=spread, me=me, mine=mine)
    return ex, hist, out


# ---------------------------------------------------------------- drawing helpers
def box(fig, x, y, w, h, fc=SURF, ec=LINE, alpha=1.0, lw=1.0, r=0.008):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={r}', transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=alpha, zorder=-1)   # under any axes (figure draws axes before patches at equal zorder)
    fig.patches.append(p); return p


def txt(fig, x, y, s, size=13, color=TEXT, alpha=1.0, ha='left', va='top', mono=False, weight='normal', wrap=None, ls=1.35, **kw):
    if alpha <= 0.01:
        return
    if wrap:
        s = '\n'.join(textwrap.fill(par, wrap) for par in s.split('\n'))
    fig.text(x, y, s, fontsize=size, color=color, alpha=alpha, ha=ha, va=va, family=MONO if mono else SANS, weight=weight, linespacing=ls, **kw)


def chrome(fig, step, title, D, n_steps=7):
    """Header: step pills; title; footer with provenance."""
    names = ['one game', 'every game', 'room strength', 'OVR', 'win probability', 'score & stats', 'the chain']
    x = 0.04
    for i, nm in enumerate(names):
        on = i == step - 1; done = i < step - 1
        col = TEXT if on else (MUTED if done else FAINT)
        txt(fig, x, 0.965, f'{i + 1}  {nm}', size=10.5, color=col, weight='bold' if on else 'normal')
        x += 0.02 + 0.0082 * len(nm) + (0.012 if nm.isupper() else 0) + 0.028
    txt(fig, 0.04, 0.915, title, size=22, weight='bold')
    R, run = D['rating'], D['run']
    txt(fig, 0.04, 0.03, f"{D['player']}  ·  {R['n_games']} scored games {R['first_date'][:7]} → {R['last_date'][:7]}  ·  ratings run {run['run_id']} "
        f"({D['run_label']}, {run['created']})  ·  data-only OVR: nothing from the hand list", size=9.5, color=FAINT, va='bottom')


def strip(fig, rect, vals, i_me, label, mean, sd, zval, t, t0, t1, fmt):
    """One measure across the group: dots, mean line, ±1 sd band, the player's z as a labelled gap."""
    p = seg(t, t0, t1)
    if p <= 0:
        return
    ax = fig.add_axes(rect); ax.set_facecolor(SURF)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.set_yticks([]); ax.tick_params(axis='x', labelsize=10, colors=MUTED)
    lo, hi = min(vals) - 0.12 * (max(vals) - min(vals)), max(vals) + 0.12 * (max(vals) - min(vals))
    ax.set_xlim(lo, hi); ax.set_ylim(-1, 1.6)
    ax.text(0.0, 1.02, label, transform=ax.transAxes, fontsize=12, color=MUTED, va='bottom', ha='left')
    order = np.argsort(vals)
    for rank, j in enumerate(order):                                      # dots arrive one by one
        a = seg(p, 0.0 + 0.4 * rank / len(vals), 0.15 + 0.4 * rank / len(vals))
        if a <= 0:
            continue
        me = j == i_me
        ax.scatter([vals[j]], [0], s=190 if me else 110, color=A_COL if me else MUTED, alpha=a, edgecolors=BG, linewidths=1.5, zorder=3 if me else 2)
    a2 = seg(p, 0.45, 0.65)
    if a2 > 0:
        ax.axvspan(mean - sd, mean + sd, color=MUTED, alpha=0.10 * a2, lw=0)
        ax.axvline(mean, color=MUTED, alpha=a2, lw=1.4, ls=(0, (4, 3)))
        ax.text(mean, -0.75, f'mean {fmt(mean)}', color=MUTED, fontsize=10.5, ha='center', va='top', alpha=a2)
        ax.text(mean + sd, -0.75, f'+1 sd = {fmt(sd)}', color=FAINT, fontsize=9.5, ha='left', va='top', alpha=a2)
    a3 = seg(p, 0.68, 0.92)
    if a3 > 0:
        v = vals[i_me]
        ax.annotate('', xy=(v, 0.55), xytext=(mean, 0.55), arrowprops=dict(arrowstyle='-|>', color=A_COL, lw=1.6, alpha=a3, shrinkA=0, shrinkB=4))
        ax.text(mean + (v - mean) / 2, 0.68, f'z = ({fmt(v)} − {fmt(mean)}) / {fmt(sd)} = {sgn(zval)}', color=TEXT, fontsize=12.5, ha='center', va='bottom',
                alpha=a3, family=MONO)
    return ax


def history_axes(fig, rect, hist, D):
    ax = fig.add_axes(rect); ax.set_facecolor(SURF)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    dates = [datetime.date.fromisoformat(h['date']) for h in hist['kept']] + [datetime.date.fromisoformat(h['date']) for h in hist['dropped']]
    ax.set_xlim(min(dates) - datetime.timedelta(days=70), max(dates) + datetime.timedelta(days=70)); ax.set_ylim(-2.7, 2.7)
    ax.axhline(0, color=LINE2, lw=1); ax.set_yticks([-2, -1, 0, 1, 2]); ax.set_yticklabels(['−2', '−1', '0', '+1', '+2'])
    ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y')); ax.tick_params(labelsize=10.5)
    ax.set_ylabel('z in that game', fontsize=11, color=MUTED)
    return ax


# ---------------------------------------------------------------- scenes (each draws the whole figure for progress t in [0, 1])
def scene_title(fig, t, D, ex, hist, out):
    a = seg(t, 0.0, 0.35)
    txt(fig, 0.5, 0.60, 'From a scoreboard to an OVR', size=34, weight='bold', ha='center', va='center', alpha=a)
    txt(fig, 0.5, 0.52, 'and from two rosters to a win probability and a score', size=20, color=MUTED, ha='center', va='center', alpha=seg(t, 0.15, 0.5))
    txt(fig, 0.5, 0.40, f"worked example: {D['player']}", size=18, color=A_COL, ha='center', va='center', alpha=seg(t, 0.35, 0.7), mono=True)
    R = D['rating']
    txt(fig, 0.5, 0.34, f"{R['n_games']} scored games on {R['n_maps']} maps  ·  final OVR {R['ovr']:.1f}  ·  nothing in it comes from a hand rating",
        size=13, color=FAINT, ha='center', va='center', alpha=seg(t, 0.5, 0.85))


def scene_game(fig, t, D, ex, hist, out):
    g = D['game']; me = out['me']; T = out['mine']
    chrome(fig, 1, f"One game: a z is a position inside the room  ·  {g['map']} {g['date']}, {T['team']['label']} vs {g['opp_clan']}", D)
    # the board (his group), left
    core = ex['core']; a = seg(t, 0.0, 0.15)
    x0, y0 = 0.04, 0.84
    box(fig, x0 - 0.01, 0.16, 0.33, 0.70, alpha=a)
    txt(fig, x0, y0, f"{T['team']['label']}  ·  {T['team']['role'] or T['team']['side']}  ·  {len(core)} scored players", size=12, color=MUTED, alpha=a)
    txt(fig, x0, y0 - 0.045, 'player', size=10.5, color=FAINT, alpha=a); txt(fig, x0 + 0.20, y0 - 0.045, 'kills', size=10.5, color=FAINT, alpha=a, ha='right')
    txt(fig, x0 + 0.29, y0 - 0.045, 'damage', size=10.5, color=FAINT, alpha=a, ha='right')
    for i, r in enumerate(core):
        yy = y0 - 0.085 - i * 0.048
        if r['is_player']:
            box(fig, x0 - 0.006, yy - 0.036, 0.316, 0.046, fc=SURF2, ec=A_COL, alpha=a, lw=1.2)
        col = TEXT if r['is_player'] else MUTED
        txt(fig, x0, yy, r['handle'][:17], size=12, color=col, mono=True, alpha=a, weight='bold' if r['is_player'] else 'normal')
        txt(fig, x0 + 0.20, yy, f"{r['kills']}", size=12, color=col, mono=True, alpha=a, ha='right')
        txt(fig, x0 + 0.29, yy, f"{r['dmg']:,}", size=12, color=col, mono=True, alpha=a, ha='right')
    grp = ('his own side: attackers and defenders do different jobs on Skydock and Docks, so each side is its own group'
           if ex['asym'] else 'both teams: on Warehouse and Ordana the whole board is one group')
    txt(fig, x0, 0.29, f'The comparison group is {grp}. Nobody is compared with anyone who was not in this room.', size=10.5, color=MUTED, alpha=a, wrap=60)
    # the two measures, right
    i = ex['i']
    strip(fig, [0.42, 0.66, 0.54, 0.16], [r['kills'] for r in core], i, 'kills, this room', ex['k_mean'], ex['k_sd'], ex['zk'][i], t, 0.12, 0.45, lambda v: f'{v:.1f}' if isinstance(v, float) else str(v))
    strip(fig, [0.42, 0.42, 0.54, 0.16], [r['dmg'] for r in core], i, 'damage, this room', ex['d_mean'], ex['d_sd'], ex['zd'][i], t, 0.42, 0.72, lambda v: f'{v:,.0f}')
    # composite
    a4 = seg(t, 0.72, 0.84); a5 = seg(t, 0.84, 1.0)
    if a4 > 0:
        box(fig, 0.42, 0.17, 0.54, 0.17, alpha=a4)
        txt(fig, 0.44, 0.32, 'one number for the game', size=12, color=MUTED, alpha=a4)
        txt(fig, 0.44, 0.28, f"0.5 × {sgn(ex['zk'][i])} + 0.5 × {sgn(ex['zd'][i])} = {sgn(ex['comp'][i])}", size=14, mono=True, alpha=a4)
        txt(fig, 0.44, 0.235, f"÷ {ex['sdc']:.3f} (spread of the {len(core)} composites, so one game sd = 1 again)  →  {sgn(ex['comp'][i] / ex['sdc'])}", size=12, mono=True, color=MUTED, alpha=a5)
        txt(fig, 0.44, 0.195, f"clipped to ±2.5 (one monster board cannot dominate a career)  →  z = {sgn(ex['zc'][i])}", size=13, mono=True, color=A_COL, alpha=a5, weight='bold')


def scene_games(fig, t, D, ex, hist, out):
    chrome(fig, 2, f"Every game: {hist['n']} z's, one average", D)
    ax = history_axes(fig, [0.07, 0.17, 0.58, 0.66], hist, D)
    dates = [datetime.date.fromisoformat(h['date']) for h in hist['kept']]
    n = len(dates)
    for j, (d, z) in enumerate(zip(dates, hist['z'])):
        a = seg(t, 0.02 + 0.5 * j / n, 0.08 + 0.5 * j / n)
        if a > 0:
            ax.scatter([d], [z], s=70, color=A_COL, alpha=a, edgecolors=BG, linewidths=1, zorder=3)
    a_d = seg(t, 0.55, 0.65)
    if a_d > 0 and hist['dropped']:
        dd = [datetime.date.fromisoformat(h['date']) for h in hist['dropped']]; dz = [h['z_comp'] for h in hist['dropped']]
        ax.scatter(dd, dz, s=90, marker='x', color=DISCARD, alpha=a_d, linewidths=2, zorder=3)
        ax.annotate(f'{len(dd)} discarded: more than {D["run"]["outlier_gap"]:.0f} z under the rest of his games and under the room average,\nthe signature of a late join (no time-played column exists)',
                    xy=(dd[0], dz[0]), xytext=(0.03, 0.06), textcoords='axes fraction', fontsize=9.5, color=DISCARD, alpha=a_d,
                    arrowprops=dict(arrowstyle='-', color=DISCARD, alpha=0.6 * a_d, lw=0.8))
    a_m = seg(t, 0.62, 0.78)
    if a_m > 0:
        ax.axhline(hist['z_mean'] * a_m, color=A_COL, lw=2, alpha=0.9)
        ax.text(ax.get_xlim()[1], hist['z_mean'] * a_m + 0.08, f"mean z = {sgn(hist['z_mean'])}", color=A_COL, fontsize=12, ha='right', va='bottom', family=MONO)
    # right card
    a_c = seg(t, 0.72, 0.86); a_c2 = seg(t, 0.86, 1.0)
    if a_c > 0:
        box(fig, 0.69, 0.30, 0.28, 0.53, alpha=a_c)
        txt(fig, 0.71, 0.80, 'a first rating', size=12, color=MUTED, alpha=a_c)
        txt(fig, 0.71, 0.755, f"mean of {hist['n']} games   {sgn(hist['z_mean'])}", size=13, mono=True, alpha=a_c)
        txt(fig, 0.71, 0.70, f"shrink toward 0 by n / (n + k)\nk = {hist['k']:.3f} = within-player ÷ between-player variance\n(how much one game can be trusted)", size=10.5, color=MUTED, alpha=a_c, ls=1.4)
        txt(fig, 0.71, 0.585, f"{sgn(hist['z_mean'])} × {hist['n']} / {hist['n'] + hist['k']:.3f} = {sgn(hist['shr'])}", size=13, mono=True, alpha=a_c)
        txt(fig, 0.71, 0.50, f"on the OVR scale that would be {hist['ovr_unadj']:.1f}", size=12.5, alpha=a_c2)
        txt(fig, 0.71, 0.45, 'but every z here was measured against a different room. A +2 among weak teammates is not the same as a +2 among strong ones.',
            size=11, color=MUTED, alpha=a_c2, wrap=44)


def scene_lobby(fig, t, D, ex, hist, out):
    chrome(fig, 3, 'Room strength: each z is moved by who was in the room', D)
    ax = history_axes(fig, [0.07, 0.17, 0.58, 0.66], hist, D)
    dates = [datetime.date.fromisoformat(h['date']) for h in hist['kept']]
    z, lob, y = hist['z'], hist['lob'], hist['y']
    a_l = seg(t, 0.02, 0.22); a_mv = seg(t, 0.25, 0.55); a_m = seg(t, 0.55, 0.68)
    for d, zi, li, yi in zip(dates, z, lob, y):
        pos = zi + (yi - zi) * a_mv
        if a_l > 0:
            ax.plot([d - datetime.timedelta(days=9), d + datetime.timedelta(days=9)], [li, li], color=MUTED, lw=2, alpha=0.9 * a_l, zorder=2)
        if a_mv > 0:
            ax.plot([d, d], [zi, pos], color=A_COL, lw=1, alpha=0.5, zorder=2)
            ax.scatter([d], [zi], s=70, facecolors='none', edgecolors=A_COL, linewidths=1, alpha=0.5, zorder=2)
        ax.scatter([d], [pos], s=70, color=A_COL, edgecolors=BG, linewidths=1, zorder=3)
    if a_l > 0:
        ax.text(0.01, 0.97, '— room strength: the mean rating of the other players in his group that game', transform=ax.transAxes, fontsize=10.5, color=MUTED, va='top', alpha=a_l)
    if a_m > 0:
        ax.axhline(hist['z_mean'], color=A_COL, lw=1.2, ls=(0, (4, 3)), alpha=0.5 * a_m)
        ax.axhline(hist['y_mean'], color=A_COL, lw=2, alpha=a_m)
        ax.text(ax.get_xlim()[1], hist['y_mean'] - 0.1, f"adjusted mean {sgn(hist['y_mean'])}", color=A_COL, fontsize=12, ha='right', va='top', family=MONO, alpha=a_m)
        ax.text(ax.get_xlim()[1], hist['z_mean'] + 0.08, f"raw {sgn(hist['z_mean'])}", color=A_COL, fontsize=10.5, ha='right', va='bottom', family=MONO, alpha=0.6 * a_m)
    a_c = seg(t, 0.3, 0.45); a_c2 = seg(t, 0.62, 0.76); a_c3 = seg(t, 0.78, 0.95)
    if a_c > 0:
        box(fig, 0.69, 0.17, 0.28, 0.66, alpha=a_c)
        txt(fig, 0.71, 0.80, 'adjusted value of a game', size=12, color=MUTED, alpha=a_c)
        txt(fig, 0.71, 0.76, 'y = z + room strength', size=13.5, mono=True, alpha=a_c)
        txt(fig, 0.71, 0.715, f"his rooms averaged {sgn(hist['lob_mean'])}: he was usually the strongest player on his side, so the raw +{hist['z_mean']:.2f} overstates him.",
            size=11, color=MUTED, alpha=a_c, wrap=44)
        txt(fig, 0.71, 0.60, 'solved jointly', size=12, color=MUTED, alpha=a_c2)
        txt(fig, 0.71, 0.565, f"room strength is made of other players' ratings, which depend on their rooms. All {D['run']['players']:,} players and "
            f"{D['run']['player_games']:,} player-games are fitted together, iterated until nothing moves.", size=11, color=MUTED, alpha=a_c2, wrap=44)
        txt(fig, 0.71, 0.42, 'his rating', size=12, color=MUTED, alpha=a_c3)
        txt(fig, 0.71, 0.385, f"mean y          {sgn(hist['y_mean'])}\n× {hist['n']}/({hist['n']}+{hist['k']:.3f})   {sgn(hist['y_shr'])}\ncentred         {sgn(-hist['centre'])}",
            size=12.5, mono=True, alpha=a_c3, ls=1.5)
        txt(fig, 0.71, 0.245, f"z = {sgn(hist['zsos'])}", size=18, mono=True, color=A_COL, weight='bold', alpha=a_c3)
        txt(fig, 0.71, 0.205, 'centring: the average player-game in the data is 0', size=9.5, color=FAINT, alpha=a_c3)


def scene_ovr(fig, t, D, ex, hist, out):
    chrome(fig, 4, 'OVR: the same number on a familiar scale', D)
    run = D['run']; R = D['rating']
    ax = fig.add_axes([0.07, 0.50, 0.60, 0.16]); ax.set_facecolor(BG)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.set_yticks([]); ax.set_xlim(62, 97.5); ax.set_ylim(0, 1); ax.set_xticks(range(65, 100, 5)); ax.tick_params(labelsize=11)
    ax.axvspan(62, run['ovr_cap'], ymin=0.42, ymax=0.58, color=SURF2, lw=0)
    ax.axvline(run['ovr_mean'], color=MUTED, lw=1.2, ls=(0, (4, 3))); ax.text(run['ovr_mean'] - 0.4, 0.62, f"{run['ovr_mean']:.0f} = average participant", color=MUTED, fontsize=10.5, ha='right', va='bottom')
    ax.axvline(run['ovr_cap'], color=MUTED, lw=1.2); ax.text(run['ovr_cap'], 0.62, f"cap {run['ovr_cap']:.0f}", color=MUTED, fontsize=10.5, ha='center', va='bottom')
    a1 = seg(t, 0.05, 0.3); a2 = seg(t, 0.35, 0.65)
    if a1 > 0:
        xu = run['ovr_mean'] + (hist['ovr_unadj'] - run['ovr_mean']) * a1
        ax.scatter([xu], [0.5], s=260, facecolors='none', edgecolors=A_COL, linewidths=1.6, zorder=3)
        ax.text(xu, 0.80, f'unadjusted {hist["ovr_unadj"]:.1f}', color=A_COL, fontsize=11, ha='center', va='bottom', alpha=0.7 * a1, family=MONO)
    if a2 > 0:
        xf = hist['ovr_unadj'] + (hist['ovr_final'] - hist['ovr_unadj']) * a2
        ax.scatter([xf], [0.5], s=300, color=A_COL, edgecolors=BG, linewidths=1.5, zorder=4)
        ax.text(xf, 0.05, f'OVR {hist["ovr_final"]:.1f}', color=A_COL, fontsize=15, ha='center', va='bottom', weight='bold', family=MONO)
    txt(fig, 0.07, 0.80, f"OVR = {run['ovr_mean']:.0f} + {run['ovr_sd']:.0f} × z / {run['sd_b']:.3f}", size=17, mono=True, alpha=seg(t, 0.0, 0.15))
    txt(fig, 0.07, 0.745, f"{run['sd_b']:.3f} is the between-player sd of the ratings, so one between-player sd is {run['ovr_sd']:.0f} OVR; "
        f"{run['ovr_mean']:.0f} is the average player in these lobbies, not a tier boundary. No floor; the top is clipped at {run['ovr_cap']:.0f}.", size=11.5, color=MUTED, alpha=seg(t, 0.0, 0.15), wrap=92)
    txt(fig, 0.07, 0.40, f"= {run['ovr_mean']:.0f} + {run['ovr_sd']:.0f} × {sgn(hist['zsos'])} / {run['sd_b']:.3f} = {hist['ovr_final']:.1f}", size=15, mono=True, color=A_COL, alpha=a2)
    txt(fig, 0.07, 0.35, f"± {R['ovr_sigma']:.2f}: the standard error after {hist['n']} games", size=11, color=MUTED, alpha=a2)
    a3 = seg(t, 0.62, 0.9)
    if a3 > 0:
        box(fig, 0.71, 0.33, 0.26, 0.50, alpha=a3)
        txt(fig, 0.73, 0.80, 'per map, the same recipe', size=12, color=MUTED, alpha=a3)
        txt(fig, 0.73, 0.76, "that map's adjusted values only, shrunk the same way; a map with no games shows the overall OVR instead", size=10.5, color=MUTED, alpha=a3, wrap=40)
        yy = 0.655
        for mp, key in (('Skydock', 'skydock'), ('Docks', 'docks'), ('Warehouse', 'warehouse'), ('Ordana', 'ordana')):
            nn, ov = R['n_' + key], R['ovr_' + key]
            txt(fig, 0.73, yy, f'{mp:<10}', size=12.5, mono=True, color=TEXT if nn else FAINT, alpha=a3)
            txt(fig, 0.95, yy, (f'{ov:.1f}   ×{nn}' if nn else '—  (overall)'), size=12.5, mono=True, color=TEXT if nn else FAINT, alpha=a3, ha='right')
            yy -= 0.055
        txt(fig, 0.73, 0.40, 'overall', size=12.5, mono=True, color=A_COL, alpha=a3, weight='bold')
        txt(fig, 0.95, 0.40, f"{R['ovr']:.1f}   ×{R['n_games']}", size=12.5, mono=True, color=A_COL, alpha=a3, ha='right', weight='bold')


def roster(fig, x, y, team, col, t, a0, a1, title, sp):
    rows = team['rows']; a = seg(t, a0, a1)
    txt(fig, x, y, title, size=12, color=col, weight='bold', alpha=a)
    for i, r in enumerate(rows):
        aa = seg(t, a0 + (a1 - a0) * i / len(rows), a0 + (a1 - a0) * (i + 1) / len(rows))
        yy = y - 0.04 - i * sp
        col_r = TEXT if r['is_player'] else MUTED
        txt(fig, x, yy, r['handle'][:16], size=10.5, mono=True, color=col_r, alpha=aa, weight='bold' if r['is_player'] else 'normal')
        txt(fig, x + 0.19, yy, (f"{r['ovr']:.1f}" if r['ovr'] is not None else 'unrated'), size=10.5, mono=True, color=col_r, alpha=aa, ha='right')
        txt(fig, x + 0.245, yy, (sgn(r['zs']) if r['zs'] is not None else '0.00'), size=10.5, mono=True, color=FAINT, alpha=aa, ha='right')
    return y - 0.04 - len(rows) * sp


def scene_win(fig, t, D, ex, hist, out):
    g = D['game']; om = out['om']
    chrome(fig, 5, f"Win probability: two rosters, one strength difference  ·  {g['map']} {g['date']}", D)
    A, B = out['A'], out['B']
    labA = A['team']['label'] or 'side A'; labB = B['team']['label'] or 'side B'
    sp = min(0.031, 0.60 / (len(A['rows']) + len(B['rows']) + 5))                 # row pitch: both rosters and the box must fit
    yA = roster(fig, 0.05, 0.84, A, A_COL, t, 0.0, 0.2, f"{labA}  ({om['side_a']}, side A)", sp)
    yB = roster(fig, 0.05, yA - 0.045, B, B_COL, t, 0.18, 0.36, f"{labB}  (side B)", sp)
    txt(fig, 0.30, 0.84, 'OVR', size=9.5, color=FAINT, ha='right', alpha=seg(t, 0.0, 0.1)); txt(fig, 0.345, 0.84, 'z', size=9.5, color=FAINT, ha='right', alpha=seg(t, 0.0, 0.1))
    a_s = seg(t, 0.36, 0.5)
    if a_s > 0:
        yb = max(0.06, yB - 0.15)
        box(fig, 0.04, yb, 0.31, 0.125, alpha=a_s)
        txt(fig, 0.055, yb + 0.11, f"mean z   A {sgn(out['sA'])}    B {sgn(out['sB'])}", size=12.5, mono=True, alpha=a_s)
        txt(fig, 0.055, yb + 0.066, f"difference A − B = {sgn(out['diff'])}", size=13.5, mono=True, color=TEXT, weight='bold', alpha=a_s)
        txt(fig, 0.055, yb + 0.022, 'unrated players count as 0 (average)', size=9.5, color=FAINT, alpha=a_s)
    # logistic
    ax = fig.add_axes([0.44, 0.20, 0.52, 0.62]); ax.set_facecolor(SURF)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.set_xlim(-1.3, 1.3); ax.set_ylim(0, 1.02); ax.set_yticks([0, .25, .5, .75, 1]); ax.set_yticklabels(['0', '25', '50', '75', '100%']); ax.tick_params(labelsize=10.5)
    ax.set_xlabel('strength difference, side A − side B (mean rating z)', fontsize=11, color=MUTED); ax.axvline(0, color=LINE2, lw=1); ax.axhline(0.5, color=LINE2, lw=1)
    a_b = seg(t, 0.40, 0.55); a_f = seg(t, 0.5, 0.7); a_p = seg(t, 0.7, 0.9)
    if a_b > 0:
        for b in om['bins']:
            ax.scatter([(b['lo'] + b['hi']) / 2], [b['win']], s=14 * b['n'], color=MUTED, alpha=0.55 * a_b, edgecolors=BG, linewidths=1, zorder=2)
        ax.text(0.02, 0.97, f"grey: finished two-sided {g['map']} games grouped by strength difference\n(dot area = games, {om['n']} in all). Victory channels are left out:\na win-only sample says nothing about losing.",
                transform=ax.transAxes, fontsize=9.5, color=MUTED, alpha=a_b, va='top')
    if a_f > 0:
        xs = np.linspace(-1.3, 1.3, 200); xs = xs[: max(2, int(len(xs) * a_f))]
        ys = 1 / (1 + np.exp(-(om['logit'][0] + om['home_logit'] * out['home'] + om['logit'][1] * xs)))
        ax.plot(xs, ys, color=TEXT, lw=2, zorder=3)
        ax.text(0.98, 0.30, f"P(A wins) = 1 / (1 + e^−({om['logit'][0]:.2f} + {om['logit'][1]:.2f} × diff{(' + %.2f × home' % om['home_logit']) if om['home_clan'] else ''}))",
                transform=ax.transAxes, fontsize=11, color=TEXT, ha='right', va='top', family=MONO, alpha=a_f)
        base = 1 / (1 + math.exp(-om['logit'][0]))
        ax.text(0.98, 0.23, f"at even strength side A wins {100 * base:.0f}% here" + (f"\n(home clan {om['home_clan']} adds {om['home_logit']:.2f} on the logit)" if om['home_clan'] else ''),
                transform=ax.transAxes, fontsize=10, color=MUTED, ha='right', va='top', alpha=a_f)
    if a_p > 0:
        xd = out['diff'] * a_p; pd_ = 1 / (1 + math.exp(-(om['logit'][0] + om['home_logit'] * out['home'] + om['logit'][1] * xd)))
        ax.plot([xd, xd], [0, pd_], color=A_COL, lw=1.2, ls=(0, (3, 3)), alpha=0.8); ax.plot([-1.3, xd], [pd_, pd_], color=A_COL, lw=1.2, ls=(0, (3, 3)), alpha=0.8)
        ax.scatter([xd], [pd_], s=220, color=A_COL, edgecolors=BG, linewidths=1.5, zorder=5)
        ax.text(xd + 0.05, pd_ - 0.07, f"{labA} {100 * pd_:.0f}%", color=A_COL, fontsize=15, weight='bold', family=MONO, va='top')


def scene_score(fig, t, D, ex, hist, out):
    g = D['game']; om = out['om']; A, B = out['A'], out['B']; labA = A['team']['label'] or 'A'; labB = B['team']['label'] or 'B'
    chrome(fig, 6, 'Score and stats: what the same strengths say about the final board', D)
    a1 = seg(t, 0.0, 0.18); a2 = seg(t, 0.18, 0.36); a3 = seg(t, 0.36, 0.5)
    box(fig, 0.04, 0.43, 0.44, 0.41, alpha=a1)
    txt(fig, 0.06, 0.81, "the loser's score", size=12, color=MUTED, alpha=a1)
    txt(fig, 0.06, 0.77, f"{om['loser'][0]:.0f} {'−' if om['loser'][1] < 0 else '+'} {abs(om['loser'][1]):.1f} × |diff|  =  {om['loser'][0]:.0f} {'−' if om['loser'][1] < 0 else '+'} {abs(om['loser'][1]):.1f} × {abs(out['diff']):.2f}  =  {out['loser']:.0f}",
        size=12.5, mono=True, alpha=a1)
    txt(fig, 0.06, 0.725, f"a straight line through the same {om['n']} games (± {om['loser_sd']:.0f} around it); the winner reaches the cap of {om['cap']:,}", size=10.5, color=MUTED, alpha=a1, wrap=70)
    fav, dog, pf = (labA, labB, out['pA']) if out['pA'] >= 0.5 else (labB, labA, 1 - out['pA'])
    txt(fig, 0.06, 0.645, f"projected   {fav} {om['cap']:,} – {out['loser']:.0f} {dog}   ({100 * pf:.0f}%)", size=14, mono=True, weight='bold', alpha=a2)
    txt(fig, 0.06, 0.60, f"expected margin = (2p − 1) × (cap − loser)\n= ({2 * out['pA']:.2f} − 1) × ({om['cap']:,} − {out['loser']:.0f}) = {sgn(out['margin'], 0)} for {labA}", size=11, mono=True, color=MUTED, alpha=a2, ls=1.45)
    txt(fig, 0.06, 0.53, f"length: {om['cap'] + out['loser']:,.0f} points in all" + (f" (a clock on Docks: {om['minutes']:.1f} min)" if om.get('minutes') else ''), size=11, color=MUTED, alpha=a2)
    if a3 > 0:
        txt(fig, 0.06, 0.485, f"actual       {labA} {out['actA']:,} – {out['actB']:,} {labB}", size=14, mono=True, color=A_COL, alpha=a3)
    # score bars
    ax = fig.add_axes([0.15, 0.22, 0.31, 0.14]); ax.set_facecolor(BG); ax.set_xlim(0, om['cap'] * 1.05); ax.set_ylim(-0.6, 1.6); ax.axis('off')
    if a2 > 0:
        pa, pb = (om['cap'], out['loser']) if out['pA'] >= 0.5 else (out['loser'], om['cap'])
        ax.barh([1], [pa * a2], height=0.5, color=A_COL, alpha=0.9); ax.barh([0], [pb * a2], height=0.5, color=B_COL, alpha=0.9)
        ax.text(-20, 1, labA, ha='right', va='center', color=A_COL, fontsize=10.5, family=MONO); ax.text(-20, 0, labB, ha='right', va='center', color=B_COL, fontsize=10.5, family=MONO)
        ax.text(pa * a2 + 15, 1, f'{pa:,.0f}', va='center', color=TEXT, fontsize=10.5, family=MONO); ax.text(pb * a2 + 15, 0, f'{pb:,.0f}', va='center', color=TEXT, fontsize=10.5, family=MONO)
    if a3 > 0:
        for yy, v in ((1, out['actA']), (0, out['actB'])):
            ax.plot([v, v], [yy - 0.38, yy + 0.38], color=TEXT, lw=2, alpha=a3); ax.text(v, yy + 0.42, 'actual', ha='center', va='bottom', color=MUTED, fontsize=8.5, alpha=a3)
    # his stats
    a4 = seg(t, 0.5, 0.68); a5 = seg(t, 0.68, 0.82); a6 = seg(t, 0.82, 0.96); P = out['proj']; me = out['me']
    if a4 > 0:
        box(fig, 0.52, 0.17, 0.45, 0.67, alpha=a4)
        txt(fig, 0.54, 0.81, f"{D['player']} in this room", size=12, color=MUTED, alpha=a4)
        txt(fig, 0.54, 0.77, f"expected z = rating − mean of the other {len(A['rows']) + len(B['rows']) - 1} = {sgn(hist['zsos'])} − ({sgn(out['others_mean'])}) = {sgn(out['zexp'])}", size=11.5, mono=True, alpha=a4)
        txt(fig, 0.54, 0.725, f"baseline: {P['base']}  ·  kills {out['st']['k'][0]:.1f} + z × {out['st']['k'][1]:.1f}, damage {out['st']['d'][0]:,.0f} + z × {out['st']['d'][1]:,.0f}", size=10, color=MUTED, alpha=a4, wrap=78)
        txt(fig, 0.54, 0.655, f"kills    {P['k']:.0f} ± {P['kr']:.0f}\ndamage   {P['d']:,.0f} ± {P['dr']:,.0f}", size=14, mono=True, alpha=a5, ls=1.5)
        txt(fig, 0.54, 0.555, f"± is his own game-to-game spread ({out['spread']:.2f} z), blended toward the population spread when a player has few games", size=10, color=MUTED, alpha=a5, wrap=78)
    if a5 > 0:
        for j, (lab, mu, sd, act, lim) in enumerate((('kills', P['k'], P['kr'], me['kills'], None), ('damage', P['d'], P['dr'], me['dmg'], None))):
            axp = fig.add_axes([0.56, 0.37 - j * 0.11, 0.38, 0.07]); axp.set_facecolor(BG); axp.axis('off')
            hi = max(mu + 2.2 * sd, act * 1.1); axp.set_xlim(0, hi); axp.set_ylim(-1, 1)
            axp.barh([0], [2 * sd * a5], left=[mu - sd], height=0.6, color=A_COL, alpha=0.35)
            axp.plot([mu, mu], [-0.45, 0.45], color=A_COL, lw=2.2)
            axp.text(0, 0.95, lab, color=MUTED, fontsize=10, va='bottom'); axp.text(mu, -0.55, f'{mu:,.0f}', color=A_COL, fontsize=10, ha='center', va='top', family=MONO)
            if a6 > 0:
                axp.plot([act, act], [-0.6, 0.6], color=TEXT, lw=2.2, alpha=a6); axp.text(act, 0.7, f'actual {act:,}', color=TEXT, fontsize=10.5, ha='center', va='bottom', family=MONO, alpha=a6)


def scene_chain(fig, t, D, ex, hist, out):
    chrome(fig, 7, 'The whole chain', D)
    steps = [('board', 'kills and damage,\nnames only'), ('z in the room', f"{sgn(ex['zc'][ex['i']])} in the\nexample game"), ('all games', f"{hist['n']} games,\nmean {sgn(hist['z_mean'])}"),
             ('room strength', f"adjusted mean\n{sgn(hist['y_mean'])}, joint fit"), ('rating', f"shrunk, centred\nz = {sgn(hist['zsos'])}"), ('OVR', f"{D['run']['ovr_mean']:.0f} + {D['run']['ovr_sd']:.0f}·z/{D['run']['sd_b']:.2f}\n= {hist['ovr_final']:.1f}")]
    n = len(steps); x0, w, gap = 0.04, 0.135, 0.019
    for i, (h, s) in enumerate(steps):
        a = seg(t, 0.05 * i, 0.05 * i + 0.12)
        if a <= 0:
            continue
        x = x0 + i * (w + gap)
        box(fig, x, 0.60, w, 0.18, fc=SURF2 if i == n - 1 else SURF, ec=A_COL if i == n - 1 else LINE2, alpha=a)
        txt(fig, x + w / 2, 0.755, h, size=13, weight='bold', ha='center', alpha=a)
        txt(fig, x + w / 2, 0.705, s, size=10.5, color=MUTED, ha='center', mono=True, alpha=a, ls=1.4)
        if i < n - 1:
            txt(fig, x + w + gap / 2, 0.69, '→', size=16, color=FAINT, ha='center', va='center', alpha=a)
    a2 = seg(t, 0.4, 0.55)
    txt(fig, 0.5, 0.53, '↓   two rosters, averaged', size=12, color=MUTED, ha='center', alpha=a2)
    steps2 = [('strength difference', f"A − B = {sgn(out['diff'])}"), ('win probability', f"logistic fit\n{out['A']['team']['label']} {100 * out['pA']:.0f}%"),
              ('score', f"loser {out['loser']:.0f}\n{out['om']['cap']:,} – {out['loser']:.0f}"), ('stats per player', f"expected z × baseline\n{out['proj']['k']:.0f} k, {out['proj']['d']:,.0f} dmg")]
    w2 = 0.19
    for i, (h, s) in enumerate(steps2):
        a = seg(t, 0.5 + 0.08 * i, 0.62 + 0.08 * i)
        if a <= 0:
            continue
        x = 0.5 - (len(steps2) * w2 + (len(steps2) - 1) * gap) / 2 + i * (w2 + gap)
        box(fig, x, 0.30, w2, 0.17, alpha=a)
        txt(fig, x + w2 / 2, 0.445, h, size=13, weight='bold', ha='center', alpha=a)
        txt(fig, x + w2 / 2, 0.395, s, size=10.5, color=MUTED, ha='center', mono=True, alpha=a, ls=1.4)
        if i < len(steps2) - 1:
            txt(fig, x + w2 + gap / 2, 0.385, '→', size=16, color=FAINT, ha='center', va='center', alpha=a)
    txt(fig, 0.5, 0.20, 'Everything above is recomputed from the database on every run; no number is typed in by hand.', size=11.5, color=FAINT, ha='center', alpha=seg(t, 0.85, 1.0))


SCENES = [(scene_title, 4.0), (scene_game, 18.0), (scene_games, 14.0), (scene_lobby, 18.0), (scene_ovr, 13.0), (scene_win, 16.0), (scene_score, 18.0), (scene_chain, 10.0)]
HOLD = 1.2      # seconds the finished state of each scene stays on screen before the next


def render(D, ex, hist, out, path, fps=FPS):
    import imageio_ffmpeg
    plt.rcParams['animation.ffmpeg_path'] = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    writer = FFMpegWriter(fps=fps, codec='libx264', bitrate=-1, extra_args=['-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-crf', '19', '-preset', 'medium'])
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    total = sum(int((d + HOLD) * fps) for _, d in SCENES); done = 0
    with writer.saving(fig, path, DPI):
        for fn, dur in SCENES:
            n = int(dur * fps); hold = int(HOLD * fps)
            for i in range(n + hold):
                fig.clear(); fig.patches.clear()
                fn(fig, min(1.0, i / max(1, n - 1)), D, ex, hist, out)
                writer.grab_frame(); done += 1
                if done % (10 * fps) == 0:
                    print(f'  {done}/{total} frames', flush=True)
    plt.close(fig)
    print('wrote', path, f'{os.path.getsize(path) / 1e6:.1f} MB', f'{total / fps:.0f} s')


def preview(D, ex, hist, out, folder):
    os.makedirs(folder, exist_ok=True)
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    for si, (fn, _) in enumerate(SCENES):
        for tt in (0.4, 1.0):
            fig.clear(); fig.patches.clear(); fn(fig, tt, D, ex, hist, out)
            p = os.path.join(folder, f'scene{si}_{int(tt * 100):03d}.png'); fig.savefig(p, dpi=DPI, facecolor=BG); print('wrote', p)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('player'); ap.add_argument('--game', type=int, required=True, help='game_id of the example board (the player must be on it)')
    ap.add_argument('--run', default='all-years'); ap.add_argument('--out'); ap.add_argument('--preview'); ap.add_argument('--fps', type=int, default=FPS)
    a = ap.parse_args()
    D = load(a.player, a.game, a.run); ex, hist, out = derive(D)
    print(f"{a.player}: n={hist['n']} mean z {hist['z_mean']:+.3f} rooms {hist['lob_mean']:+.3f} adjusted {hist['y_mean']:+.3f} -> z_sos {hist['zsos']:+.4f} OVR {hist['ovr_final']:.2f} (unadjusted {hist['ovr_unadj']:.2f})")
    print(f"example game {a.game}: z {ex['zc'][ex['i']]:+.2f}; strengths A {out['sA']:+.3f} B {out['sB']:+.3f} diff {out['diff']:+.3f} P(A) {out['pA']:.3f} loser {out['loser']:.0f} actual {out['actA']}-{out['actB']}; "
          f"proj k {out['proj']['k']:.1f}±{out['proj']['kr']:.1f} d {out['proj']['d']:.0f}±{out['proj']['dr']:.0f} actual {out['me']['kills']}/{out['me']['dmg']}")
    if a.preview:
        preview(D, ex, hist, out, a.preview)
    if a.out:
        render(D, ex, hist, out, a.out, a.fps)


if __name__ == '__main__':
    main()
