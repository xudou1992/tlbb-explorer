"""pu_twin.py — 孪生 .pu 差分:同 key 序列对齐,列出载荷不同的记录。

用法: python pu_twin.py rel1.pu rel2.pu [...]
"""
import os
import struct
import json
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
HARD = {0: 0, 7: 3}
TABLE = {tuple(int(x) for x in k.split(',')): v
         for k, v in json.load(open(os.path.join(HERE, 'pu_pw_table.json'))).items()}


def load(path):
    raw = open(os.path.join(ROOT, path), 'rb').read()
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pool = 8 + 8 * cnt
    p = pool
    names = []
    for i in range(0, 2 * cnt, 2):
        ln = tab[i]
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    words = struct.unpack_from('<%dI' % n, raw, start)

    def f32(w):
        return struct.unpack('<f', struct.pack('<I', w))[0]
    recs = []
    q = 0
    while q < n:
        w = words[q]
        cls, fld = w >> 16, w & 0xffff
        pw = HARD[cls] if cls in HARD else TABLE[(cls, fld)]
        pay = words[q + 1:q + 1 + pw]
        recs.append((q, cls, fld, pw, pay))
        q += 1 + pw
    return names, words, recs, f32


def fmt(pay, f32):
    fs = ['%.6g' % f32(x) for x in pay]
    ints = [str(x) for x in pay]
    return 'int[%s] f32[%s]' % (','.join(ints), ','.join(fs))


def main():
    paths = sys.argv[1:]
    data = [load(p) for p in paths]
    base = data[0]
    print('base: %s (%d strings, %d records)' % (paths[0], len(base[0]), len(base[2])))
    print('strings:', [n.decode('gbk', 'replace') for n in base[0]])
    for other in data[1:]:
        print('\n===== vs %s (%d strings, %d records)' % (other[0], len(other[0]) if 0 else 0, len(other[2])))
        print('    strings:', [n.decode('gbk', 'replace') for n in other[0]])
        b, o = base[2], other[2]
        i = j = 0
        nd = 0
        nresync = 0
        while i < len(b) and j < len(o):
            kb = (b[i][1], b[i][2])
            ko = (o[j][1], o[j][2])
            if kb != ko:
                # 重同步:小窗口内找下一对相同 key
                hit = None
                for d in range(1, 12):
                    if i + d < len(b) and j < len(o) and (b[i + d][1], b[i + d][2]) == ko:
                        hit = ('base-skip', d)
                        break
                    if j + d < len(o) and i < len(b) and (o[j + d][1], o[j + d][2]) == kb:
                        hit = ('other-skip', d)
                        break
                if hit:
                    nresync += 1
                    kind, d = hit
                    if kind == 'base-skip':
                        i += d
                    else:
                        j += d
                    continue
                print('  KEY MISMATCH @rec%d: base%s vs other%s (no resync)' % (i, kb, ko))
                break
            if b[i][3] != o[j][3]:
                print('  PW MISMATCH key%s: %d vs %d' % (kb, b[i][3], o[j][3]))
                break
            if b[i][4] != o[j][4]:
                nd += 1
                print('  rec%04d key(%3d,%3d) pw=%d' % (i, kb[0], kb[1], b[i][3]))
                print('     A %s' % fmt(b[i][4], base[3]))
                print('     B %s' % fmt(o[j][4], other[3]))
            i += 1
            j += 1
        if i >= len(b) and j >= len(o):
            print('  %d differing records (of %d), %d resyncs; key sequences identical' % (nd, len(b), nresync))
        else:
            print('  stopped at rec%d/%d, %d diffs so far, %d resyncs' % (i, j, nd, nresync))


if __name__ == '__main__':
    main()
