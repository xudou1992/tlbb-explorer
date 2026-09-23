"""One-off: dump payload heads for sampled resources, by type (and by codec for textures)."""
import os, sqlite3, struct, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(HERE, 'out', 'all')
con = sqlite3.connect(os.path.join(HERE, 'resources.db'))

FIND = {}
for pak in sorted(os.listdir(ALL)):
    d = os.path.join(ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            FIND.setdefault(fn[:16], os.path.join(d, fn))


def hd(b, base=0):
    out = []
    for i in range(0, len(b), 16):
        ch = b[i:i + 16]
        out.append('    +%04x %s |%s|' % (base + i, ' '.join('%02x' % x for x in ch).ljust(47),
                                          ''.join(chr(x) if 32 <= x < 127 else '.' for x in ch)))
    return '\n'.join(out)


def dump(h, size=192, label=''):
    p = FIND.get(h)
    if not p:
        print('    %s [no payload on disk] %s' % (h, label))
        return None
    with open(p, 'rb') as f:
        b = f.read(size)
    print('  == %s size=%d  %s' % (h, os.path.getsize(p), label))
    print(hd(b))
    print('     u32:', [struct.unpack_from('<I', b, o)[0] for o in range(0, min(len(b), 96), 4)])
    return b, os.path.getsize(p)


def pick(rs, k=3):
    """spread across the size distribution"""
    rs = sorted(rs, key=lambda r: -(r[7] or 0))
    if len(rs) <= k:
        return rs
    return [rs[0], rs[len(rs) // 3], rs[2 * len(rs) // 3], rs[-1]][:k + 1]


def main():
    types = sys.argv[1:]
    q = ('select hash,path,type,codec,width,height,mips,stored,original '
         'from resources where type in (%s)' % ','.join('?' * len(types)))
    by = collections.defaultdict(list)
    for r in con.execute(q, types):
        by[(r[2], r[3] if r[2] == 'texture' else '')].append(r)
    for k in sorted(by, key=lambda x: -len(by[x])):
        print('\n########## type=%s codec=%s uniq=%d ##########' % (k[0], k[1], len(by[k])))
        for r in pick(by[k], 2):
            dump(r[0], label='path=%s  %sx%s mips=%s orig=%s' % (r[1], r[4], r[5], r[6], r[8]))


main()
