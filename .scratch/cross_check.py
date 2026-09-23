import json, sqlite3

d = json.load(open(r'D:\TLGL\.scratch\baseline_now.json', encoding='utf-8'))
bl = {c['key'][0]: c['n'] for c in d['grades']}
print('BASELINE  A=%d B=%d C=%d  sum=%d  (groups=%d)' % (
    bl.get('A', 0), bl.get('B', 0), bl.get('C', 0),
    sum(bl.values()), d['totals']['groups']))

print('WORKBENCH A=20 B=2581 C=10479 D=0  sum=%d' % (20 + 2581 + 10479))
print('MATCH' if bl.get('A', 0) == 20 and bl.get('B', 0) == 2581 and bl.get('C', 0) == 10479 else 'MISMATCH')
print()

# Spot-check one of the A groups the workbench names, and one that used to be A2-only.
db = r'D:\TLGL\.scratch\resources.db'
con = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
c = con.cursor()
for gid in (1994, 2118, 1991, 24):
    c.execute("SELECT stem, dir FROM agroups WHERE id=?", (gid,))
    row = c.fetchone()
    c.execute("SELECT role FROM amembers WHERE gid=?", (gid,))
    roles = [r[0] for r in c.fetchall()]
    c.execute("""SELECT r.name, r.kind, CASE WHEN r.to_hash IS NULL THEN 0 ELSE 1 END
                 FROM refs r JOIN amembers m ON m.hash=r.from_hash AND m.gid=?
                 WHERE r.kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')
                 GROUP BY r.name""", (gid,))
    tex = c.fetchall()
    tot = len(tex); loc = sum(t[2] for t in tex)
    distinct = len(set(roles))
    grade = 'A' if (distinct >= 2 and tot > 0 and loc == tot) else ('B' if distinct >= 2 else 'C')
    print('gid=%-5s stem=%-34s dir=%-18s roles=%d(%s) tex=%d loc=%d -> %s'
          % (gid, row[0][:34], row[1][:18], distinct, ','.join(sorted(set(roles)))[:30], tot, loc, grade))
    for n, k, r in tex[:3]:
        print('        ref %-46s %-7s %s' % (n[:46], k, 'resolved' if r else 'dangling'))
con.close()
