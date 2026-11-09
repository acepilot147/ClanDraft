"""raids.sqlite: schema + imports. Every row traces back to an image (sha256),
an audit-log line, or a repo CSV, and every derived number to a run row.

  python -I raid_db.py init                      create tables (idempotent)
  python -I raid_db.py import-manifest           sources/vak_screenshots/manifest.csv -> images / image_audit_rows
  python -I raid_db.py import-repo               RaidStats.csv + Games.csv (M1..Mn) -> games / teams / player_games
  python -I raid_db.py build-games               best transcription per image -> games / teams / player_games
  python -I raid_db.py status                    counts per table / per status
"""
import sqlite3, csv, os, sys, json, hashlib, datetime, re, subprocess, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'raids.sqlite')
SHOTS = os.path.join(ROOT, 'sources', 'vak_screenshots')
MANIFEST = os.path.join(SHOTS, 'manifest.csv')
STATS = ('kills', 'deaths', 'dmg', 'heals', 'assists', 'caps', 'points')
INFERRED_MAP_SOURCES = {'sol_victories'}      # sources whose map was inferred (shout pairing) rather than recorded

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  source_id INTEGER PRIMARY KEY, name TEXT UNIQUE, kind TEXT, path TEXT, sha256 TEXT, imported_at TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS images (
  image_id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources, file TEXT UNIQUE, sha256 TEXT UNIQUE,
  width INTEGER, height INTEGER, bytes INTEGER, audit_date TEXT, audit_map TEXT, audit_type TEXT, audit_clan TEXT,
  audit_leader TEXT, audit_result TEXT, audit_challenge TEXT, audit_auditor TEXT, audit_line INTEGER, url TEXT, image_url TEXT);
CREATE TABLE IF NOT EXISTS image_audit_rows (
  image_id INTEGER REFERENCES images, audit_line INTEGER, link_no INTEGER, audit_date TEXT, audit_map TEXT, audit_type TEXT,
  audit_clan TEXT, audit_leader TEXT, audit_result TEXT, audit_challenge TEXT, audit_auditor TEXT, url TEXT, status TEXT,
  PRIMARY KEY (audit_line, link_no));
CREATE TABLE IF NOT EXISTS transcriptions (
  transcription_id INTEGER PRIMARY KEY, image_id INTEGER REFERENCES images, attempt INTEGER, model TEXT, prompt_version TEXT,
  effort TEXT, tiled INTEGER, created_at TEXT, status TEXT, checks_json TEXT, raw_json TEXT, input_tokens INTEGER,
  output_tokens INTEGER, cost_usd REAL, error TEXT);
CREATE INDEX IF NOT EXISTS ix_transcriptions_image ON transcriptions(image_id);
CREATE TABLE IF NOT EXISTS image_refs (
  source_id INTEGER REFERENCES sources, ref TEXT, link_no INTEGER, date TEXT, map TEXT, type TEXT, clan TEXT, leader TEXT,
  result TEXT, url TEXT, status TEXT, image_id INTEGER REFERENCES images, extra TEXT, PRIMARY KEY (source_id, ref, link_no));
CREATE TABLE IF NOT EXISTS games (
  game_id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources, image_id INTEGER REFERENCES images,
  transcription_id INTEGER REFERENCES transcriptions, ext_id TEXT, map TEXT, date TEXT, event_type TEXT, opp_clan TEXT,
  format TEXT, banner TEXT, score_left INTEGER, score_right INTEGER, match_time TEXT, verified_status TEXT,
  fingerprint TEXT, duplicate_of INTEGER, notes TEXT);
CREATE INDEX IF NOT EXISTS ix_games_image ON games(image_id);
CREATE TABLE IF NOT EXISTS teams (
  team_id INTEGER PRIMARY KEY, game_id INTEGER REFERENCES games, side TEXT, label TEXT, sublabel TEXT, role TEXT,
  declared_size INTEGER, truncated INTEGER, tot_kills INTEGER, tot_deaths INTEGER, tot_dmg INTEGER, tot_heals INTEGER,
  tot_assists INTEGER, tot_caps INTEGER, checks_json TEXT);
