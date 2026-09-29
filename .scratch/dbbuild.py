"""Stage 1 of the TLBB resource index: build resources.db (SQLite).

Inputs (all read-only):
  D:\\TLGL\\data*.pak          -> index records, incl. payload offset
  .scratch/names_jrpc.tsv      -> hash -> recovered virtual path
  .scratch/out/all/<pak>/...   -> already-extracted payloads, used for magic sniffing

Schema
  resources(hash, path, dir, name, ext, type, subtype, codec, width, height, mips,
            ver, flags, method, stored, occupied, original, filecrc, pak, gen, offset,
            named, props)
  records(pak, gen, hash, offset, stored, occupied, original, ver, flags, method, filecrc)
  relations(from_hash, from_path, to_hash, to_path, rel)   -- filled by stage 2
  refs(from_hash, from_path, name, kind, to_hash, ambig)   -- JBCF string-table imports
  agroups/amembers/agroup_names/dangling                   -- stage 3 asset graph

Usage:  python dbbuild.py [--root DIR] [--db FILE] [--no-rescan] [--rels] [--assets]
"""
import argparse
import binascii
import collections
import json
import mmap
import os
import re
import sqlite3
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pakunpack2 as pu          # noqa: E402  REC / walk_generations / crc
import jhash                     # noqa: E402  canonical path hash
import jbcf                      # noqa: E402  sdecode + BinaryConfigFile reader
import jbpu                      # noqa: E402  particle-effect (.pu) reader

M = 0xFFFFFFFF
# 客户端根与库路径以前写死在本机（D:\TLGL + .scratch/resources.db），换一台机器
# 或客户端装在别处就跑不起来。现在与 Rust 侧同一套约定：TLBB_ROOT / TLBB_DB 环境变量，
# 或命令行 --root / --db；不给时沿用老默认值，本机习惯不变。
ROOT = os.environ.get('TLBB_ROOT') or r'D:\TLGL'
OUT_ALL = os.path.join(HERE, 'out', 'all')
DB = os.environ.get('TLBB_DB') or os.path.join(HERE, 'resources.db')
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']


# ---------------------------------------------------------------- index scan
def scan_index():
    """All live index records: [(pak_stem, gen, hash, off, size, occ, ofsz, ver, flags, meth, fcrc)]."""
    rows = []
    for p in PAKS:
        path = os.path.join(ROOT, p)
        if not os.path.isfile(path):
            continue
        stem = os.path.splitext(p)[0]
        with open(path, 'rb') as f:
            d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            for gi, (rp, n, _e) in enumerate(pu.walk_generations(d)):
                for i in range(n):
                    r = d[rp + i * 36:rp + i * 36 + 36]
                    h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = pu.REC.unpack(r)
                    if pu.crc(r[:32]) != ucrc:
                        continue          # unused slot / dead record
                    rows.append((stem, gi, h, off, size, occ, ofsz, ver, fl, me, fcrc))
            d.close()
    return rows


# ---------------------------------------------------------------- type sniff
COPY_TAG = re.compile(rb'[\x20-\x7e]{1,12}')


RUN = re.compile(rb'[\x20-\x7e]{5,}')


