import sys, struct, re, random, collections, sqlite3, binascii
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le, hist

R = Reader()
c = conn()
random.seed(7)


def probe(label, sql, limit=None, cap=None):
    rows = c.execute(sql).fetchall()
    if limit:
        rows = random.sample(rows, min(limit, len(rows)))
    ok = 0
    out = []
    for row in rows:
        b, why = R.get(row)
        if b is None:
            out.append((row['hash'], why, None))
            continue
        ok += 1
        out.append((row['hash'], why, b))
    print('\n########## %s : n=%d decoded_ok=%d ##########' % (label, len(rows), ok))
    return out


def show(items, n, full=False):
    for h, why, b in items[:n]:
        if b is None:
            print('  %s %-14s' % (h, why))
            continue
        print('  %s %-14s len=%d' % (h, why, len(b)))
        print('     hex32 %s' % b[:32].hex(' '))
        print('     u32x8 %s' % u32le(b, 8))
        print('     asc48 %r' % b[:48])
        print('     strs  %s' % strings(b[:6000], 8))


# ---------- item 1: type=set .scene ----------
it = probe('ITEM1 set/.scene (ALL)',
           "select * from resources where type='set' and ext='.scene'")
mag = collections.Counter()
banner = 0
mesh_names = 0
for h, why, b in it:
    if b is None:
        continue
    tag = b[:8].hex(' ')
    m = b[:4]
    mag[(m.hex(), m.decode('latin1', 'replace') if re.match(rb'^[\x20-\x7e]*$', m) else '')] += 1
    if b'Copyright 2013' in b[:256]:
        banner += 1
    if b'.mesh' in b[:8000]:
        mesh_names += 1
print('  first4 magic hist:', mag.most_common(8))
print('  banner@head:', banner, ' has .mesh in first 8KB:', mesh_names)
sizes = collections.Counter(len(b) for _, _, b in it if b)
print('  size hist:', sizes.most_common(8))
show(it, 5)

# ---------- item 6: type=geom raw ----------
it6 = probe('ITEM6 geom/raw (sample 400)',
            "select * from resources where type='geom'", limit=400)
m6 = collections.Counter()
b6 = 0
mesh_tag = 0
strs_seen = 0
for h, why, b in it6:
    if b is None:
        continue
    m6[b[:4].hex() + '|' + b[:4].decode('latin1', 'replace')] += 1
    if b'Copyright 2013' in b[:512]:
        b6 += 1
    if re.search(rb'mesh', b[:200]):
        mesh_tag += 1
    if strings(b, 3):
        strs_seen += 1
print('  first4 magic hist:', m6.most_common(6))
print('  Copyright banner in first 512B:', b6, '/', len(it6))
print('  "mesh" token in first 200B:', mesh_tag)
print('  files with >=4char ascii runs:', strs_seen)
print('  len hist:', collections.Counter(len(b) for _, _, b in it6 if b).most_common(6))
show(it6, 6)

# ---------- item 3: .tani ----------
it3 = probe('ITEM3 .tani (sample 80)', "select * from resources where ext='.tani'", limit=80)
m3 = collections.Counter()
for h, why, b in it3:
    if b:
        m3[b[:4].hex() + '|' + b[:4].decode('latin1', 'replace')] += 1
print('  first4 magic hist:', m3.most_common(6))
print('  len hist:', collections.Counter(len(b) for _, _, b in it3 if b).most_common(10))
show(it3, 6)

# ---------- item 4: .nav + NAVF ----------
it4 = probe('ITEM4 .nav named (ALL 25)', "select * from resources where ext='.nav'")
m4 = collections.Counter()
for h, why, b in it4:
    if b:
        m4[b[:4].hex() + '|' + b[:4].decode('latin1', 'replace')] += 1
print('  first4 magic hist:', m4.most_common(6))
show(it4, 4)
it4b = probe('ITEM4b NAVF unnamed (sample 60)', "select * from resources where type='NAVF' and named=0", limit=60)
m4b = collections.Counter()
for h, why, b in it4b:
    if b:
        m4b[b[:4].hex() + '|' + b[:4].decode('latin1', 'replace')] += 1
print('  first4 magic hist:', m4b.most_common(6))
show(it4b, 3)

# ---------- item 5: mapref tab280 ----------
it5 = probe('ITEM5 mapref/tab280 (ALL)', "select * from resources where type='mapref'")
cnt = collections.Counter()
bodies = []
allwords = []
for h, why, b in it5:
    if b:
        cnt[len(b)] += 1
        w = u32le(b, 72)
        cnt2 = w[0]
        bodies.append(tuple(w))
        allwords.extend(w)
print('  len hist:', cnt.most_common(5))
print('  word0 hist:', hist([x[0] for x in bodies]))
print('  word1 hist:', hist([x[1] for x in bodies])[:8])
print('  word2 hist:', hist([x[2] for x in bodies])[:8])
nonzero_tail = [x for x in bodies if any(v != 0 for v in x[2:])]
print('  bodies with nonzero after word2:', len(nonzero_tail), '/', len(bodies))
mn = min((v for x in bodies for v in x[2:] if v), default=None)
mx = max((v for x in bodies for v in x[2:] if v), default=None)
print('  body u32 min/max:', mn, mx, 'hex', hex(mn) if mn else None, hex(mx) if mx else None)
print('  distinct body word count:', len({v for x in bodies for v in x[2:]}))
print('  sample bodies:')
for x in bodies[:6]:
    print('    ', x)

# ---------- item 2: unnamed grid753 content ----------
it2 = probe('ITEM2 grid753 unnamed (sample 120)', "select * from resources where subtype='grid753' and named=0", limit=120)
c2 = collections.Counter()
for h, why, b in it2:
    if b:
        c2[(u32le(b, 2)[0] if len(b) >= 8 else None, u32le(b, 2)[1] if len(b) >= 8 else None)] += 1
print('  (word0,word1) hist:', c2.most_common(8))
show(it2, 4)