CREATE TABLE IF NOT EXISTS player_games (
  pg_id INTEGER PRIMARY KEY, game_id INTEGER REFERENCES games, team_id INTEGER REFERENCES teams, handle TEXT,
  obscured INTEGER, kills INTEGER, deaths INTEGER, dmg INTEGER, heals INTEGER, assists INTEGER, caps INTEGER,
  pauses INTEGER, subgroup TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_pg_game ON player_games(game_id);
CREATE INDEX IF NOT EXISTS ix_pg_handle ON player_games(handle);
CREATE TABLE IF NOT EXISTS handle_resolutions (
  handle_key TEXT PRIMARY KEY, handle TEXT, status TEXT, canonical TEXT, candidates TEXT, via TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY, kind TEXT, created_at TEXT, script TEXT, git_rev TEXT, params_json TEXT, summary_json TEXT);
CREATE TABLE IF NOT EXISTS z_scores (
  run_id INTEGER REFERENCES runs, pg_id INTEGER REFERENCES player_games, game_id INTEGER, player_key TEXT, group_key TEXT,
  group_n INTEGER, z_kills REAL, z_dmg REAL, z_comp REAL, flag TEXT, lobby_z REAL, PRIMARY KEY (run_id, pg_id));
CREATE TABLE IF NOT EXISTS ratings (
  run_id INTEGER REFERENCES runs, player_key TEXT, canonical TEXT, resolution TEXT, n_games INTEGER, n_maps INTEGER,
  first_date TEXT, last_date TEXT, z_mean REAL, z_sd REAL, z_shrunk REAL, zk_mean REAL, zd_mean REAL, ovr REAL,
  ovr_raw REAL, ovr_sigma REAL, n_warehouse INTEGER, z_warehouse REAL, n_docks INTEGER, z_docks REAL, n_ordana INTEGER,
  z_ordana REAL, ovr_warehouse REAL, ovr_docks REAL, ovr_ordana REAL, z_sos REAL, ovr_unadj REAL, zs_warehouse REAL, zs_docks REAL,
  zs_ordana REAL, PRIMARY KEY (run_id, player_key));
"""


MIGRATIONS = [('ratings', 'ovr_warehouse', 'REAL'), ('ratings', 'ovr_docks', 'REAL'), ('ratings', 'ovr_ordana', 'REAL'),
              ('z_scores', 'lobby_z', 'REAL'), ('ratings', 'z_sos', 'REAL'), ('ratings', 'ovr_unadj', 'REAL'),
              ('ratings', 'zs_warehouse', 'REAL'), ('ratings', 'zs_docks', 'REAL'), ('ratings', 'zs_ordana', 'REAL'),
              # 2026-10-23: second image source (RoA / Skydock) and a points column
              ('player_games', 'points', 'INTEGER'), ('teams', 'tot_points', 'INTEGER'), ('images', 'base_dir', 'TEXT'), ('images', 'provenance', 'TEXT'),
              ('ratings', 'n_skydock', 'INTEGER'), ('ratings', 'z_skydock', 'REAL'), ('ratings', 'ovr_skydock', 'REAL'), ('ratings', 'zs_skydock', 'REAL'),
              ('z_scores', 'discard_gap', 'REAL'),
              ('sources', 'result_selected', 'INTEGER')]   # 2026-10-24: late-join suspects keep their pass-1 point and the gap that discarded them


def connect():
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:           # idempotent column additions for databases created before the column existed
        if col not in [r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
    return con


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def git_rev():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ''


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def upsert_source(con, name, kind, path, notes=''):
    sha = sha256_file(path) if path and os.path.exists(path) else None
    con.execute('INSERT INTO sources(name,kind,path,sha256,imported_at,notes) VALUES(?,?,?,?,?,?) '
                'ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256, imported_at=excluded.imported_at, path=excluded.path',
                (name, kind, os.path.relpath(path, ROOT).replace('\\', '/') if path else None, sha, now(), notes))
    return con.execute('SELECT source_id FROM sources WHERE name=?', (name,)).fetchone()[0]


def start_run(con, kind, script, params, summary=None):
    cur = con.execute('INSERT INTO runs(kind,created_at,script,git_rev,params_json,summary_json) VALUES(?,?,?,?,?,?)',
                      (kind, now(), script, git_rev(), json.dumps(params, sort_keys=True), json.dumps(summary) if summary else None))
    return cur.lastrowid


def finish_run(con, run_id, summary):
    con.execute('UPDATE runs SET summary_json=? WHERE run_id=?', (json.dumps(summary, sort_keys=True), run_id))


def fingerprint(map_name, handles, totals):
    """Same game captured twice: same handle set (case-insensitive) and same team totals."""
    key = (map_name or '') + '|' + ','.join(sorted(h.lower() for h in handles if h and not h.startswith('('))) + '|' + ','.join(str(t) for t in totals)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- imports
def import_manifest(con):
    src = upsert_source(con, 'vak_audit_log', 'audit_csv',
                        os.path.join(ROOT, 'sources', '[VOC] Personnel and Data Center - AUDIT LOG.csv'),
                        'VAKTOVIAN OPERATIONS COMMAND sector audit log; screenshots salvaged by sources/fetch_vak_screenshots.py')
    rows = list(csv.DictReader(open(MANIFEST, newline='', encoding='utf-8')))
    n_img = 0
    for r in rows:
        if r['status'] not in ('ok', 'ok_dup'):
            continue
        if r['status'] == 'ok':
            con.execute('''INSERT OR IGNORE INTO images(source_id,file,sha256,width,height,bytes,audit_date,audit_map,audit_type,
                audit_clan,audit_leader,audit_result,audit_challenge,audit_auditor,audit_line,url,image_url)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (src, r['file'], r['sha256'], int(r['width']), int(r['height']), int(r['bytes']), r['date'], r['map'],
                         r['type'], r['clan'].strip(), r['leader'], r['result'], r['challenge'], r['auditor'], int(r['line']),
                         r['url'], r['image_url']))
            n_img += 1
        img = con.execute('SELECT image_id FROM images WHERE file=?', (r['file'],)).fetchone()
        con.execute('''INSERT OR REPLACE INTO image_audit_rows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (img[0], int(r['line']), int(r['link_no']), r['date'], r['map'], r['type'], r['clan'].strip(), r['leader'],
                     r['result'], r['challenge'], r['auditor'], r['url'], r['status']))
    con.commit()
    print(f'images: {con.execute("SELECT count(*) FROM images").fetchone()[0]} (inserted {n_img}); audit rows: '
          f'{con.execute("SELECT count(*) FROM image_audit_rows").fetchone()[0]}')


def import_images(con, source_name, kind, src_path, notes, base_dir, rows):
    """rows: dicts with file (relative to base_dir), sha256, width, height, bytes, date, map, type, clan, leader, result,
    ref, link_no, url, image_url, status, provenance. Images are deduplicated on sha256 across all sources (the first
    source to import a picture keeps it; later refs point at the existing image)."""
    src = upsert_source(con, source_name, kind, src_path, notes)
    n_img = n_ref = 0
    for r in rows:
        img = None
        if r['status'] == 'ok':
            img = con.execute('SELECT image_id FROM images WHERE sha256=?', (r['sha256'],)).fetchone()
            if not img:
                con.execute("""INSERT INTO images(source_id,file,sha256,width,height,bytes,audit_date,audit_map,audit_type,audit_clan,
                               audit_leader,audit_result,audit_challenge,audit_auditor,audit_line,url,image_url,base_dir,provenance)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (src, r['file'], r['sha256'], int(r['width']), int(r['height']), int(r['bytes']), r['date'], r['map'], r['type'],
                             r['clan'], r['leader'], r['result'], '', '', int(re.sub(r'\D', '', str(r['ref'])) or 0), r['url'], r['image_url'],
                             base_dir, r.get('provenance', '')))
                n_img += 1
                img = con.execute('SELECT image_id FROM images WHERE sha256=?', (r['sha256'],)).fetchone()
        con.execute('INSERT OR REPLACE INTO image_refs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (src, str(r['ref']), int(r['link_no']), r['date'], r['map'], r['type'], r['clan'], r['leader'], r['result'], r['url'],
                     r['status'], img[0] if img else None, r.get('provenance', '')))
        n_ref += 1
    con.commit()
    print(f'{source_name}: {n_ref} refs, {n_img} new images (total images {con.execute("SELECT count(*) FROM images").fetchone()[0]})')