def classify(h, size):
    """(type, subtype, codec, w, hh, mips, props) from the first bytes of a payload."""
    props = {}
    if size == 0:
        return 'empty', None, None, None, None, None, props
    h = h[:96].ljust(96, b'\x00')
    a = struct.unpack_from('<6I', h, 0)
    m4 = h[:4]
    if m4 == b'JMT1':
        # [24B header][per mip: u32 size + data]* — the 4CC lies (BC3 ships tagged as
        # DXT1), so the pixel format is derived from the mip0 byte count.
        tag = h[4:8].decode('latin1', 'replace')
        w, hh = struct.unpack_from('<HH', h, 16)
        nmip, mip0 = a[5], struct.unpack_from('<I', h, 24)[0]
        b0 = ((w + 3) // 4) * ((hh + 3) // 4)
        # COLW/COLR are the two real variants: the engine (sub_1405D2160) feeds COLW
        # straight into a WebP demuxer and sizes COLR as padded (w+2)x(h+2) RGBA.
        fmt = ('WEBP' if tag == 'COLW' else
               'RGBA32P' if tag == 'COLR' and mip0 == (w + 2) * (hh + 2) * 4 else
               'RGBA32' if mip0 == w * hh * 4 else 'BC3' if mip0 == b0 * 16 else
               'BC1' if mip0 == b0 * 8 else 'unknown')
        return 'texture', 'JMT1', fmt, w, hh, nmip, \
            {'declared_codec': tag, 'marker': a[2], 'payload': a[3], 'mip0': mip0}
    if h[:10] == b'Copyright ':
        # julegame asset banner: (c) text, type tag at +64, u32 version at +72, 4CC kind
        # at +76; animation sets carry "julekeji" instead of a type tag.
        banner = h[:80].split(b'\x00')[0].decode('latin1', 'replace')
        tag = h[64:72].split(b'\x00')[0].decode('latin1', 'replace').strip()
        kind = h[76:84].split(b'\x00')[0].decode('latin1', 'replace').strip()
        embedded = [r.decode('latin1') for r in RUN.findall(h[8:64])
                    if r.decode('latin1').lower() not in banner.lower()]
        t = tag or ('set' if kind == 'julekeji' else 'copy')
        return t, 'copy', kind or None, None, None, None, \
            {'ver': struct.unpack_from('<I', h, 72)[0], 'embedded': embedded[:1],
             'banner': banner[:72]}
    if m4 in (b'JBCF', b'JBPU', b'NAVF', b'GATA', b'JLUA', b'JMDL', b'JPKF', b'JSTR'):
        t = m4.decode('latin1')
        if t == 'GATA':
            e = h.find(b'\x00', 8)
            ref = jbcf.sdecode(h[8:e]) if 8 < e < 200 else ''
            return t, 'gata', None, None, None, None, {'ref': ref}
        return t, t, None, None, None, None, {'f4': a[1], 'f8': a[2], 'f12': a[3]}
    for magic, name in ((b'\x89PNG\r\n\x1a\n', 'png'), (b'RIFF', 'wav'), (b'OggS', 'ogg'),
                        (b'\xff\xd8\xff', 'jpeg'), (b'GIF8', 'gif'), (b'BM', 'bmp'),
                        (b'\x00\x00\x00\x18ftyp', 'mp4'), (b'ID3', 'mp3'), (b'MZ\x90\x00', 'pe'),
                        (b'\x1a\x45\xdf\xa3', 'mkv')):
        if h.startswith(magic):
            if name == 'RIFF' or magic == b'RIFF':
                name = 'webp' if h[8:12] == b'WEBP' else 'wav'
            if name == 'png':
                w, hh = struct.unpack('>II', h[16:24])
                return name, 'png', None, w, hh, None, {}
            return name, name, None, None, None, None, {}
    if h[:4] in (b'\x00\x01\x00\x00', b'OTTO', b'true', b'ttcf') and a[1] in (0x00010000, 0x4F54544F):
        return 'font', 'ttf', None, None, None, None, {'num': a[2]}
    if a[1] == 753:                        # scene grid: u32 chunk count, u32 753
        return 'scene', 'grid753', None, None, None, None, {'count': a[0]}
    if a[1] == 280:                        # map reference table: u32 count, u32 280
        return 'mapref', 'tab280', None, None, None, None, {'count': a[0]}
    if a[1] == 237:
        return 'table', 'tab237', None, None, None, None, {'count': a[0]}
    if a[0] == 0 and a[1] in (1, 2, 3, 4) and a[2]:
        return 'geom', 'raw', None, None, None, None, {'f': list(a[:4])}
    if a[0] and a[1] == 0 and a[2] == 0 and a[3] == 0:
        return 'table', 'u32head', None, None, None, None, {'count': a[0]}
    if h[:1] == b'<' and b'>' in h[:96]:
        return 'xml', 'xml', None, None, None, None, {}
    printable = sum(1 for b in h[:64] if b in (9, 10, 13) or 32 <= b < 127)
    if printable >= 60:
        return 'text', 'text', None, None, None, None, {'head': jbcf.sdecode(h[:48])}
    if size <= 8:
        return 'tiny', 'bin', None, None, None, None, {'f': list(a[:4])}
    return 'binary', 'bin', None, None, None, None, {'f': list(a[:4])}


# ---------------------------------------------------------------- name map
def load_tsv(fn):
    p = os.path.join(HERE, fn)
    if not os.path.isfile(p):
        return {}
    out = {}
    for l in open(p, encoding='utf-8').readlines()[1:]:
        a = l.rstrip('\n').split('\t')
        if len(a) >= 2 and a[1]:
            out[a[0]] = a[1]
    return out


def load_names():
    names = {}
    for l in open(os.path.join(HERE, 'names_jrpc.tsv'), encoding='utf-8').readlines()[1:]:
        a = l.rstrip('\n').split('\t')
        if len(a) >= 2 and a[1]:
            names[int(a[0], 16)] = a[1]
    return names


def name_sources():
    """hash -> provenance of the recovered name, strongest signal wins.

    manifest  -- the .pak record itself carried the path (updater loose files)
    self      -- the payload opens with its own virtual path; re-hashing proves it
    resourcepath -- listed in the engine's ResourcePath.cfg (JRPC) table
    mined     -- recovered by dictionary/token mining
    """
    src = {}
    self_path = load_tsv('names_self.tsv')
    for h in load_tsv('names.tsv'):
        src[h] = 'manifest'
    for h in self_path:
        src[h] = 'self'
    for h in load_tsv('names_jrpc.tsv'):
        src.setdefault(h, 'resourcepath')
    for f in ('names_round.tsv', 'names_new.tsv'):
        for h in load_tsv(f):
            src.setdefault(h, 'mined')
    return src, self_path


def payload_heads():
    """{(pak_stem, hash) -> (first 96 bytes, file size)} for everything already extracted."""
    idx = {}
    for pak in os.listdir(OUT_ALL):
        d = os.path.join(OUT_ALL, pak)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.isdir(p) or len(fn) < 16:
                continue
            try:
                h = int(fn[:16], 16)
            except ValueError:
                continue
            with open(p, 'rb') as f:
                idx[(pak, h)] = (f.read(96), os.path.getsize(p))
    return idx


# ---------------------------------------------------------------- build
def build(rescan=True):
    rows = scan_index() if rescan else None
    if rows is None:
        rows = []
        for l in open(os.path.join(HERE, 'index_off.tsv'), encoding='utf-8'):
            a = l.rstrip('\n').split('\t')
            rows.append((a[0], int(a[1]), int(a[2])) + tuple(int(x) for x in a[3:]))
    else:
        with open(os.path.join(HERE, 'index_off.tsv'), 'w', encoding='utf-8') as o:
            for r in rows:
                o.write('\t'.join(str(x) for x in r) + '\n')

    names = load_names()
    src, self_path = name_sources()
    # last writer wins: index by (pak,hash) for records, and pick a home record per hash
    best = {}
    for r in rows:
        pak, gi, h = r[0], r[1], r[2]
        cur = best.get(h)
        if cur is None or (gi, r[4]) > (cur[1], cur[4]):
            best[h] = r
    print('records %d   unique hashes %d   named %d' % (len(rows), len(best), len(names)))

    con = sqlite3.connect(DB)
    con.execute('PRAGMA busy_timeout=180000')
    c = con.cursor()
    c.executescript('''
      DROP TABLE IF EXISTS resources;
      DROP TABLE IF EXISTS records;
      DROP TABLE IF EXISTS relations;
      DROP TABLE IF EXISTS assets;
      DROP TABLE IF EXISTS meta;
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE resources(
        hash TEXT PRIMARY KEY, path TEXT, dir TEXT, name TEXT, ext TEXT,
        type TEXT, subtype TEXT, codec TEXT, width INT, height INT, mips INT,
        ver INT, flags INT, method INT, stored INT, occupied INT, original INT,
        filecrc INT, pak TEXT, gen INT, offset INT, named INT, props TEXT,
        src TEXT, self_path TEXT);
      CREATE TABLE records(
        pak TEXT, gen INT, hash TEXT, offset INT, stored INT, occupied INT,
        original INT, ver INT, flags INT, method INT, filecrc INT,
        PRIMARY KEY(pak, hash));
      CREATE TABLE relations(
        from_hash TEXT, from_path TEXT, to_hash TEXT, to_path TEXT, rel TEXT,
        PRIMARY KEY(from_hash, to_hash, rel));
      CREATE TABLE assets(grp TEXT, primary_hash TEXT, kind TEXT);
      CREATE INDEX ix_res_path ON resources(path);
      CREATE INDEX ix_res_type ON resources(type);
      CREATE INDEX ix_res_dir  ON resources(dir);
      CREATE INDEX ix_res_ext  ON resources(ext);
      /* `textures_in_dir` runs 12,159 times during a workbench cold start, asking for
         `dir = ? AND type = 'texture' ORDER BY original DESC LIMIT 8`. With only
         `ix_res_dir(dir)` SQLite must fetch every row of the directory and sort it in a
         temp B-tree. This covering index answers the whole query inside the index:
         measured on the shipped catalog, 12,159 calls go 8.98s -> 0.32s (28x) and the
         `USE TEMP B-TREE FOR ORDER BY` disappears from the plan. */
      CREATE INDEX ix_res_dir_type_original ON resources(dir, type, original DESC);
      CREATE INDEX ix_rel_from ON relations(from_hash);
      CREATE INDEX ix_rel_to   ON relations(to_hash);
    ''')

    rec_rows = [('%s' % r[0], r[1], '%016x' % r[2], r[3], r[4], r[5], r[6], r[7],
                 r[8], r[9], r[10]) for r in rows]
    c.executemany('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?)', rec_rows)

    res = []
    census = {}
    bad = []
    heads = payload_heads()
    print('payload files indexed: %d' % len(heads))
    for h, r in sorted(best.items()):
        pak, gi, _, off, size, occ, ofsz, ver, fl, me, fcrc = r
        head, real = heads.get((pak, h), (None, None))
        if head is None and names.get(h):
            # updater loose files were written under out/loose/<real path>, not by hash
            lp = os.path.join(HERE, 'out', 'loose', names[h].replace('/', os.sep))
            if os.path.isfile(lp):
                with open(lp, 'rb') as f:
                    head, real = f.read(96), os.path.getsize(lp)
        if head is None:
            t, sub, codec, w, hh, mips, props = ('missing', None, None, None, None, None, {})
        else:
            t, sub, codec, w, hh, mips, props = classify(head, real)
        census[t] = census.get(t, 0) + 1
        if t in ('binary', 'missing') and len(bad) < 400000:
            bad.append((t, pak, '%016x' % h, (head or b'')[:8].hex(), real))
        hexh = '%016x' % h
        p = names.get(h)
        if p:
            d, fn = p.rsplit('/', 1) if '/' in p else ('', p)
            ext = os.path.splitext(fn)[1].lower()
        else:
            d = fn = ext = ''
        res.append((hexh, p, d, fn, ext, t, sub, codec, w, hh, mips, ver, fl, me,
                    size, occ, ofsz, fcrc, pak, gi, off, 1 if p else 0,
                    json.dumps(props, ensure_ascii=False) if props else None,
                    src.get(hexh, ''), self_path.get(hexh, '')))
    c.executemany('INSERT OR REPLACE INTO resources VALUES(%s)' % ','.join('?' * 25), res)
    with open(os.path.join(HERE, 'unclassified.txt'), 'w', encoding='utf-8') as o:
        for t, pak, hs, hx, sz in bad:
            o.write('%s\t%s\t%s\t%s\t%s\n' % (t, pak, hs, hx, sz))
    c.executemany('INSERT OR REPLACE INTO assets VALUES(?,?,?)', [])
    for k, v in sorted(census.items(), key=lambda x: -x[1]):
        c.execute('INSERT INTO meta VALUES(?,?)', ('type:' + k, v))
    c.execute('INSERT INTO meta VALUES(?,?)', ('records', len(rows)))
    c.execute('INSERT INTO meta VALUES(?,?)', ('resources', len(best)))
    c.execute('INSERT INTO meta VALUES(?,?)', ('named', len(names)))
    con.commit()
    print('type census:')
    for k, v in sorted(census.items(), key=lambda x: -x[1])[:20]:
        print('   %-14s %7d' % (k, v))
    return con, best, names


# ---------------------------------------------------------------- stage 2
SUBDIRS = {'ani', 'mesh', 'mtl', 'ske', 'texture', 'textures', 'tex', 'model', 'models',
           'tdw', 'sound', 'icon', 'src'}

# ---------------------------------------------------------------- stage 3
SHARED_DEG = 8          # targets above this inbound degree are cut from grouping
ROLE = {'.mdl': 'model', '.ske': 'skeleton', '.mesh': 'mesh', '.geom': 'mesh',
        '.mtl': 'material', '.ani': 'animation', '.anis': 'animation', '.pu': 'effect',
        '.scene': 'scene', '.set': 'set', '.wav': 'audio', '.ogg': 'audio', '.mp3': 'audio',
        '.map': 'map', '.tab': 'table', '.xml': 'table', '.cfg': 'config'}
DIR_KINDS = (('data/source/player', 'player'), ('data/source/npc', 'npc'),
         ('data/source/monster', 'monster'), ('data/source/pet', 'pet'),
         ('data/source/weapon', 'weapon'), ('data/source', 'source'),
         ('data/effect', 'effect'), ('data/sharematerial', 'shared-material'),
         ('data/scene', 'scene'), ('data/tani', 'tani'), ('mobile_maps', 'map-prop'),
         ('ui/', 'ui'), ('data/', 'data'))


def kind_of(d):
    dl = (d or '').lower()
    for pre, k in DIR_KINDS:
        if dl.startswith(pre):
            return k
    return 'other'


def build_relations(con):
    """Three evidence-based edge families:
       ref       -- container embeds another asset's virtual path (GATA, Copyright banner)
       same-stem -- same directory + same file stem, different extension (mesh/ske/ani/mtl/...)
       model-dir -- file sits in a directory named after a model hub asset
    """
    import json
    c = con.cursor()
    paths = dict(c.execute('SELECT hash, path FROM resources WHERE path IS NOT NULL'))
    known = {int(h, 16) for h in paths}
    by_hash = {h: int(h, 16) for h in paths}
    n = 0
    sel = list(c.execute("SELECT hash, props FROM resources WHERE props LIKE '%ref%' OR "
                         "props LIKE '%embedded%'"))
    for h, props in sel:
        d = json.loads(props or '{}')
        p = paths.get(h) or ''
        base = p.rsplit('/', 1)[0] if '/' in p else ''
        for cand in filter(None, [d.get('ref')] + (d.get('embedded') or [])):
            cand = cand.replace('\\', '/').lstrip('/')
            trials = [cand] if '/' in cand else ([base + '/' + cand] if base else []) + [cand]
            for t in trials:
                k = jhash.path_hash(t)
                if k in known:
                    kh = '%016x' % k
                    if kh != h:
                        c.execute('INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?)',
                                  (h, p, kh, paths.get(kh), 'ref'))
                        n += 1
                    break
    con.commit()
    print('ref edges: %d' % n)

    groups = {}
    for h, p in paths.items():
        d, fn = p.rsplit('/', 1) if '/' in p else ('', p)
        stem = os.path.splitext(fn)[0]
        g = d.rsplit('/', 1)[0] if (d.rsplit('/', 1)[-1] if '/' in d else d).lower() in SUBDIRS \
            else d
        groups.setdefault(g.lower(), []).append((h, stem.lower(), os.path.splitext(fn)[1].lower()))

    rows = []
    for g, files in groups.items():
        if len(files) < 2:
            continue
        bystem = {}
        for h, stem, ext in files:
            bystem.setdefault(stem, []).append(h)
        for stem, hs in bystem.items():
            for a in hs[1:]:
                rows.append((hs[0], paths[hs[0]], a, paths[a], 'same-stem'))
            if len(hs) > 1:
                c.execute('INSERT INTO assets(grp, primary_hash, kind) VALUES(?,?,?)',
                          (g, hs[0], 'stem'))
        # hub of the group: the file whose stem equals the group's last component
        leaf = g.rsplit('/', 1)[-1]
        hub = [h for h, stem, ext in files if stem == leaf.lower()]
        if hub:
            for h, stem, ext in files:
                if h != hub[0]:
                    rows.append((hub[0], paths[hub[0]], h, paths[h], 'model-part'))
            c.execute('INSERT INTO assets(grp, primary_hash, kind) VALUES(?,?,?)',
                      (g, hub[0], 'model'))
    c.executemany('INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?)', rows)
    con.commit()
    print('sibling/model edges: %d' % len(rows)
                )
    add_content_refs(con)


def add_content_refs(con):
    """BinaryConfigFile (JBCF) string tables -> content-derived dependencies.

    Materials, skeletons and model hubs list their imports by name in a real string
    table, so these edges come from the file contents rather than from a filename
    guess.  Unresolved names are kept in `refs` with a null target: the texture files
    simply carry no names in this install, and the reference itself is the finding.
    """
    files = {}
    for pak in os.listdir(OUT_ALL):
        d = os.path.join(OUT_ALL, pak)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if len(fn) >= 16:
                files[fn[:16]] = os.path.join(d, fn)
    paths = dict(con.execute('select hash, path from resources where path is not null'))
    bybase, bydir = {}, {}
    for h, p in paths.items():
        b = os.path.basename(p).lower()
        bybase.setdefault(b, set()).add(h)
        bydir.setdefault(os.path.dirname(p.lower()), {})[b] = h

    c = con.cursor()
    c.executescript('''
      DROP TABLE IF EXISTS refs;
      CREATE TABLE refs(from_hash TEXT, from_path TEXT, name TEXT, kind TEXT,
                        to_hash TEXT, ambig INT DEFAULT 0, PRIMARY KEY(from_hash, name));
      CREATE INDEX ix_refs_to ON refs(to_hash);
      CREATE INDEX ix_refs_kind ON refs(kind);
    ''')
    KINDS = {'.mtl': 'use-mtl', '.ske': 'use-ske', '.mesh': 'use-mesh', '.ani': 'use-ani',
             '.anis': 'use-ani', '.tga': 'use-tex', '.dds': 'use-tex', '.png': 'use-tex',
             '.pu': 'use-pu', '.scene': 'use-scene'}
    rrows, urows, stats, propupd = [], [], collections.Counter(), []
    known = {int(x, 16) for x in paths}
    for h, t in c.execute("select hash, type from resources where type in ('JBCF','JBPU')")\
            .fetchall():
        f = files.get(h)
        if not f:
            continue
        fx = None
        try:
            raw = open(f, 'rb').read()
            if t == 'JBCF':
                _, _, _, strs = jbcf.parse(raw)
            else:
                names_, blob = jbpu.parse(raw)
                strs = [(x, 0) for x in names_]
                fx = jbpu.classify(names_)
                fx['param_bytes'] = len(blob)
        except ValueError:
            continue
        p = paths.get(h) or ''
        ddir = os.path.dirname(p.lower())
        names, shader = [], None
        for s, _ in strs:
            if not s:
                continue
            names.append(s)
            if 'shader' in s.lower():
                shader = s
            low = s.lower()
            e = os.path.splitext(low)[1]
            rel = KINDS.get(e)
            if not rel:
                continue
            stats['ref:' + e] += 1
            base = os.path.basename(low)
            tgt = bydir.get(ddir, {}).get(base)
            if tgt is None and '/' in low:
                k = jhash.path_hash(s.lstrip('/'))
                if k in known:
                    tgt = '%016x' % k
            amb = 0
            if tgt is None:
                cand = bybase.get(base)
                if cand and len(cand) == 1:
                    tgt = next(iter(cand))
                elif cand:
                    tgt, amb = min(cand), 1
            if tgt and tgt != h:
                rrows.append((h, p, tgt, paths.get(tgt), rel))
                stats['edge:' + e] += 1 if tgt in paths else 0
            elif not tgt:
                stats['dangling:' + e] += 1
            urows.append((h, p, s, e, tgt, amb))
        if fx:
            propupd.append((json.dumps({'fx': fx}, ensure_ascii=False), h))
        elif names or shader:
            pr = {'refs': names[:40], 'shader': shader}
            propupd.append((json.dumps(pr, ensure_ascii=False), h))
    c.executemany('INSERT OR IGNORE INTO refs VALUES(?,?,?,?,?,?)', urows)
    c.executemany('INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?)', rrows)
    c.executemany('UPDATE resources SET props=? WHERE hash=?', propupd)
    for k, v in sorted(stats.items()):
        c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('jbcf:' + k, v))
    con.commit()
    print('content refs: %d rows, %d relation edges, %d prop updates' %
          (len(urows), len(rrows), len(propupd)))
    for k in sorted(stats):
        print('   %-16s %6d' % (k, stats[k]))


