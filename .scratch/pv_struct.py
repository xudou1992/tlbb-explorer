"""One-off: structural invariants for JBCF / scene / JBPU / GATA / NAVF / mapref / mesh / ani."""
import os, sys, sqlite3, struct, collections, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
recs = dict(con.execute("select hash,count(*) from records group by 1"))
NAME = re.compile(rb'[\w\-/\\.]{5,60}\.(?:mesh|tga|ani|mtl|ske|mdl|pu|scene|wav|ogg|dds|tab)\b')


def probe(typ, limit=1200):
    c = collections.Counter()
    ex = []
    for h, path in con.execute("select hash,path from resources where type=? limit ?",
                               (typ, limit)):
        p = FIND.get(h)
        if not p:
            c['no-payload'] += 1
            continue
        b = open(p, 'rb').read()
        n = len(b)
        a = struct.unpack_from('<10I', b.ljust(40, b'\0'), 0)
        c['n'] += 1
        if typ == 'JBCF':
            c['u32@8==8'] += a[2] == 8
            c['u32@12==size-16'] += a[3] == n - 16
            c['u32@16==86'] += a[4] == 86
            c['u32@24 in 88..170'] += 88 <= a[6] <= 170
            c['has-plaintext-name'] += bool(NAME.search(b))
        elif typ == 'scene':
            c['u32@4==753'] += a[1] == 753
            c['u32@4==749'] += a[1] == 749
            m = NAME.search(b)
            c['embeds-resource-path'] += bool(m)
            if m and len(ex) < 3:
                ex.append((path or h, n, a[0], m.group()[:60].decode('latin1')))
            c['count*recsize~=size'] += bool(a[0] and 20 < n / a[0] < 4000)
        elif typ == 'JBPU':
            c['u32@4<=64'] += a[1] <= 64
            c['u32@8<=64'] += a[2] <= 64
            c['embeds-resource-path'] += bool(NAME.search(b))
            c['has-jule-ascii'] += b'W65j' in b
            if len(ex) < 3:
                ex.append((path or h, n, a[1], a[2]))
        elif typ == 'GATA':
            e = b.find(b'\0', 8)
            c['u32@4==0'] += a[1] == 0
            c['self-path@8'] += 8 < e < 200
            c['embeds-resource-path'] += bool(NAME.search(b[80:]))
            if len(ex) < 3:
                ex.append((path or h, n, b[8:e][:60].decode('latin1')))
        elif typ in ('NAVF', 'mapref'):
            if typ == 'NAVF':
                c['ver==2'] += a[1] == 2
                for i in (2, 3, 4):
                    c['u32@%d<100000' % (4 * i)] += a[i] < 100000
            else:
                c['u32@4==280'] += a[1] == 280
                c['u32@0<2000'] += a[0] < 2000
                c['has-64bit-pointer(0x7f..)'] += b.count(b'\xf7\x7f\x00') > 2
        elif typ in ('mesh', 'ani', 'set', 'geom'):
            off = 140
            v1, v2 = struct.unpack_from('<II', b.ljust(148, b'\0'), off)
            c['u32@140<200000'] += v1 < 200000
            c['u32@144<200000'] += v2 < 200000
            c['embeds-resource-path'] += bool(NAME.search(b))
            bn = b.count(b'bip01') + b.count(b'Bip01')
            c['has-bip01-bone-names'] += bn > 0
            c['has-dragonBones-keys'] += (b'armature' in b or b'dragonBones' in b or
                                          b'textureAtlas' in b)
            if len(ex) < 3:
                ex.append((path or h, n, v1, v2))
    print('--- %s' % typ)
    for k, v in c.most_common(14):
        print('     %-28s %5d/%d' % (k, v, c['n']))
    for e in ex:
        print('     ex %s' % (e,))


for t in ('JBCF', 'scene', 'JBPU', 'GATA', 'NAVF', 'mapref', 'mesh', 'ani', 'set', 'geom'):
    probe(t)

print('\n======== mesh / ani field-vs-size regression ========')
for typ in ('mesh', 'ani'):
    pts = []
    for h, in con.execute("select hash from resources where type=? limit 400", (typ,)):
        p = FIND.get(h)
        if not p:
            continue
        b = open(p, 'rb').read()
        v1, v2, v3, v4 = struct.unpack_from('<4I', b, 140)
        pts.append((len(b), v1, v2, v3, v4))
    pts.sort()
    print('   %s: size, u32@140, @144, @148, @152' % typ)
    for r in pts[:3] + pts[len(pts) // 2:len(pts) // 2 + 2] + pts[-3:]:
        print('      %9d %8d %8d %6d %6d   bytes/(@140+1)= %.1f' %
              (r[0], r[1], r[2], r[3], r[4], r[0] / max(1, r[1] + 1)))