def import_roa_manifest(con):
    """sources/roa_screenshots/manifest.csv (RoA AMCOM registry, fetched by sources/fetch_roa_screenshots.py)."""
    man = os.path.join(ROOT, 'sources', 'roa_screenshots', 'manifest.csv')
    rows = []
    for r in csv.DictReader(open(man, newline='', encoding='utf-8')):
        rows.append(dict(file=r['file'], sha256=r['sha256'], width=r['width'] or 0, height=r['height'] or 0, bytes=r['bytes'] or 0,
                         date=r['date'], map=r['map'], type=r['type'], clan=r['clan'], leader=r['leader'], result=r['result'],
                         ref=r['line'], link_no=r['link_no'], url=r['url'], image_url=r['image_url'], status=r['status'],
                         provenance=f"host={r['leader']}; attendees={r['attendees']}; allied={r['allied']}; registry_winner={r['registry_winner']}"))
    import_images(con, 'roa_registry', 'registry_csv', os.path.join(ROOT, 'sources', 'RoA AMCOM Registry - Events.csv'),
                  'RoA AMCOM Registry - Events (Google Form log); screenshots salvaged by sources/fetch_roa_screenshots.py',
                  'sources/roa_screenshots', rows)


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def import_discord_manifest(con):
    """python -I raid_db.py import-discord-manifest --source NAME --manifest DIR/manifest.csv --channel ID [--map MAP | --map-json FILE] [--own CLAN]
    Imports images downloaded from a Discord channel by sources/discord_fetch.py (download). The post text supplies the
    opponent and event type; the map is fixed (--map) or per message (--map-json {message_id: map}); messages absent from
    the map json are skipped. Posts in a victories channel are wins for the posting clan (--own names it)."""
    name, man, chan = _arg('--source'), _arg('--manifest'), _arg('--channel')
    fixed_map = _arg('--map'); map_json = json.load(open(_arg('--map-json'))) if _arg('--map-json') else None
    own = _arg('--own', '')
    base_dir = os.path.relpath(os.path.dirname(os.path.abspath(man)), ROOT).replace('\\', '/')
    rows = []
    for r in csv.DictReader(open(man, newline='', encoding='utf-8')):
        mp = fixed_map or (map_json or {}).get(r['message_id'])
        if not mp:
            continue
        text = r['content'] or ''
        m = re.search(r'(?:\bv\.?|\bvs\.?)\s+(.+?)\s*(?:@|\(|\||$)', text, re.I)
        m2 = re.search(r'^\W*(?:<:\w+:\d+>)?\W*\**([^@|*]+?)\**\s*@\s*\**([^@|*(]+?)\**\s*(?:\(|\||$)', text)
        if m:
            opp = m.group(1).strip()
            typ = 'Scrimmage' if re.search(r'scrim', text, re.I) else 'Raid' if re.search(r'\braid\b', text, re.I) else 'Defense'
        elif m2:
            a, b = m2.group(1).strip(), m2.group(2).strip()
            we_attack = bool(own) and own.lower() in a.lower()
            opp, typ = (b if we_attack else a), ('Raid' if we_attack else 'Defense')
        else:
            opp, typ = '', ''
        rows.append(dict(file=r['file'], sha256=r['sha256'], width=r['width'] or 0, height=r['height'] or 0, bytes=r['bytes'] or 0,
                         date=(r['timestamp'] or '')[:10], map=mp, type=typ, clan=opp, leader=r['author'] or '', result='Win',
                         ref=r['message_id'], link_no=1, url=f"https://discord.com/channels/@me/{chan}/{r['message_id']}",
                         image_url=r['url'], status=r['status'], provenance=f"post={text[:200]}"))
    import_images(con, name, 'discord_channel', man, f'Discord channel {chan}; exported/downloaded by sources/discord_fetch.py', base_dir, rows)


