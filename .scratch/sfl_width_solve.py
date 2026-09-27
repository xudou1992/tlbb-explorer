# -*- coding: utf-8 -*-
"""sfl_width_solve.py — READ-ONLY constraint solver for .sfl record widths.

For each bracketed region (chunk77 run, chunk76 run) the exact word span is
known, so record widths must tile it perfectly. Unknown (cls,fld) start with
candidate set {1..8}; every region prunes candidates that admit NO complete
tiling (forward-reachable set F x backward-reachable set B). Fixed point =>
either a unique width per field or an honest ambiguity report.
"""
import struct, glob, os, collections

FILES = sorted(glob.glob(os.path.join(r'D:\TLGL\.scratch\out\tree\mobile_maps', '*', '*.sfl')))
FIXED = {1: 1, 3: 1, 6: 3, 7: 4, 8: 4, 16: 1}

def r8(n):
    return n if n % 8 == 0 else n + 8 - (n % 8)

def load(f):
    raw = open(f, 'rb').read()
    a = struct.unpack_from('<6I', raw, 0)
    so = r8(a[5]) + 24
    sid, ssize, flag, cnt = struct.unpack_from('<4I', raw, so)
    strs, p = [], so + 16 + 8 * cnt
    for i in range(cnt):
        ln, hv = struct.unpack_from('<2I', raw, so + 16 + 8 * i)
        b = raw[p:p + ln]
        try:
            s = b.decode('utf-8')
        except UnicodeDecodeError:
            try:
                s = b.decode('gbk')
            except UnicodeDecodeError:
                s = b.decode('latin1', 'replace')
        strs.append((s, hv))
        p += ln
    t39, n, W = struct.unpack_from('<3I', raw, 44)
    p76 = 64 + 4 * W
    h76 = struct.unpack_from('<5I', raw, p76)
    p40 = p76 + 20 + 4 * h76[4]
    h40 = struct.unpack_from('<5I', raw, p40) if p40 + 20 <= so else None
    return raw, so, strs, (t39, n, W), h76, h40

def region_edges(words, S):
    """edges (c,f,w) that appear on some complete tiling of the region"""
    N = len(words)
    def widths(i):
        k = words[i]
        c, f = k >> 16, k & 0xFFFF
        return ([FIXED[c]] if c in FIXED else sorted(S.get((c, f), ())), c, f)
    F = {0}
    for i in range(N):
        if i in F:
            ws, c, f = widths(i)
            for w in ws:
                if i + 1 + w <= N:
                    F.add(i + 1 + w)
    B = {N}
    for i in range(N - 1, -1, -1):
        ws, c, f = widths(i)
        for w in ws:
            if i + 1 + w in B:
                B.add(i)
                break
    edges = set()
    for i in sorted(F & B):
        if i >= N:
            continue
        ws, c, f = widths(i)
        for w in ws:
            if i + 1 + w in B:
                edges.add((c, f, w))
    return edges

if __name__ == '__main__':
    regions = []
    for f in FILES:
        raw, so, strs, h77, h76, h40 = load(f)
        for name, start, nwords in (('77', 64, h77[2]), ('76', 64 + 4 * h77[2] + 40, h76[4] - 5)):
            if nwords <= 0:
                continue
            regions.append((f, name, struct.unpack_from('<%dI' % nwords, raw, start)))
    S = {}
    for _, _, words in regions:
        for k in words:
            c, f = k >> 16, k & 0xFFFF
            if c not in FIXED:
                S.setdefault((c, f), set(range(1, 9)))
    changed = True
    rounds = 0
    while changed and rounds < 40:
        changed = False
        rounds += 1
        for f, name, words in regions:
            allowed = collections.defaultdict(set)
            for c, f2, w in region_edges(words, S):
                allowed[(c, f2)].add(w)
            present = set()
            for k in words:
                key = (k >> 16, k & 0xFFFF)
                if key[0] not in FIXED:
                    present.add(key)
            for key in present:
                new = S[key] & allowed.get(key, set())
                if not new:
                    print('CONTRADICTION', key, f, name)
                    continue
                if new != S[key]:
                    S[key] = new
                    changed = True
    print('rounds', rounds)
    for k in sorted(S):
        print('  cls=%2d fld=%-4d candidates %s' % (k[0], k[1], sorted(S[k])))
    unresolved = 0
    for f, name, words in regions:
        i = 0
        while i < len(words):
            k = words[i]
            c, fl = k >> 16, k & 0xFFFF
            ws = [FIXED[c]] if c in FIXED else sorted(S.get((c, fl), ()))
            if len(ws) != 1 or i + 1 + ws[0] > len(words):
                unresolved += 1
                break
            i += 1 + ws[0]
    print('regions:', len(regions), 'unresolved:', unresolved)
