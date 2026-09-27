import collections
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]

# --- 1. are the recovered paths literally present in ResourcePath.cfg? ---
cfg = C.execute("select * from resources where hash='4b761249ad5d605c'").fetchone()
cb, why = R.get(cfg)
print('ResourcePath.cfg decoded %s len=%d' % (why, len(cb)))
un = dict(Q("select hash,original from resources where subtype='grid753' and named=0"))
dirs = [d for (d,) in Q("select distinct dir from resources where dir like 'mobile_maps/%'")]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = '%s/%d_%d_%d.scene' % (d, a, y, z)
print('recovered:', len(found), '/', len(un))
ins = sum(1 for p in found.values() if p.encode() in cb)
leaf = sum(1 for p in found.values() if p.split('/')[-1].encode() in cb and p.rsplit('/', 1)[0].split('/')[-1].encode() in cb)
print('  完整路径串出现在 cfg 里: %d / %d' % (ins, len(found)))
print('  (目录尾名 + 文件名 分别出现在 cfg 串流里): %d' % leaf)
# how many nameless-hash paths would a *full* enumeration of the cfg cover:
print('  cfg 里 .scene 结尾的路径串条数(粗算): %d' % cb.count(b'.scene'))

# --- 2. which extension recovered the nameless NAVF / binary blocks ---
tgt = {
    'NAVF-un': {r[0] for r in Q("select hash from resources where type='NAVF' and named=0")},
    'bin-un': {r[0] for r in Q("select hash from resources where type='binary' and named=0")},
    'tiny-un': {r[0] for r in Q("select hash from resources where type='tiny' and named=0")},
    'tex-un': {r[0] for r in Q("select hash from resources where type='texture' and named=0")},
    'ani-un': {r[0] for r in Q("select hash from resources where type='ani' and named=0")},
    'mesh-un': {r[0] for r in Q("select hash from resources where type='mesh' and named=0")},
    'geom': {r[0] for r in Q("select hash from resources where type='geom'")},
    'mapref': {r[0] for r in Q("select hash from resources where type='mapref'")},
}
hits = collections.defaultdict(set)
EXTS = ['.scene', '.nav', '.map', '.sfl', '.mesh', '.mtl', '.pu', '.ani', '.tga', '.bin', '.dat', '.jmdl',
        '.set', '.col', '.phy', '.geo', '.vb', '.ib', '.buf', '.cbuf', '.lod', '.obj', '.txt', '.xml', '.fbx']
tried = 0
for d in dirs:
    leaf0 = d.split('/')[-1]
    cands = []
    for e in EXTS:
        cands += ['%s/%s%s' % (d, leaf0, e), '%s/%s/%s%s' % (d, leaf0, leaf0, e)]
    for a in (0, 1):
        for y in range(-3, 13):
            for z in range(-13, 3):
                for e in ('.scene', '.nav', '.map', '.sfl'):
                    cands.append('%s/%d_%d_%d%s' % (d, a, y, z, e))
    for p in cands:
        tried += 1
        k = '%016x' % path_hash(p)
        for nm, t in tgt.items():
            if k in t:
                hits[nm].add(p)
print('\nenumerated %d paths ; recovered nameless rows per class:' % tried)
for nm in tgt:
    print('  %-9s rows=%6d recovered-by-name=%5d  e.g. %s' % (nm, len(tgt[nm]), len(hits[nm]),
          sorted(hits[nm])[:2]))