def import_repo(con):
    """The repo's hand-verified games (RaidStats.csv + Games.csv) as their own source, so z/OVR runs see every game."""
    src = upsert_source(con, 'repo_raidstats', 'repo_csv', os.path.join(ROOT, 'RaidStats.csv'),
                        'RaidStats.csv rows transcribed + checksum-verified by a_cemaster via the raid-ingest skill; provenance in Games.csv')
    meta = {g['GameId']: g for g in csv.DictReader(open(os.path.join(ROOT, 'Games.csv'), newline='', encoding='utf-8-sig'))}
    by_game = collections.OrderedDict()
    for r in csv.DictReader(open(os.path.join(ROOT, 'RaidStats.csv'), newline='', encoding='utf-8-sig')):
        if r['Map']:
            by_game.setdefault(r['Map'], []).append(r)
    retire_runs(con, src)
    con.execute('DELETE FROM player_games WHERE game_id IN (SELECT game_id FROM games WHERE source_id=?)', (src,))
    con.execute('DELETE FROM teams WHERE game_id IN (SELECT game_id FROM games WHERE source_id=?)', (src,))
    con.execute('DELETE FROM games WHERE source_id=?', (src,))
    for gid, rows in by_game.items():
        m = meta.get(gid, {})
        teams = list(collections.OrderedDict((r['Team'], None) for r in rows))
        handles = [r['Handle'] for r in rows]
        totals = []
        for t in teams:
            tr = [r for r in rows if r['Team'] == t]
            totals += [sum(int(r['Kills'] or 0) for r in tr), sum(int(r['DMG'] or 0) for r in tr)]
        fp = fingerprint(m.get('Map', ''), handles, totals)
        mode = rows[0]['Mode']
        asym = mode == 'RAID' or 'RAID' in teams
        cur = con.execute('''INSERT INTO games(source_id,ext_id,map,date,event_type,opp_clan,format,verified_status,fingerprint,notes)
                             VALUES(?,?,?,?,?,?,?,?,?,?)''',
                          (src, gid, m.get('Map') or None, m.get('Date'), m.get('Event'), None,
                           'repo:' + (mode or '') + (':asym' if asym else ''), 'verified', fp, m.get('Notes')))
        game_id = cur.lastrowid
        for i, t in enumerate(teams):
            tr = [r for r in rows if r['Team'] == t]
            tcur = con.execute('''INSERT INTO teams(game_id,side,label,role,declared_size,truncated,tot_kills,tot_dmg,tot_heals,tot_caps)
                                  VALUES(?,?,?,?,?,?,?,?,?,?)''',
                               (game_id, 'left' if i == 0 else 'right', t, 'attacker' if t == 'RAID' else ('defender' if asym else 'neutral'),
                                len(tr), 0, sum(int(r['Kills'] or 0) for r in tr), sum(int(r['DMG'] or 0) for r in tr),
                                sum(int(r['Heals'] or 0) for r in tr), sum(int(r['Caps'] or 0) for r in tr)))
            for r in tr:
                con.execute('''INSERT INTO player_games(game_id,team_id,handle,obscured,kills,deaths,dmg,heals,caps,note)
                               VALUES(?,?,?,?,?,?,?,?,?,?)''',
                            (game_id, tcur.lastrowid, r['Handle'], 1 if r['Handle'].startswith('(') else 0,
                             int(r['Kills']) if r['Kills'] else None, int(r['Deaths']) if r['Deaths'] else None,
                             int(r['DMG']) if r['DMG'] else None, int(r['Heals']) if r['Heals'] else None,
                             int(r['Caps']) if r['Caps'] else None, 'canonical=' + r['Canonical'] if r['Canonical'] else None))
    con.commit()
    print(f'repo games imported: {len(by_game)}')


