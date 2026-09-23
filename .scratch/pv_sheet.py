"""One-off: rebuild JMT1 -> DDS -> PNG for one sample of each real class (visual proof)."""
import os, sys, io, sqlite3, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND, parse, OUT, dds_header, walk, SUB_BC1
from PIL import Image

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
classes = collections.defaultdict(list)
for h, path in con.execute("select hash,path from resources where type='texture' "
                           "order by original desc"):
    p = FIND.get(h)
    if not p:
        continue
    j = parse(p)
    b0 = ((j['w'] + 3) // 4) * ((j['h'] + 3) // 4)
    if j['raw'][28:32] == b'RIFF':
        k = 'WEBP/COLW'
    elif j['l0'] == b0 * 8:
        k = 'BC1/' + j['codec']
    elif j['codec'] == 'ALI8' and j['l0'] == j['w'] * j['h']:
        k = 'RAW8/ALI8'
    elif j['l0'] == b0 * 16:
        k = 'BC3/' + j['codec']
    elif j['l0'] == j['w'] * j['h'] * 4:
        k = 'RGBA32/' + j['codec']
    else:
        k = 'other/' + j['codec']
    if 64 <= j['w'] <= 1024 and 48 <= j['h'] <= 1024 and len(classes[k]) < 4:
        classes[k].append((h, path, j))
print('classes found in the 8000 largest textures:')
for k in sorted(classes):
    print('   %-16s %d' % (k, len(classes[k])))

tiles = []
for k in sorted(classes):
    for h, path, j in classes[k][:2]:
        w, H, mips = j['w'], j['h'], j['mips']
        try:
            if k.startswith('WEBP'):
                im = Image.open(io.BytesIO(j['raw'][28:28 + j['l0']]))
            elif k.startswith('RAW8'):
                im = Image.frombytes('L', (w, H), j['raw'][28:28 + w * H]).convert('RGBA')
            else:
                ms = walk(j) or [(0, 28, j['l0'])]
                body = b''.join(j['raw'][o:o + s] for _, o, s in ms)
                if k.startswith('BC1'):
                    d = dds_header(w, H, b'DXT1', mips) + body
                elif k.startswith('BC3'):
                    d = dds_header(w, H, b'DXT5', mips) + body
                else:
                    d = dds_header(w, H, b'BGRA', 1, 32,
                                   (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
                                   0x40 | 0x2 | 0x1, w * 4) + body[:w * H * 4]
                fn = os.path.join(OUT, 'T_%s.dds' % h)
                open(fn, 'wb').write(d)
                im = Image.open(fn)
            im.load()
            im = im.convert('RGBA')
        except Exception as e:
            print('  FAIL %-14s %s: %s' % (k, h, repr(e)[:70]))
            continue
        print('  ok   %-14s %-16s %4sx%-4s mips=%-2s l0=%-8s %s' %
              (k, h, w, H, mips, j['l0'], (path or '(unnamed)').split('/')[-1]))
        im.thumbnail((200, 200), Image.LANCZOS)
        tiles.append((k, h, im))

sheet = Image.new('RGB', (200 * 4, 200 * ((len(tiles) + 3) // 4)), (26, 26, 30))
for i, (k, h, im) in enumerate(tiles):
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    sheet.paste(bg.convert('RGB'), ((i % 4) * 200, (i // 4) * 200))
sheet.save(os.path.join(OUT, 'sheet.png'))
print('sheet ->', os.path.join(OUT, 'sheet.png'), sheet.size)
print('grid order:', ['%s %s' % (t[0], t[1][:6]) for t in tiles])
