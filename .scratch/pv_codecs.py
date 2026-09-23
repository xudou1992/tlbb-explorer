"""One-off: identify the COLR / ALI8 / COLW bodies and the 8bpp block flavour."""
import os, sqlite3, struct, collections, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pv_jmt1 import FIND, parse, dds_chain, SUB_BC1

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))


def hd(b, n=64):
    return '\n'.join('    +%04x %s |%s|' % (i, ' '.join('%02x' % x for x in b[i:i + 16]).ljust(47),
                                            ''.join(chr(x) if 32 <= x < 127 else '.' for x in b[i:i + 16]))
                     for i in range(0, min(n, len(b)), 16))


q = """select hash, props from resources where type='texture'"""
want = {'COLR': [], 'ALI8': [], 'COLW': [], 'DXT1': []}
for h, pr in con.execute(q):
    for k in want:
        if pr and '"declared_codec": "%s"' % k in pr and len(want[k]) < 3:
            want[k].append(h)

for k in ('COLR', 'ALI8', 'COLW'):
    print('=========== %s ===========' % k)
    for h in want[k]:
        j = parse(FIND[h])
        b0 = ((j['w'] + 3) // 4) * ((j['h'] + 3) // 4)
        print('  %s %dx%d m=%s l0=%d size=%d blob=%d | b0*16=%d b0*8=%d w*h=%d w*h*4=%d'
              % (h, j['w'], j['h'], j['mips'], j['l0'], j['size'], j['blob'], b0 * 16, b0 * 8,
                 j['w'] * j['h'], j['w'] * j['h'] * 4))
        print(hd(j['raw'][24:24 + 64]))
        if k == 'COLW':
            body = j['raw'][28:28 + j['l0']]
            print('     RIFF?' , body[:4], body[8:12], 'rifflen=', struct.unpack_from('<I', body, 4)[0] + 8,
                  'l0=', j['l0'])
            p = 12
            while p + 8 <= len(body) and body[p - 4:p] != b'\x00\x00\x00\x00':
                cid, csz = body[p:p + 4], struct.unpack_from('<I', body, p + 4)[0]
                print('       chunk %-6r size=%-8d fourcc-payload=%r' % (cid, csz, body[p + 8:p + 12]))
                p += 8 + csz + (csz & 1)

print('\n=========== 8bpp class: BC3 vs DXT3 discriminator ===========')
n = bc3sig = dxt3sig = unk = 0
aa = 0
for h in want['DXT1'][:1] + [x[0] for x in list(con.execute(
        "select hash from resources where type='texture' and codec='BC3' limit 60"))]:
    p = FIND.get(h)
    if not p:
        continue
    j = parse(p)
    if j['sub'] == SUB_BC1 or j['codec'] != 'DXT1':
        continue
    for i in range(0, min(40000, j['l0']), 16):
        b = j['raw'][28 + i:28 + i + 16]
        if len(b) < 16:
            break
        n += 1
        if b[2:8] == b'\xaa' * 6 or b[2:8] == b'\x00' * 6 or b[2:8] == b'\xff' * 6:
            bc3sig += 1                       # constant-alpha selector runs
        if b[0] > b[1]:
            pass
        if int.from_bytes(b[0:4], 'little') & 0x11111111 == 0x11111111:
            dxt3sig += 1
print('  blocks sampled %d, constant-alpha-selector blocks %d (%.1f%%)' %
      (n, bc3sig, 100.0 * bc3sig / max(1, n)))