# ---------------------------------------------------------------- transcription -> games
STATUS_RANK = {'verified': 4, 'consensus': 3, 'kd_verified': 3, 'partial': 2, 'unchecked': 1, 'failed': 0}


def best_transcription(con, image_id):
    rows = con.execute('SELECT * FROM transcriptions WHERE image_id=? AND raw_json IS NOT NULL', (image_id,)).fetchall()
    rows = [r for r in rows if r['status'] in STATUS_RANK]
    if not rows:
        return None
    return max(rows, key=lambda r: (STATUS_RANK[r['status']], r['transcription_id']))


def retire_runs(con, source_id):
    """A rebuild replaces game/player rows, so every scoring run that referenced them is retired: its z_scores and ratings
    are dropped and the run row keeps a note. Re-run raid_score.py to get fresh, traceable numbers."""
    runs = [r[0] for r in con.execute('SELECT DISTINCT run_id FROM z_scores WHERE game_id IN (SELECT game_id FROM games WHERE source_id=?)', (source_id,)).fetchall()]
    for rid in runs:
        con.execute('DELETE FROM z_scores WHERE run_id=?', (rid,)); con.execute('DELETE FROM ratings WHERE run_id=?', (rid,))
        row = con.execute('SELECT summary_json FROM runs WHERE run_id=?', (rid,)).fetchone()
        summ = json.loads(row[0]) if row and row[0] else {}
        summ['retired'] = f'games rebuilt at {now()}; z_scores/ratings dropped'
        con.execute('UPDATE runs SET summary_json=? WHERE run_id=?', (json.dumps(summ, sort_keys=True), rid))
    if runs:
        print(f'retired scoring runs {runs} (their games were rebuilt)')


