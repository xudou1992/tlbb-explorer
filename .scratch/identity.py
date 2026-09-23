"""Asset identity v2: a content-stable fingerprint plus a structure signature.

Why v1 was not enough: `fingerprint.py` digested `filecrc`, the CRC of the *stored*
(compressed) bytes, so re-packing a pak with a different compression level would read
as "every asset changed".  The user's judgement table demands otherwise:

    压缩变化        -> 身份证不变
    pak 重新打包    -> 身份证不变
    成员排序变化    -> 身份证不变
    动作增加        -> 变化
    贴图替换        -> 变化

So identity is split into layers that answer different questions:

  id_content  per-role multiset of SHA-256 over the DECOMPRESSED payload.  Immune to
              packing, offsets, pak membership, `ver`, and member ordering.
  id_pack     per-role multiset of `filecrc` (stored bytes).  Differs from id_content
              exactly when the asset was re-packed rather than re-made.
  id_struct   shape of the asset: role counts plus the multiset of internal relation
              kinds.  Changes when the composition changes.
  id_names    referenced-but-missing names (the texture imports whose blobs this
              install does not name).  Normalised to lower-case basenames.
  id_asset    digest(id_content || id_struct) -- what a version comparison matches on.

usage:
  python identity.py                 # build blobs + asset_identity, then snapshot
  python identity.py --snapshot FILE # write a portable version snapshot
  python identity.py --diff A B      # compare two snapshots
  python identity.py --selftest      # prove the judgement table on synthetic edits
"""
import argparse
import collections
import hashlib
import json
import os
import sqlite3
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'resources.db')
OUT_ALL = os.path.join(HERE, 'out', 'all')
ROLES = ('model', 'skeleton', 'mesh', 'material', 'animation', 'texture', 'other')
ROLE_CN = {'model': '模型', 'skeleton': '骨骼', 'mesh': '子模型', 'material': '材质',
         'animation': '动作', 'texture': '贴图', 'other': '其他'}


def h16(*parts):
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:16]


def digests(files):
    """[path] -> [(path, sha256hex, size)]; a process pool keeps this I/O bound."""
    out = []
    for p in files:
        try:
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            out.append((p, h.hexdigest(), os.path.getsize(p)))
        except OSError:
            continue
    return out


def _worker(chunk):
    return digests(chunk)


def payload_paths():
    paths = []
    for pak in sorted(os.listdir(OUT_ALL)):
        d = os.path.join(OUT_ALL, pak)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if len(fn) >= 16 and os.path.isfile(p):
                paths.append(p)
    return paths


def build_blobs(con, workers=8):
    have = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blobs'"
                       ).fetchone()
    if have and con.execute('SELECT COUNT(*) FROM blobs').fetchone()[0]:
        print('blobs: already populated (%d rows)' %
              con.execute('SELECT COUNT(*) FROM blobs').fetchone()[0])
        return
    paths = payload_paths()
    print('blobs: %d payloads, %.2f GB' %
          (len(paths), sum(os.path.getsize(p) for p in paths) / 1e9))
    con.executescript('DROP TABLE IF EXISTS blobs;'
                      'CREATE TABLE blobs(hash TEXT PRIMARY KEY, sha TEXT, size INT);')
    chunks = [paths[i::workers] for i in range(workers)]
    n = 0
    with Pool(workers) as pool:
        for res in pool.imap_unordered(_worker, chunks):
            con.executemany('INSERT OR REPLACE INTO blobs VALUES(?,?,?)',
                            [(p.rsplit(os.sep, 1)[1][:16], s, z) for p, s, z in res])
            n += len(res)
            print('\r  %d/%d' % (n, len(paths)), end='', flush=True)
    print()
    con.commit()


def multiset(vals):
    return h16(','.join(sorted(v for v in vals if v)))


def by_role(members, field):
    d = collections.defaultdict(list)
    for m in members:
        if m.get(field):
            d[m['role']].append(m[field])
    return d


def id_content_of(members):
    """Digest of the decompressed bytes, grouped per role — order and packing cannot
    move it, only real content or membership can.

    Roles come from the data, not a fixed list: 'effect' was once missing from ROLES
    and that silently excluded every .pu file from its own asset identity.
    """
    g = by_role(members, 'sha')
    return h16(*['%s:%s' % (r, multiset(g[r])) for r in sorted(g)])


