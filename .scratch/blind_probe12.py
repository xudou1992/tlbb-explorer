import sys, os, re, struct, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

HERE = r'D:\TLGL\.scratch'
print('=== name tsv files present ===')
for fn in ('names_jrpc.tsv', 'names.tsv', 'names_self.tsv', 'names_round.tsv', 'names_new.tsv'):
    p = os.path.join(HERE, fn)
    print('  ', fn, os.path.getsize(p) if os.path.isfile(p) else 'MISSING')

# --- JRPC name table: does it list paths for the nameless resources? ---
def load(fn):
    p = os.path.join(HERE, fn)
    d = {}
    if not os.path.isfile(p):
        return d
    with open(p, encoding='utf-8', errors='replace') as f:
        head = f.readline()
        for l in f:
            a = l.rstrip('\n').split('\t')
            if len(a) >= 2 and a[0] and a[1]:
                d[a[0]] = a[1]
    return d

jr = load('names_jrpc.tsv')
print('  jrpc entries:', len(jr), 'sample:', list(jr.items())[:3])

c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]
print('\n=== how many NAMELESS resources have a jrpc name? ===')
nameless = {r[0] for r in q("select hash from resources where named=0")}
print('  nameless rows:', len(nameless))
hit = {h for h in nameless if h in jr}
print('  nameless with a jrpc name:', len(hit))
byclass = collections.Counter()
for h in hit:
    pass
cls = dict((r[0], (r[1], r[2])) for r in q("select hash,type,subtype from resources where named=0"))
for h in hit:
    byclass[cls.get(h)] += 1
print('  by class:', byclass.most_common(10))
print('  sample recovered names for geom:', [jr[h] for h in list(hit) if cls.get(h) == ('geom', 'raw')][:5])
print('  sample recovered names for grid753-un:', [jr[h] for h in list(hit) if cls.get(h) == ('scene', 'grid753')][:5])

print('\n=== jrpc paths that are NOT attached to any db row ===')
allh = {r[0] for r in q("select hash from resources")}
extra = {k: v for k, v in jr.items() if k not in allh}
print('  jrpc hashes absent from resources table:', len(extra))
ext = collections.Counter(os.path.splitext(v)[1].lower() for v in jr.values())
print('  jrpc path ext hist:', ext.most_common(14))
dirstat = collections.Counter(v.split('/')[0] for v in jr.values())
print('  jrpc top-level dirs:', dirstat.most_common(10))
sc = [v for v in jr.values() if v.lower().endswith('.scene')]
print('  jrpc .scene paths:', len(sc), sc[:5])