def build_asset_groups(con):
    """Stage 3: collapse the graph into assets (one character / prop / skill effect).

    Components come from the content-derived `use-*` edges plus the directory-scoped
    structural edges.  Shared targets (a base skeleton, `template_default.mtl`) are cut
    by inbound degree, otherwise every asset would merge into one giant component.
    Texture names that have no hash in this install stay attached as `agroup_names` --
    the relationship is the finding, the missing blob identity is not ours to invent.
    """
    c = con.cursor()
    deg = dict(c.execute('SELECT to_hash, COUNT(*) FROM relations WHERE rel LIKE \'use-%\' '
                         'GROUP BY to_hash'))
    paths = dict(c.execute('SELECT hash, path FROM resources WHERE path IS NOT null'))
    exts = dict(c.execute('SELECT hash, ext FROM resources'))
    types = dict(c.execute('SELECT hash, type FROM resources'))
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    cut = structural = 0
    for f, t, rel in c.execute('SELECT from_hash, to_hash, rel FROM relations').fetchall():
        if not rel.startswith('use-'):
            structural += 1        # directory heuristics merge whole trees: not grouping edges
            continue
        if deg.get(t, 0) > SHARED_DEG:
            cut += 1               # base skeletons and shared material templates
            continue
        union(f, t)

    # dangling names first: a material that only contributes names is still an asset
    byname = {}
    for name, src in c.execute('SELECT name, from_hash FROM refs WHERE to_hash IS NULL'):
        r = byname.setdefault(name.lower(), [name, os.path.splitext(name)[1].lower(), 0, set()])
        r[2] += 1
        r[3].add(src)
    tn, owner, cls_by_lo = [], {}, {}
    for lo, (name, e, nrefs, srcs) in byname.items():
        cls = 'unique' if len(srcs) == 1 else 'shared'
        tn.append((name, e, nrefs, len(srcs), cls))
        cls_by_lo[lo] = (name, cls)
        for s in srcs:
            owner.setdefault(s, []).append(lo)

    comp = {}
    # 特效源文件的判据：扩展名优先，内容 magic 只当补充。
    # 原来只看 type='JBPU'，而 type 是「把 payload 解出来读 magic」才填得上的——
    # 跳过解包那一步时 226 个 .pu 会被标成 'missing'，它们的单文件组件就被下面
    # 「成员<2 且不属于 owner/fxsrc 就丢」那条规则整批扔掉，清单凭空少 209 组。
    # 组该不该存在不该取决于本机当时解没解包，所以这里认 ext='.pu'。
    # 实测（同一份重建库上只跑分组阶段）：12,871 → 13,097 组。
    # 残余差额没被本条解释：随包库有 47 个 stem 在重建后没有自己的组（同时新出 65 个），
    # 两边 relations 差 582 条边，union-find 对那一步敏感——另账待查，别当成已对齐。
    fxsrc = {h for (h,) in c.execute(
        "select hash from resources where type='JBPU' or ext='.pu'")}
    for s in list(owner) + list(fxsrc):
        find(s)          # a material that only contributes names is still an asset root
    for h in list(parent):
        comp.setdefault(find(h), []).append(h)

    c.executescript('''
      DROP TABLE IF EXISTS agroups;
      DROP TABLE IF EXISTS amembers;
      DROP TABLE IF EXISTS agroup_names;
      DROP TABLE IF EXISTS dangling;
      CREATE TABLE agroups(id INTEGER PRIMARY KEY, hub TEXT, hub_path TEXT, dir TEXT,
        stem TEXT, kind TEXT, n INT, n_mesh INT, n_mtl INT, n_ani INT, n_ske INT,
        n_tex INT, n_other INT, names INT);
      CREATE TABLE amembers(gid INT, hash TEXT, role TEXT, UNIQUE(gid, hash));
      CREATE TABLE agroup_names(gid INT, name TEXT, cls TEXT, UNIQUE(gid, name));
      CREATE TABLE dangling(name TEXT PRIMARY KEY, ext TEXT, n_refs INT, n_src INT, cls TEXT);
      CREATE INDEX ix_am_g ON amembers(gid);
      CREATE INDEX ix_am_h ON amembers(hash);
      CREATE INDEX ix_an_g ON agroup_names(gid);
    ''')

    c.executemany('INSERT OR REPLACE INTO dangling VALUES(?,?,?,?,?)', tn)

    def role_of(h):
        return ROLE.get(exts.get(h) or '',
                        'texture' if types.get(h) == 'texture' else 'other')

    mem, meta, stats = [], {}, collections.Counter()
    gid = 0
    for root, members in sorted(comp.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 2 and not any(m in owner or m in fxsrc for m in members):
            continue
        gid += 1
        named = [m for m in members if m in paths]
        hub = next((m for m in named if (exts.get(m) or '') == '.mdl'), '')
        if not hub and named:
            cand = [m for m in named
                    if os.path.splitext(os.path.basename(paths[m]))[0].lower() ==
                    os.path.basename(os.path.dirname(paths[m])).lower()]
            hub = cand[0] if cand else min(named, key=lambda m: len(paths[m]))
        if not hub:
            hub = members[0]
        cnt = collections.Counter()
        for m in members:
            r = role_of(m)
            cnt[r] += 1
            stats[r] += 1
            mem.append((gid, m, r))
        hp = paths.get(hub, '')
        d, fn = hp.rsplit('/', 1) if '/' in hp else ('', hp)
        meta[gid] = [hub, hp, d.lower(), os.path.splitext(fn)[0], kind_of(d), cnt]

    # absorb ungrouped siblings, but only where the directory holds exactly one asset
    gdir = {}
    for g, m in meta.items():
        gdir.setdefault(m[2], set()).add(g)
    assigned = {h for _, h, _ in mem}
    absorbed = 0
    for h, p in paths.items():
        if h in assigned:
            continue
        gs = gdir.get(os.path.dirname(p).lower())
        if gs and len(gs) == 1:
            g = next(iter(gs))
            r = role_of(h)
            mem.append((g, h, r))
            meta[g][5][r] += 1
            stats[r] += 1
            assigned.add(h)
            absorbed += 1
    rows = [(g, m[0], m[1], m[2], m[3], m[4], sum(m[5].values()), m[5]['mesh'],
             m[5]['material'], m[5]['animation'], m[5]['skeleton'], m[5]['texture'],
             m[5]['other'], 0) for g, m in meta.items()]
    c.executemany('INSERT OR REPLACE INTO amembers VALUES(?,?,?)', mem)
    c.executemany('INSERT OR REPLACE INTO agroups VALUES(%s)' % ','.join('?' * 14), rows)
    print('absorbed by single-asset directory: %d' % absorbed)

    # dangling texture names, classified by how many materials ask for them
    gof = {}
    for m, gid_ in c.execute('SELECT hash, gid FROM amembers').fetchall():
        gof[m] = gid_
    an = [(gof[s], cls_by_lo[lo][0], cls_by_lo[lo][1])
          for s, los in owner.items() if s in gof for lo in los]
    c.executemany('INSERT OR IGNORE INTO agroup_names VALUES(?,?,?)', an)
    for g, n in collections.Counter(x[0] for x in an).items():
        c.execute('UPDATE agroups SET names=? WHERE id=?', (n, g))
    orph = c.execute('SELECT COUNT(*) FROM resources r WHERE r.path IS NOT NULL AND NOT EXISTS'
                     ' (SELECT 1 FROM relations x WHERE x.to_hash=r.hash)').fetchone()[0]
    for k, v in (('groups', gid), ('members', len(mem)), ('shared-cut', cut),
                 ('dangling-names', len(tn)), ('names-attached', len(an)), ('named-orphans', orph)):
        c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('asset:' + k, v))
    con.commit()
    print('asset groups: %d (members %d) ; edges: content-used %d, structural %d, shared-cut %d'
      % (gid, len(mem), len(mem), structural, cut))
    print('roles: %s' % stats.most_common())
    print('texture names: %d  unique=%d shared=%d ; attached to groups: %d' %
          (len(tn), sum(1 for t in tn if t[4] == 'unique'),
           sum(1 for t in tn if t[4] == 'shared'), len(set(x[0] for x in an))))
    print('named resources with no inbound edge: %d' % orph)


