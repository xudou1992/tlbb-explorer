"""One-off: (a) COLR = border-padded BGRA?  (b) DragonBones vs custom evidence for
ani/mesh/geom/set, (c) JBCF record grammar, (d) text encodings."""
import os, sys, io, sqlite3, struct, collections, re, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND, parse, OUT
from PIL import Image

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
RUN = re.compile(rb'[\x20-\x7e]{4,}')

print('======== (a) COLR geometry test ========')
ok = bad = 0
for h, in con.execute("select hash from resources where type='texture'"):
    p = FIND.get(h)
    if not p:
        continue
    j = parse(p)
    if j['codec'] != 'COLR':
        continue
    pad = ((j['w'] + 2) * (j['h'] + 2) * 4 == j['l0'])
    ok += pad
    bad += not pad
print('   COLR l0 == (w+2)*(h+2)*4 :  %d yes / %d no' % (ok, bad))
for h, in con.execute("select hash from resources where type='texture' limit 4000"):
    p = FIND.get(h)
    if not p:
        continue
    j = parse(p)
    if j['codec'] != 'COLR':
        continue
    W = j['w'] + 2
    px = bytearray(j['w'] * j['h'] * 4)
    src = j['raw'][28:]
    for y in range(j['h']):
        for x in range(j['w']):
            s = ((y + 1) * W + x + 1) * 4
            px[(y * j['w'] + x) * 4:(y * j['w'] + x) * 4 + 4] = src[s:s + 4]
    im = Image.frombytes('RGBA', (j['w'], j['h']), bytes(px))
    im.thumbnail((256, 256))
    bg = Image.new('RGBA', im.size, (255, 0, 255, 255))
    bg.alpha_composite(im)
    bg.convert('RGB').save(os.path.join(OUT, 'COLR_%s.png' % h))
    print('   COLR %s %sx%s -> COLR_%s.png' % (h, j['w'], j['h'], h))
    break

print('\n======== (b) DragonBones / bone-name evidence ========')
pats = [b'dragonBones', b'DragonBones', b'armature', b'Armature', b'textureAtlas',
        b'slot', b'Bone', b'bone', b'Bip01', b'pelvis', b'spine', b'frame', b'keyframe',
        b'tween', b'.mesh', b'.ani', b'.mtl', b'.ske', b'.tga']
for typ, n in (('ani', 120), ('mesh', 120), ('geom', 60), ('set', 30)):
    hits = collections.Counter()
    sizes = []
    strs = collections.Counter()
    for h, in con.execute("select hash from resources where type=? limit ?", (typ, n)):
        p = FIND.get(h)
        if not p:
            continue
        b = open(p, 'rb').read()
        sizes.append(len(b))
        for q in pats:
            if q in b:
                hits[q.decode()] += 1
        for r in RUN.findall(b[:1 << 20])[:40]:
            strs[r[:24]] += 1
    print('   %-6s n=%d  avg=%d  magic-hits=%s' % (typ, len(sizes),
                                                   sum(sizes) // max(1, len(sizes)),
                                                   dict(hits.most_common(8))))
    print('        top strings: %s' % [s.decode('latin1') for s, _ in strs.most_common(8)])

print('\n======== (b2) header field map for banner types ========')
for typ in ('ani', 'mesh', 'set'):
    hs = [r[0] for r in con.execute("select hash from resources where type=? limit 400", (typ,))]
    f = collections.defaultdict(collections.Counter)
    for h in hs:
        p = FIND.get(h)
        if not p:
            continue
        b = open(p, 'rb').read()
        for off in (64, 72, 76, 80, 128, 132, 136, 140, 144, 148, 152, 156, 160):
            v = struct.unpack_from('<I', b, off)[0]
            f[off]['u32=%d' % v] += 1
            f[off]['4cc=%s' % b[off:off + 4].decode('latin1') if all(32 <= c < 127 for c in b[off:off + 4]) else ''] += 0
        f['size-vs-140'][round((len(b) - 140) / 4)] += 0
    print('   --- %s' % typ)
    for off in sorted(k for k in f if isinstance(k, int)):
        print('      +%-4d %s' % (off, f[off].most_common(4)))

print('\n======== (c) JBCF record grammar ========')
for h, path in list(con.execute("select hash,path from resources where type='JBCF' limit 6")):
    b = open(FIND[h], 'rb').read()
    n, sz, v = struct.unpack_from('<III', b, 20)
    print('   %s size=%d  u32@8=%d u32@12=%d(=size-16?) u32@16=%d(86) u32@20=%d u32@24=%d'
          % ((path or h)[:44], len(b), struct.unpack_from('<I', b, 8)[0],
             struct.unpack_from('<I', b, 12)[0], n, sz, v))
    print('      bytes[24:64]=%s' % b[24:64].hex(' '))
    # try: records of [u16 id][u16 type][payload]
    p, cnt = 24 + sz, 0
    print('      after body @%d: %s' % (p, b[p:p + 32].hex(' ')))

print('\n======== (d) text / xml / table encodings ========')
for typ in ('text', 'xml', 'table'):
    seen = collections.Counter()
    ex = []
    for h, path in con.execute("select hash,path from resources where type=? limit 400", (typ,)):
        p = FIND.get(h)
        if not p:
            continue
        b = open(p, 'rb').read(8192)
        enc = 'ascii'
        if any(c >= 128 for c in b):
            try:
                b.decode('utf-8')
                enc = 'utf-8'
            except Exception:
                try:
                    b.decode('gbk')
                    enc = 'gbk'
                except Exception:
                    enc = 'binary'
        eol = 'CRLF' if b'\r\n' in b else ('LF' if b'\n' in b else 'none')
        seen['%s/%s' % (enc, eol)] += 1
        if len(ex) < 2 and enc != 'binary':
            ex.append((path or h, b[:110]))
    print('   %-6s %s' % (typ, seen.most_common(5)))
    for p, s in ex:
        print('      %s | %s' % (os.path.basename(p), s.decode('latin1').replace('\r', '\\r').replace('\n', '\\n')[:100]))
