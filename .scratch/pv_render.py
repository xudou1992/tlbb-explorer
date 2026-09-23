"""One-off: render one PNG per JMT1 class; A/B test DXT3 vs DXT5 for the 8bpp class."""
import os, sqlite3, struct, collections, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND, parse, to_dds, SUB_BC1, OUT
from PIL import Image

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
rows = list(con.execute("select hash,path from resources where type='texture' "
                        "and path is not null order by original desc"))
buckets = collections.defaultdict(list)
for h, path in rows:
    p = FIND.get(h)
    if not p:
        continue
    j = parse(p)
    buckets[(j['codec'], hex(j['sub']), 'mip>1' if j['mips'] > 1 else 'mip=1')].append((h, path, j))
print('named-texture classes (declared 4CC / u32@8):')
for k in sorted(buckets, key=lambda x: -len(buckets[x])):
    print('   %-34s %5d' % (str(k), len(buckets[k])))

made = 0
for k in sorted(buckets, key=lambda x: -len(buckets[x])):
    if made >= 16:
        break
    for h, path, j in buckets[k][:2]:
        variants = (['DXT1', 'DXT3', 'DXT5'] if j['codec'] == 'DXT1' else [None])
        for v in variants:
            if v and (j['sub'] == SUB_BC1) != (v == 'DXT1'):
                continue
            try:
                d, kind = to_dds(j, v)
            except Exception as e:
                print('SKIP %s %s: %s' % (h, k, e))
                continue
            ext = 'webp' if kind == 'webp' else 'dds'
            fn = os.path.join(OUT, 'R_%s_%s.%s' % (h, kind, ext))
            open(fn, 'wb').write(d)
            im = Image.open(fn)
            im.load()
            rgba = im.convert('RGBA')
            png = os.path.join(OUT, 'R_%s_%s.png' % (h, kind))
            rgba.save(png)
            dat = list(rgba.getdata())
            uniq = len({p[:3] for p in dat[::97]})
            trans = sum(1 for p in dat if p[3] == 0) * 100 // len(dat)
            print('OK %-16s %-28s %-24s %4sx%-4s m=%-2s %-6s uniq~%-5s transp=%-3d%% -> %s'
                  % (h, os.path.basename(path), str(k), j['w'], j['h'], j['mips'], kind,
                     uniq, trans, os.path.basename(png)))
            made += 1
