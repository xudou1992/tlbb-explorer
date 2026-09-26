import sqlite3, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h

c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
hi2row = {}
lowdup = 0
hids = []
for h, named, typ, ext in c.execute("select hash, named, type, ext from resources"):
    v = int(h, 16)
    hi = v >> 32
    hids.append((hi, v & 0xffffffff, named, typ, ext))
dist = len({x[0] for x in hids})
print(f'entries={len(hids)} distinct high32={dist}')
cnt = collections.Counter(x[0] for x in hids)
dups = {k:v for k,v in cnt.items() if v>1}
print(f'high32 collisions: {len(dups)} entries involved {sum(dups.values())}')

# cfg paths -> high32 lookup
pairs = []
for line in open('D:/TLGL/.scratch/cfg_paths.txt', encoding='utf-8'):
    p = line.rstrip('\n')
    if p: pairs.append(p)
p2hi = {p: sdbm(p.lower().encode()) for p in pairs}
hit_named = hit_anon = miss = 0
tga_named = tga_anon = tga_miss = 0
hit_rows = []
for p in pairs:
    hi = p2hi[p]
    row = hi2row.get(hi)
    # need full lookup; build dict hi->(named,typ,ext)
    r = hiby.get(hi) if False else None
for r in [None]: pass
hiby = {}
for hi, lo, named, typ, ext in hids:
    hiby.setdefault(hi, []).append((lo, named, typ, ext))
for p in pairs:
    hi = p2hi[p]
    lst = hiby.get(hi)
    is_tga = p.lower().endswith('.tga')
    if not lst:
        miss += 1
        if is_tga: tga_miss += 1
    else:
        for lo, named, typ, ext in lst:
            if named:
                hit_named += 1
                if is_tga: tga_named += 1
            else:
                hit_anon += 1
                if is_tga: tga_anon += 1
                if len(hit_rows) < 8: hit_rows.append((p, typ, ext))
print(f'\ncfg 72,764 paths -> pak lookup: hit_named={hit_named} hit_ANON={hit_anon} miss={miss}')
print(f'tga specifically: named={tga_named} ANON={tga_anon} miss={tga_miss}')
print('anon hit samples:', hit_rows)
