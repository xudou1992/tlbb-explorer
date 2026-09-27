# -*- coding: utf-8 -*-
"""sfl_join.py — READ-ONLY join of binary records with plaintext property curves.

Strategy for payload widths: classes {1,3,16}->1w, {6}->3w, {7,8}->4w are fixed.
Other (cls,fld) widths are learned by "unique extension" iteration: at each
unresolved position, try width 1..8 and require the *rest of the region* to tile
completely with currently known widths; accept only when exactly one width works.
Region brackets are byte-exact (chunk77 W words / chunk76 L76-5 words), so a
wrong width almost always breaks the tail.
"""
import struct, glob, os, re, collections, json

FILES = sorted(glob.glob(os.path.join(r'D:\TLGL\.scratch\out\tree\mobile_maps', '*', '*.sfl')))
FIXED = {1: 1, 3: 1, 6: 3, 7: 4, 8: 4, 16: 1}

def r8(n):
    return n if n % 8 == 0 else n + 8 - (n % 8)

def f32(w):
    return struct.unpack('<f', struct.pack('<I', w & 0xFFFFFFFF))[0]

def sdecode(b):
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin1', 'replace')

def load(f):
    raw = open(f, 'rb').read()
    a = struct.unpack_from('<6I', raw, 0)
    so = r8(a[5]) + 24
    sid, ssize, flag, cnt = struct.unpack_from('<4I', raw, so)
    strs, p = [], so + 16 + 8 * cnt
    for i in range(cnt):
        ln, hv = struct.unpack_from('<2I', raw, so + 16 + 8 * i)
        strs.append((sdecode(raw[p:p + ln]), hv))
        p += ln
    t39, n, W = struct.unpack_from('<3I', raw, 44)
    p76 = 64 + 4 * W
    h76 = struct.unpack_from('<5I', raw, p76)
    p40 = p76 + 20 + 4 * h76[4]
    h40 = struct.unpack_from('<5I', raw, p40) if p40 + 20 <= so else None
    return raw, so, strs, (t39, n, W), h76, h40

REGIONS = {}   # name -> (start, nwords)
def regions_of(raw, so, hdr77, h76, h40):
    W = hdr77[2]
    return [('77', 64, W), ('76', 64 + 4 * W + 40, h76[4] - 5)]

def tile_with(words, size_map):
    """words: tuple of ints; returns list (i,cls,fld,pw) or None."""
    out, i, N = [], 0, len(words)
    while i < N:
        k = words[i]
        cls, fld = k >> 16, k & 0xFFFF
        pw = size_map.get((cls, fld), FIXED.get(cls))
        if pw is None or i + 1 + pw > N:
            return None
        out.append((i, cls, fld, pw))
        i += 1 + pw
    return out if i == N else None

def learn_all(size_map):
    """iterate: load all regions, for each unresolvable pos find unique width."""
    new = 1
    regions = []
    for f in FILES:
        try:
            raw, so, strs, hdr77, h76, h40 = load(f)
        except Exception:
            continue
        for name, start, nwords in regions_of(raw, so, hdr77, h76, h40):
            if nwords <= 0:
                continue
            regions.append((f, name, struct.unpack_from('<%dI' % nwords, raw, start)))
    while new:
        new = 0
        for f, name, words in regions:
            i = 0
            while i < len(words):
                k = words[i]
                cls, fld = k >> 16, k & 0xFFFF
                pw = size_map.get((cls, fld), FIXED.get(cls))
                if pw is None:
                    sols = []
                    for cand in range(1, 9):
                        if i + 1 + cand > len(words):
                            break
                        sm = dict(size_map)
                        sm[(cls, fld)] = cand
                        if tile_with(words[i + 1 + cand:], sm) is not None:
                            sols.append(cand)
                    if len(sols) == 1:
                        size_map[(cls, fld)] = sols[0]
                        new += 1
                    elif len(sols) > 1:
                        break  # ambiguous here; retry next iteration after more learnings
                    else:
                        break  # dead end: stop this region
                    i += 1 + sols[0]
                    continue
                i += 1 + pw
    return size_map, regions

if __name__ == '__main__':
    size_map = {}
    size_map, regions = learn_all(size_map)
    print('learned widths:', sorted((k, v) for k, v in size_map.items()))
    # final full-coverage check
    fail = []
    per_file_recs = {}
    for f, name, words in regions:
        r = tile_with(words, size_map)
        if r is None:
            fail.append((f, name))
        else:
            per_file_recs.setdefault(f, {})[name] = (words, r)
    print('regions=%d fail=%d' % (len(regions), len(fail)))
    for x in fail[:12]:
        print('  FAIL', x)
    json.dump({'widths': {'%d,%d' % k: v for k, v in size_map.items()}},
              open('sfl_widths.json', 'w'))