def load_extras(con):
    """Fold the side-car tables produced by tagger.py / fingerprint.py into resources.db.

    They are loaded from TSV rather than written in place so each producer can run
    against a read-only database.
    """
    c = con.cursor()
    specs = [
        ('out/tags.tsv', 'asset_tags',
         'CREATE TABLE asset_tags(gid INT, tag TEXT, rule TEXT, confidence TEXT,'
         ' PRIMARY KEY(gid, tag))',
         'INSERT OR REPLACE INTO asset_tags VALUES(?,?,?,?)', 4),
        ('out/fingerprint.tsv', 'asset_fingerprint',
         'CREATE TABLE asset_fingerprint(gid INTEGER PRIMARY KEY, fp_asset TEXT, fp_model TEXT,'
         ' fp_skeleton TEXT, fp_mesh TEXT, fp_material TEXT, fp_animation TEXT,'
         ' fp_texture TEXT, fp_names TEXT, n_members INT, n_names INT)',
         'INSERT OR REPLACE INTO asset_fingerprint VALUES(%s)' % ','.join('?' * 11), 11),
    ]
    for rel, table, ddl, ins, ncols in specs:
        p = os.path.join(HERE, *rel.split('/'))
        if not os.path.isfile(p):
            print('extras: %-22s missing (%s)' % (table, rel))
            continue
        rows, skipped = [], 0
        with open(p, encoding='utf-8') as f:
            next(f, None)
            for line in f:
                a = line.rstrip('\n').split('\t')
                if len(a) < ncols or not a[0].isdigit():
                    skipped += 1
                    continue
                rows.append([int(a[0])] + a[1:ncols])
        c.execute('DROP TABLE IF EXISTS %s' % table)
        c.execute(ddl)
        c.executemany(ins, rows)
        c.execute('CREATE INDEX ix_%s ON %s(gid)' % (table[6:] + '_g', table))
        con.commit()
        print('extras: %-20s %6d rows%s' % (table, len(rows),
                                            '  (%d skipped)' % skipped if skipped else ''))