def clean_clan(text):
    """The audit log's clan cell sometimes carries the auditor's evidence link, Discord bold markers or a trailing note
    ("UoA https://... Co-lead by X"). Keep the clan name: the text before the first link, or after it when nothing precedes it."""
    if not text:
        return text
    s = str(text).replace('**', '').replace('`', '')
    parts = re.split(r'https?://[^ ]+', s)
    head = parts[0].strip()
    s = head if head else ' '.join(parts[1:]).strip()
    s = ' '.join(s.split()).strip(' -:,;|')
    return s or None


RESULT_SELECTED_SOURCES = {'roa_confirmed_victories', 'sol_victories'}   # Discord victory channels: every post is a win


def result_selected(con):
    """Source ids whose games were selected on the result. A win-only sample says nothing about win probability (the
    outcome fits skip it) and lifts the posting clan's whole side within the lobby (scoring uses only the within-team
    ranking from it). The flag is written to sources.result_selected so it is visible in the DB."""
    names = sorted(RESULT_SELECTED_SOURCES)
    con.execute('UPDATE sources SET result_selected=1 WHERE name IN (%s)' % ','.join('?' * len(names)), names)
    con.execute('UPDATE sources SET result_selected=0 WHERE result_selected IS NULL')
    return {r[0] for r in con.execute('SELECT source_id FROM sources WHERE result_selected=1').fetchall()}


def trusted_scores(map_name, sl, sr):
    """Docks' end screen animates the score counters, so a capture mid-animation prints arbitrary pairs (1799/1280,
    6964/5967). A Docks score pair is kept only when one side shows the 1800 cap; other maps keep what was printed."""
    if map_name == 'Docks' and sl is not None and sr is not None and max(sl, sr) != 1800:
        return None, None
    return sl, sr


CONTENT_DUP_MIN_ROWS = 5          # identical (handle, kills, dmg) rows shared by two boards: the same game captured twice


