"""Read-only: re-implement the engine path hash (sub_14059F020) in pure python,
validate it against resources.db named rows, then brute-force enumerate the
mobile_maps grid-scene naming space to see how many nameless tables can be re-named.
No writes anywhere."""
import sqlite3
import collections
import itertools
import re
import sys

M32 = 0xFFFFFFFF


def path_hash(p):
    if isinstance(p, str):
        p = p.encode('ascii', 'replace')
    h1 = 0x4E67C6A7
    h2 = 0
    for c in p:
        if 65 <= c <= 90:
            c += 32
        if c == 92:
            c = 47
        t = (c + h1 + ((h1 << 5) & M32) + (h1 >> 2)) & M32
        h1 ^= t
        h2 = (c + h2 * 65599) & M32
    return h1 | (h2 << 32)


c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row

print('=== 1. validate path_hash against named rows ===')
rows = c.execute("select path,hash from resources where named=1 and path is not null").fetchall()
ok = 0
bad = []
for r in rows:
    if '%016x' % path_hash(r['path']) == r['hash']:
        ok += 1
    elif len(bad) < 4:
        bad.append((r['path'], r['hash'], '%016x' % path_hash(r['path'])))
print('  %d / %d named rows reproduced by hash(path)  (%.2f%%)' % (ok, len(rows), 100.0 * ok / len(rows)))
for b in bad:
    print('   mismatch:', b)

print('\n=== 2. brute force grid-scene naming for the 1,126 nameless tables ===')
un = {r['hash']: r for r in c.execute("select hash,original,props from resources where subtype='grid753' and named=0")}
dirs = sorted({r[0] for r in c.execute("select distinct dir from resources where dir like 'mobile_maps/%'")})
print('  nameless targets=%d  map dirs=%d' % (len(un), len(dirs)))
found = {}
n_try = 0
A = (0, 1, 2, 3)
B = range(-4, 16)
C = range(-16, 5)
for d in dirs:
    for a in A:
        for b in B:
            for cc in C:
                p = '%s/%d_%d_%d.scene' % (d, a, b, cc)
                n_try += 1
                k = '%016x' % path_hash(p)
                if k in un and k not in found:
                    found[k] = p
print('  tried %d candidate paths -> recovered %d / %d nameless grid753 (%.1f%%)'
      % (n_try, len(found), len(un), 100.0 * len(found) / len(un)))
for k, v in list(found.items())[:8]:
    print('    ', k, v, un[k]['original'])
by = collections.Counter(v.split('/')[1] for v in found.values())
print('  spread over map dirs:', len(by), by.most_common(5))
print('  bytes recovered: %.2f MB / %.2f MB' % (sum(un[k]['original'] for k in found) / 1e6,
                                                sum(r['original'] for r in un.values()) / 1e6))
print('  any candidate path colliding with an EXISTING named row?')
allh = {r[0] for r in c.execute("select hash from resources")}
coll = 0
for d in dirs[:20]:
    for a in A:
        for b in B:
            for cc in C:
                if '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, b, cc)) in allh:
                    coll += 1
print('    in 20 dirs: %d of %d candidates hit some db row' % (coll, 20 * len(A) * len(B) * len(C)))

print('\n=== 3. is the same naming space able to name the nameless geom blobs? ===')
geom = {r[0] for r in c.execute("select hash from resources where type='geom'")}
h = collections.Counter()
for d in dirs[:30]:
    for a in A:
        for b in B:
            for cc in C:
                if '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, b, cc)) in geom:
                    h['scene-slot'] += 1
print('  grid-scene candidates hitting a geom hash (30 dirs):', h.most_common())
print('  nameless geom hashes present in names_jrpc.tsv:',
      sum(1 for l in open('D:/TLGL/.scratch/names_jrpc.tsv', encoding='utf-8') if l.split('\t')[0] in geom))
print('  nameless grid753 hashes present in names_jrpc.tsv:',
      sum(1 for l in open('D:/TLGL/.scratch/names_jrpc.tsv', encoding='utf-8') if l.split('\t')[0] in un))

print('\n=== 4. lattice holes per dir (does the recovery fill real gaps?) ===')
pat = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$')
per = collections.defaultdict(set)
for d, n in c.execute("select dir,name from resources where dir like 'mobile_maps/%' and ext='.scene' and named=1"):
    m = pat.match(n or '')
    if m:
        per[d].add((int(m.group(2)), int(m.group(3))))
rec = collections.defaultdict(set)
for p in found.values():
    m = pat.match(p.split('/')[-1])
    rec[p.rsplit('/', 1)[0]].add((int(m.group(2)), int(m.group(3))))
tot_hole = 0
detail = []
for d, cells in per.items():
    xs = sorted({x for x, _ in cells}); zs = sorted({z for _, z in cells})
    rect = {(x, z) for x in xs for z in zs}
    holes = rect - cells
    tot_hole += len(holes)
    filled = holes & rec.get(d, set())
    if filled:
        detail.append((d, len(holes), len(filled)))
print('  named dirs=%d, rectangular holes=%d, recovered-nameless grids=%d' % (len(per), tot_hole, len(found)))
print('  dirs where a recovered name lands exactly in a hole:', len(detail), detail[:6])
out_of_hole = sum(1 for p in found.values()
                  if True) - sum(x[2] for x in detail)
print('  recovered names NOT filling a rectangular hole:', out_of_hole)