def analyze(con):
    """Let SQLite pick join orders from real statistics instead of its row guesses.

    Without `sqlite_stat1` the planner estimates table sizes, and a wrong estimate is
    what makes two structurally identical queries plan differently — the reason the
    workbench and the report could disagree about the same asset. Running this after
    every stage that adds rows keeps the plan stable and keeps concurrent readers cheap.
    """
    con.commit()
    t = time.time()
    con.execute('ANALYZE')
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM sqlite_stat1').fetchone()[0]
    print('analyze: %d 张表的统计已刷新（%.2fs）' % (n, time.time() - t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-rescan', action='store_true')
    ap.add_argument('--rels', action='store_true')
    ap.add_argument('--assets', action='store_true')
    ap.add_argument('--extras', action='store_true')
    ap.add_argument('--no-build', action='store_true',
                    help='run only the requested later stages against the existing db')
    ap.add_argument('--root', help='客户端根（含 data*.pak）；默认 $TLBB_ROOT，再默认 D:/TLGL')
    ap.add_argument('--db', help='建出来的 resources.db 落哪；默认 $TLBB_DB，再默认 .scratch/resources.db')
    a = ap.parse_args()
    global ROOT, DB
    if a.root:
        ROOT = a.root
    if a.db:
        DB = a.db
    print('root=%s' % ROOT); print('db=%s' % DB)
    if a.no_build:
        con = sqlite3.connect(DB)
    else:
        con, _best, _names = build(not a.no_rescan)
    if a.rels:
        build_relations(con)
    if a.assets:
        build_asset_groups(con)
    if a.extras:
        load_extras(con)
    analyze(con)
    cur = con.execute('SELECT COUNT(*) FROM resources').fetchone()[0]
    print('resources.db: %d resources, %d records, %d relations, %.1f MB' % (
        cur, con.execute('SELECT COUNT(*) FROM records').fetchone()[0],
        con.execute('SELECT COUNT(*) FROM relations').fetchone()[0],
        os.path.getsize(DB) / 1e6))


if __name__ == '__main__':
    main()