def mark_content_duplicates(con):
    """The fingerprint only catches an identical re-transcription. The same board posted to two channels (a Sol win that
    VAK also logged; an RoA registry entry and its confirmed-victory post; a second crop in one log) is transcribed from
    two screenshots and differs in a name, an obscured row or a truncated list, so it was counted twice (a_cemaster,
    2026-10-24: one event, one game). Two games dated within a day that share CONTENT_DUP_MIN_ROWS identical
    (handle, kills, dmg) rows, or at least 3 covering half of the smaller board, are one event. The copy kept comes from
    a two-sided source over a victory channel, then the more complete board, then the earlier capture."""
    selected = result_selected(con)
    games = con.execute('SELECT game_id, source_id, date, map FROM games WHERE duplicate_of IS NULL AND date IS NOT NULL ORDER BY date, game_id').fetchall()
    rows = collections.defaultdict(set)
    for r in con.execute('SELECT game_id, lower(handle) AS h, kills, dmg FROM player_games WHERE obscured=0 AND kills IS NOT NULL AND dmg IS NOT NULL'):
        rows[r['game_id']].add((r['h'], r['kills'], r['dmg']))

    def day(g):
        try:
            return datetime.date.fromisoformat(g['date'][:10])
        except (ValueError, TypeError):
            return None

    def rank(g):                                           # higher keeps: two-sided source, fuller board, earlier capture
        return (0 if g['source_id'] in selected else 1, len(rows[g['game_id']]), -g['game_id'])

    dropped = {}                                           # game_id -> surviving game_id
    shared_n = {}
    for i, a in enumerate(games):
        da = day(a)
        for b in games[i + 1:]:
            db = day(b)
            if da is None or db is None:
                continue
            if (db - da).days > 1:
                break
            if b['game_id'] in dropped:
                continue
            shared = len(rows[a['game_id']] & rows[b['game_id']])
            small = min(len(rows[a['game_id']]), len(rows[b['game_id']]))
            if shared < CONTENT_DUP_MIN_ROWS and not (shared >= 3 and shared * 2 >= small):
                continue
            if a['game_id'] in dropped:                    # a is already a copy: b joins the same survivor
                dropped[b['game_id']] = dropped[a['game_id']]; shared_n[b['game_id']] = shared
                continue
            keep, drop = (a, b) if rank(a) >= rank(b) else (b, a)
            dropped[drop['game_id']] = keep['game_id']; shared_n[drop['game_id']] = shared
    for gid, surv in dropped.items():
        con.execute("UPDATE games SET duplicate_of=?, notes=COALESCE(notes, '') || ? WHERE game_id=?",
                    (surv, ' | same board as game %d (%d identical rows): counted once' % (surv, shared_n[gid]), gid))
    return len(dropped)


