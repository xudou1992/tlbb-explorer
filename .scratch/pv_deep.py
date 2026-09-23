"""One-off: mesh vertex/index stride test, JBCF record grammar, text encoding census."""
import os, sys, sqlite3, struct, collections, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))

print('======== mesh: does size == 140 + H + V*36 + I*2 ? ========')
res = collections.Counter()
for h, in con.execute("select hash from resources where type='mesh' limit 3000"):
    p = FIND.get(h)
    if not p:
        continue
    b = open(p, 'rb').read()
    V, I, a, c = struct.unpack_from('<4I', b, 140)
    if not (0 < V < 400000 and 0 <= I < 800000):
        res['implausible counts'] += 1
        continue
    for stride in (32, 36, 40, 44, 48, 64):
        for isz in (2, 4):
            rem = len(b) - 140 - V * stride - I * isz
            if 0 <= rem <= 4096:
                res['V*%d + I*%d + tail %d' % (stride, isz, rem if rem < 300 else 300)] += 1
                res['fit stride=%d isz=%d' % (stride, isz)] += 1
    res['n'] += 1
for k, v in res.most_common(14):
    print('   %-32s %6d' % (k, v))

print('\n======== ani: chunk magic + keyframe-ish fields ========')
c = collections.Counter()
for h, in con.execute("select hash from resources where type='ani' limit 2000"):
    p = FIND.get(h)
    if not p:
        continue
    b = open(p, 'rb').read()
    c['4cc@140=' + b[140:144].decode('latin1')] += 1
    v148, v152, v156 = struct.unpack_from('<3I', b, 148)
    c['u32@148=%d' % v148] += 1
    c['u32@152=%d' % v152] += 1
    c['has-bip01'] += b'bip01' in b or b'Bip01' in b
    c['has-armature/DB-keys'] += (b'armature' in b or b'textureAtlas' in b or b'dragonBones' in b)
    c['n'] += 1
for k, v in c.most_common(12):
    print('   %-24s %6d/%d' % (k, v, c['n']))

print('\n======== JBCF record grammar ========')
ids = collections.Counter()
c2 = collections.Counter()
for h, in con.execute("select hash from resources where type='JBCF' limit 1500"):
    p = FIND.get(h)
    if not p:
        continue
    b = open(p, 'rb').read()
    a = struct.unpack_from('<8I', b, 0)
    c2['u32@8==8'] += a[2] == 8
    c2['u32@12==size-16'] += a[3] == len(b) - 16
    c2['u32@16==86'] += a[4] == 86
    c2['u32@20 < size'] += a[5] < len(b)
    c2['u32@24 in 80..170'] += 80 <= a[6] <= 170
    c2['u32@28 in 0..2'] += a[7] <= 2
    for m in re.finditer(rb'[\x01-\xff]\x00[\x00-\x08]\x00', b[24:24 + 400]):
        pass
    for off in range(24, min(len(b) - 4, 400), 2):
        v = struct.unpack_from('<H', b, off)[0]
        if 0xb0 <= v <= 0xc8:
            ids[v] += 1
    c2['n'] += 1
for k, v in c2.most_common():
    print('   %-22s %5d/%d' % (k, v, c2['n']))
print('   frequent u16 field-ids in the first 400B:', ids.most_common(14))

print('\n======== text / xml / table / set encoding ========')
for typ in ('text', 'xml', 'table', 'JBCF', 'GATA', 'JBPU', 'scene', 'set', 'mesh', 'ani'):
    enc = collections.Counter()
    for h, in con.execute("select hash from resources where type=? limit 250", (typ,)):
        p = FIND.get(h)
        if not p:
            continue
        b = open(p, 'rb').read(16384)
        if not b:
            enc['empty'] += 1
            continue
        ctrl = sum(1 for x in b if x < 32 and x not in (9, 10, 13))
        if ctrl > len(b) * 0.02:
            enc['binary'] += 1
            continue
        if all(x < 128 for x in b):
            enc['ascii'] += 1
        else:
            try:
                b.decode('utf-8')
                enc['utf8'] += 1
            except Exception:
                try:
                    b.decode('gbk')
                    enc['gbk'] += 1
                except Exception:
                    enc['8bit-unknown'] += 1
        enc['CRLF' if b'\r\n' in b else ('LF' if b'\n' in b else 'no-eol')] += 1
    print('   %-6s %s' % (typ, dict(enc)))