def id_pack_of(members):
    g = by_role(members, 'crc')
    return h16(*['%s:%s' % (r, multiset(g[r])) for r in sorted(g)])


def id_struct_of(members, rels=None):
    cnt = collections.Counter(m['role'] for m in members)
    return h16(json.dumps(sorted(cnt.items())),
               json.dumps(sorted((rels or {}).items())))


def id_asset_of(idc, ids):
    return h16(idc, ids)


def build_identity(con):
    con.executescript('''
      DROP TABLE IF EXISTS asset_identity;
      CREATE TABLE asset_identity(gid INTEGER PRIMARY KEY, id_asset TEXT, id_content TEXT,
        id_pack TEXT, id_struct TEXT, id_names TEXT, n_members INT, n_names INT,
        hub_path TEXT, dir TEXT, stem TEXT, kind TEXT);
      CREATE INDEX ix_ia_asset ON asset_identity(id_asset);
    ''')
    mem = collections.defaultdict(list)
    for gid, role, h in con.execute('SELECT gid, role, hash FROM amembers'):
        mem[gid].append((role, h))
    sha = dict(con.execute('SELECT hash, sha FROM blobs'))
    crc = {h: c for h, c in con.execute('SELECT hash, filecrc FROM resources')}
    typ = {h: (t, e, k, w, hh) for h, t, e, k, w, hh in
           con.execute('SELECT hash, type, ext, codec, width, height FROM resources')}
    paths = dict(con.execute('SELECT hash, path FROM resources WHERE path IS NOT null'))
    names = collections.defaultdict(list)
    for gid, nm in con.execute('SELECT gid, name FROM agroup_names'):
        names[gid].append(os.path.basename(nm).lower())
    rels = collections.defaultdict(collections.Counter)
    for g1, f, t, rel in con.execute(
            'SELECT a.gid, r.from_hash, r.to_hash, r.rel FROM relations r '
            'JOIN amembers a ON a.hash=r.from_hash JOIN amembers b '
            'ON b.hash=r.to_hash AND b.gid=a.gid'):
        rels[g1][rel] += 1

    rows, snap = [], []
    for gid, hub, hp, d, stem, kind, n in con.execute(
            'SELECT id, hub, hub_path, dir, stem, kind, n FROM agroups'):
        ms = [{'role': role,
               'name': os.path.basename(paths[h] or h) if h in paths else h,
               'sha': (sha.get(h) or '')[:16],
               'crc': '%08x' % (crc[h] & 0xffffffff) if crc.get(h) is not None else '',
               'type': (typ.get(h) or ('', '', '', None, None))[0],
               'w': (typ.get(h) or ('', '', '', None, None))[3],
               'h': (typ.get(h) or ('', '', '', None, None))[4]}
              for role, h in mem[gid]]
        idc, idp = id_content_of(ms), id_pack_of(ms)
        ids, idn = id_struct_of(ms, rels[gid]), multiset(names[gid])
        ida = id_asset_of(idc, ids)
        rows.append((gid, ida, idc, idp, ids, idn, len(ms),
                     len(names[gid]), hp, d, stem, kind))
        snap.append({
            'gid': gid, 'stem': stem, 'kind': kind, 'dir': d, 'hub_path': hp,
            'id_content': idc, 'id_pack': idp, 'id_struct': ids, 'id_names': idn,
            'id_asset': ida, 'rels': dict(rels[gid]),
            'members': ms,
            'names': sorted(set(names[gid])),
        })
    con.executemany('INSERT OR REPLACE INTO asset_identity VALUES(%s)' % ','.join('?' * 12),
                    rows)
    con.commit()
    print('asset_identity: %d rows, %d distinct id_asset' %
          (len(rows), len({r[1] for r in rows})))
    return snap


def snapshot(con, path):
    snap = build_identity(con)
    meta = dict(con.execute('SELECT key, value FROM meta'))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'version': 2, 'built_from': 'resources.db',
                   'assets': snap}, f, ensure_ascii=False, separators=(',', ':'))
    print('snapshot -> %s (%.1f MB)' % (path, os.path.getsize(path) / 1e6))


