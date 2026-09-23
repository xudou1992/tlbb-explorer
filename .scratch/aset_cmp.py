import sqlite3
from collections import defaultdict

db = r'D:\TLGL\.scratch\resources.db'
con = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
c = con.cursor()
TEX = ('.tga', '.dds', '.png', '.jpg', '.jpeg', '.bmp', '.webp')
ph = ','.join('?' * len(TEX))

c.execute("SELECT gid, role FROM amembers")
roles = defaultdict(list)
for gid, role in c.fetchall():
    roles[gid].append(role)

# Route 1: texture_refs() — dedup by NAME (the shared query, now used by both)
c.execute("""SELECT m.gid, r.name, max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END)
             FROM refs r JOIN amembers m ON m.hash=r.from_hash
             WHERE r.kind IN (%s) GROUP BY m.gid, r.name""" % ph, TEX)
by_name = defaultdict(list)
for gid, name, res in c.fetchall():
    by_name[gid].append((name, res))

# Route 2: image_candidates() — walk refs_from_group, dedup by HASH
c.execute("SELECT gid, hash FROM amembers")
gh = defaultdict(list)
for gid, h in c.fetchall():
    gh[gid].append(h)
c.execute("""SELECT from_hash, name, to_hash FROM refs WHERE kind IN (%s)""" % ph, TEX)
refrows = c.fetchall()

c.execute("SELECT id FROM agroups")
gids = [r[0] for r in c.fetchall()]

Aset = set()
for gid in gids:
    distinct = len(set(roles.get(gid, [])))
    if distinct < 2:
        continue
    pairs = by_name.get(gid, [])
    tot = len(pairs); loc = sum(1 for _, r in pairs if r)
    if tot > 0 and loc == tot:
        Aset.add(gid)

print('A-set size (by-name route)  =', len(Aset))

# Now the by-hash route
from_hash_to_gids = defaultdict(set)
for gid, pairs in gh.items():
    for h in pairs:
        from_hash_to_gids[h].add(gid)

Ahash = set()
for gid in gids:
    distinct = len(set(roles.get(gid, [])))
    if distinct < 2:
        continue
    tot = 0; loc = 0
    seen_names = {}
    for fh, name, toh in refrows:
        if gid not in from_hash_to_gids.get(fh, ()):
            continue
        seen_names.setdefault(name, 0)
        if toh is not None:
            seen_names[name] = 1
    tot = len(seen_names)
    loc = sum(seen_names.values())
    if tot > 0 and loc == tot:
        Ahash.add(gid)

print('A-set size (by-hash route)  =', len(Ahash))
print('identical sets?', Aset == Ahash)
print('only by-name:', sorted(Aset - Ahash)[:25])
print('only by-hash:', sorted(Ahash - Aset)[:25])
con.close()