def build_games(con):
    """Rebuild games/teams/player_games from the best transcription of every image, across all image sources."""
    srcs = [r[0] for r in con.execute("SELECT source_id FROM sources WHERE kind!='repo' AND source_id IN (SELECT DISTINCT source_id FROM images)").fetchall()]
    names = {r[0]: r[1] for r in con.execute('SELECT source_id, name FROM sources').fetchall()}
    for src in srcs:
        retire_runs(con, src)
        con.execute('DELETE FROM player_games WHERE game_id IN (SELECT game_id FROM games WHERE source_id=?)', (src,))
        con.execute('DELETE FROM teams WHERE game_id IN (SELECT game_id FROM games WHERE source_id=?)', (src,))
        con.execute('DELETE FROM games WHERE source_id=?', (src,))
    n = 0; recon = collections.Counter()
    for img in con.execute('SELECT * FROM images WHERE source_id IN (%s) ORDER BY audit_date, image_id' % ','.join('?' * len(srcs)), srcs).fetchall():
        src = img['source_id']
        t = best_transcription(con, img['image_id'])
        if not t:
            continue
        d = json.loads(t['raw_json'])
        if not d.get('board_present') or not d.get('teams'):
            continue
        # Inferred maps (Sol victories: map comes from the paired shout) are reconciled against the board itself:
        # an Ordana or Docks layout is unmistakable and wins; a RED/BLUE hardpoint board assigned to Ordana/Docks means
        # the pairing was wrong and the hardpoint map is unknown, so the game is left out.
        mp = img['audit_map']; fmt = d.get('format_family') or ''
        if names[src] in INFERRED_MAP_SOURCES:
            if fmt == 'ordana' and mp != 'Ordana':
                recon[f'{mp}->Ordana'] += 1; mp = 'Ordana'
            elif fmt.startswith('docks') and mp != 'Docks':
                recon[f'{mp}->Docks'] += 1; mp = 'Docks'
            elif fmt in ('hp_red_blue', 'hp_mvp') and mp not in ('Warehouse',):
                recon[f'{mp}->dropped (hardpoint board, map unknown)'] += 1; continue
            elif fmt == 'skydock' and mp != 'Skydock':
                recon[f'{mp}->Skydock'] += 1; mp = 'Skydock'
        handles = [p['handle'] for tm in d['teams'] for p in tm['players']]
        totals = []
        for tm in d['teams']:
            totals += [tm['totals'].get('kills'), tm['totals'].get('dmg')]
        fp = fingerprint(mp, handles, totals)
        dup = con.execute('SELECT game_id FROM games WHERE fingerprint=? AND duplicate_of IS NULL', (fp,)).fetchone()
        cur = con.execute('''INSERT INTO games(source_id,image_id,transcription_id,ext_id,map,date,event_type,opp_clan,format,banner,
                             score_left,score_right,match_time,verified_status,fingerprint,duplicate_of,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (src, img['image_id'], t['transcription_id'], (f"L{img['audit_line']}" if names[src] == 'vak_audit_log' else f"{names[src]}:{img['audit_line']}"), mp, img['audit_date'],
                           img['audit_type'], clean_clan(img['audit_clan']), d.get('format_family'), d.get('banner_text'), *trusted_scores(img['audit_map'], d.get('score_left'), d.get('score_right')),
                           d.get('match_time'), t['status'], fp, dup[0] if dup else None, d.get('notes')))
        game_id = cur.lastrowid
        checks = json.loads(t['checks_json'] or '{}')
        for i, tm in enumerate(d['teams']):
            tot = tm['totals']
            tcur = con.execute('''INSERT INTO teams(game_id,side,label,sublabel,role,declared_size,truncated,tot_kills,tot_deaths,tot_dmg,
                                  tot_heals,tot_assists,tot_caps,checks_json,tot_points) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (game_id, tm['side'], tm['label'], tm.get('sublabel'), tm.get('role'), tm.get('declared_size'),
                                1 if tm.get('list_truncated') else 0, tot.get('kills'), tot.get('deaths'), tot.get('dmg'), tot.get('heals'),
                                tot.get('assists'), tot.get('caps'), json.dumps(checks.get('teams', [{}] * 2)[i] if i < len(checks.get('teams', [])) else {}),
                                tot.get('points')))
            for p in tm['players']:
                con.execute('''INSERT INTO player_games(game_id,team_id,handle,obscured,kills,deaths,dmg,heals,assists,caps,pauses,subgroup,note,points)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (game_id, tcur.lastrowid, p['handle'], 1 if p.get('obscured') else 0, p.get('kills'), p.get('deaths'), p.get('dmg'),
                             p.get('heals'), p.get('assists'), p.get('caps'), p.get('pauses'), p.get('subgroup'), p.get('note'), p.get('points')))
        n += 1
    cdups = mark_content_duplicates(con)
    con.commit()
    dups = con.execute('SELECT count(*) FROM games WHERE duplicate_of IS NOT NULL').fetchone()[0]
    print(f'games built from transcriptions: {n} across {len(srcs)} sources (duplicates of an earlier capture: {dups}, of which {cdups} same boards from a second screenshot)')
    if recon:
        print('map reconciliation from board format:', dict(recon))


def status(con):
    for t in ('sources', 'images', 'image_audit_rows', 'transcriptions', 'games', 'teams', 'player_games', 'handle_resolutions', 'runs', 'z_scores', 'ratings'):
        print(f'{t:20} {con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]}')
    print('transcription status:', dict(con.execute('SELECT status, count(*) FROM transcriptions GROUP BY status').fetchall()))
    print('games by verified_status:', dict(con.execute('SELECT verified_status, count(*) FROM games GROUP BY verified_status').fetchall()))
    print('tokens / cost:', con.execute('SELECT sum(input_tokens), sum(output_tokens), round(sum(cost_usd),2) FROM transcriptions').fetchone()[:])


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    con = connect()
    con.executescript(SCHEMA)
    {'init': lambda c: print('schema ok'), 'import-manifest': import_manifest, 'import-repo': import_repo,
     'import-roa-manifest': import_roa_manifest, 'import-discord-manifest': import_discord_manifest,
     'build-games': build_games, 'status': status}[cmd](con)