def compare(A, B):
    """Verdicts per the judgement table, with per-member detail.

    Matching order is path, then identity, then member overlap: two different assets can
    legitimately share an identity (this install has 1,062 such duplicates), so identity
    alone must never consume the same candidate twice.
    """
    left = {id(x): x for x in B['assets']}
    by_path, by_id = collections.defaultdict(list), collections.defaultdict(list)
    for x in B['assets']:
        if x.get('stem'):
            by_path[(x['dir'], x['stem'])].append(id(x))
        by_id[x['id_asset']].append(id(x))
    # A path shared by several assets proves nothing (792 assets have no name at all),
    # so only unique paths may pair directly.  A shared identity is different: the
    # contents really are equal, so any candidate is a legal twin -- but prefer one
    # whose packing matches too, otherwise re-packed assets get paired with the wrong
    # twin and the counts drift (seen with the 3,359 duplicate effect assets).
    uniq_path = {k: v[0] for k, v in by_path.items() if len(v) == 1}

    def take_best(cands, a):
        live = [k for k in cands if k in left]
        if not live:
            return None
        ka = {(m['role'], m['name']) for m in a['members']}

        def rank(k):
            x = left[k]
            return (x['id_pack'] != a['id_pack'],
                    -len({(m['role'], m['name']) for m in x['members']} & ka))
        live.sort(key=rank)
        return left.pop(live[0])

    out = collections.Counter()
    lines = []
    for a in A['assets']:
        b = take_best([uniq_path[(a['dir'], a['stem'])]], a) \
            if (a['dir'], a['stem']) in uniq_path else None
        if b is None:
            b = take_best(by_id.get(a['id_asset'], []), a)
        if b is None:
            ka = {(m['role'], m['name']) for m in a['members']}
            scored = [k for k, x in left.items()
                      if len({(m['role'], m['name']) for m in x['members']} & ka)
                      >= max(1, len(ka) // 2)]
            b = take_best(scored, a)
        if b is None:
            out['资产消失'] += 1
            lines.append([str(a['stem'] or a['gid']), a['kind'], '资产消失',
                          '%d 个文件' % len(a['members'])])
            continue
        if a['id_asset'] == b['id_asset']:
            if a['id_pack'] == b['id_pack']:
                out['相同'] += 1
            else:
                out['仅重新打包'] += 1
                lines.append([str(b['stem'] or b['gid']), b['kind'], '仅重新打包',
                              '内容完全一致，只有压缩结果不同'])
            continue
        ma = {(m['role'], m['name']): m for m in a['members']}
        mb = {(m['role'], m['name']): m for m in b['members']}
        add = [k for k in mb if k not in ma]
        rem = [k for k in ma if k not in mb]
        chg = [k for k in set(ma) & set(mb)
               if ma[k]['sha'] and mb[k]['sha'] and ma[k]['sha'] != mb[k]['sha']]
        plus = collections.Counter(r for r, _ in add)
        minus = collections.Counter(r for r, _ in rem)
        txt = []
        for r in sorted(set(plus) | set(minus)):
            if plus[r]:
                txt.append('新增 %d 个%s' % (plus[r], ROLE_CN.get(r, r)))
            if minus[r]:
                txt.append('删除 %d 个%s' % (minus[r], ROLE_CN.get(r, r)))
        if chg:
            txt.append('%d 个文件内容被替换' % len(chg))
        if not txt:
            txt.append('成员一致但分组边界变化')
        verdict = ('结构变化' if (plus or minus) else '内容微调' if chg else '身份证不同')
        out[verdict] += 1
        lines.append([str(b['stem'] or a['stem']), b['kind'], verdict, '；'.join(txt)])
    for x in left.values():
        out['新资产出现'] += 1
        lines.append([str(x['stem'] or x['gid']), x['kind'], '新资产出现',
                      '%d 个文件' % len(x['members'])])
    return out, lines


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', default=os.path.join(HERE, 'out', 'versionA.json'))
    ap.add_argument('--diff', nargs=2, metavar=('A', 'B'))
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--no-scan', action='store_true')
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    con.execute('PRAGMA busy_timeout=180000')
    if a.diff:
        out, lines = compare(load(a.diff[0]), load(a.diff[1]))
        print(json.dumps(dict(out), ensure_ascii=False))
        for row in lines[:80]:
            print('  %-28s %-12s %-10s %s' % tuple(row))
        return
    if not a.no_scan:
        build_blobs(con)
    snapshot(con, a.snapshot)
    if a.selftest:
        import selftest_identity
        selftest_identity.run(load(a.snapshot))


if __name__ == '__main__':
    main()
