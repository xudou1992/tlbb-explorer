"""pu_dbg.py — 用冻结表走一份文件,打印记录流,标出挂点上下文。"""
import os
import struct
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
TABLE = {'%d,%d' % tuple(map(int, k.split(','))): v
         for k, v in json.load(open(os.path.join(HERE, 'pu_pw_table.json'))).items()}
TABLE = {tuple(map(int, k.split(','))): v for k, v in TABLE.items()}


def load_words(path):
    raw = open(os.path.join(ROOT, path), 'rb').read()
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    p = pool
    names = []
    for ln, _ in pairs:
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    words = struct.unpack_from('<%dI' % n, raw, start)
    return names, words, start


def f32(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]


def main():
    path = sys.argv[1]
    names, words, start = load_words(path)
    print('file %s  %d words  %d strings' % (path, len(words), len(names)))
    p = 0
    while p < len(words):
        w = words[p]
        cls, fld = w >> 16, w & 0xffff
        pw = TABLE.get((cls, fld))
        if pw is None or cls > MAXCLS:
            print('STOP @ word %d (byte %d): key=(%d,%d) pw=%s  后续8词: %s'
                  % (p, start + p * 4, cls, fld, pw,
                     ' '.join('%08x' % x for x in words[p:p + 8])))
            print('   f32 口径: %s' % ['%.6g' % f32(x) for x in words[p:p + 8]])
            # 上下文
            print('   前8词: %s' % ' '.join('%08x' % x for x in words[max(0, p - 8):p]))
            break
        payload = words[p + 1:p + 1 + pw]
        fs = ['%.6g' % f32(x) for x in payload]
        print('w%04d key=(%3d,%3d) pw=%d  int=%s  f32=%s'
              % (p, cls, fld, pw,
                 [str(x) for x in payload][:8], fs[:8]))
        p += 1 + pw
    else:
        print('WALK OK to end, %d records' % 0)


if __name__ == '__main__':
    main()
