# -*- coding: utf-8 -*-
"""sfl_probe.py — READ-ONLY field census over all 297 .sfl (JBCF) files.

Container grammar (same as crates/core/src/jbcf/parser.rs):
  [0]'JBCF' [4]0 [8]8 [12]bodyLen=size-16  [16] root: id=86, size_words@20
  strtab (id=85 chunk) at r8(size_words)+24.
Interior (recovered by this probe, validated byte-exact on 297/297):
  [24]  chunk77 hdr [77,0,0,3,L] ; payload@44 subhead [39,n,W,0,0];
        n records tile exactly W words from 64.
  then  chunk76 [76,0,0,4,L76] @ 64+4W ; its payload: subhead (5 words) then a
        record stream that tiles [subhead_end, end76).
  then  chunk40 [40,0,0,z,L40] ; blob payload; end == strtab offset.
  record = [u32 key=(cls<<16)|fld][payload words];
  class fixed sizes: 1/3/16 -> 1 word, 6 -> 3, 7/8 -> 4;
  other (cls,fld) sizes learned from the exact brackets by backtracking.
"""
import struct, glob, collections, json, os, random, sys

TREE = r'D:\TLGL\.scratch\out\tree'
FILES = sorted(glob.glob(os.path.join(TREE, 'mobile_maps', '*', '*.sfl')))
FIXED = {1: 1, 3: 1, 6: 3, 7: 4, 8: 4, 16: 1}

def r8(n):
    return n if n % 8 == 0 else n + 8 - (n % 8)

def sdecode(b):
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin1', 'replace')

def f32(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]

def open_sfl(raw):
    a = struct.unpack_from('<6I', raw, 0)
    if a[0] != 0x4643424A or a[3] + 16 != len(raw) or a[4] != 86:
        raise ValueError('not jbcf/root')
    return a, r8(a[5]) + 24

def read_strtab(raw, off):
    sid, size, flag, cnt = struct.unpack_from('<4I', raw, off)
    if sid != 85:
        raise ValueError('strtab id %d' % sid)
    pairs = struct.unpack_from('<%dI' % (2 * cnt), raw, off + 16) if cnt else ()
    out, p = [], off + 16 + 8 * cnt
    for i in range(cnt):
        ln, hv = pairs[2 * i], pairs[2 * i + 1]
        out.append((sdecode(raw[p:p + ln]), hv))
        p += ln
    return flag, out

def tile(start, nwords, raw, size_map, keys_ok):
    """Exact tiling of [start, start+4*nwords) into records; returns list or None."""
    end = start + 4 * nwords
    out, pos = [], start
    while pos < end:
        k = struct.unpack_from('<I', raw, pos)[0]
        cls, fld = k >> 16, k & 0xFFFF
        if not keys_ok(cls, fld):
            return None
        pw = size_map.get((cls, fld), FIXED.get(cls))
        if pw is None or pos + 4 + 4 * pw > end:
            return None
        out.append((pos, cls, fld, pw, struct.unpack_from('<%dI' % pw, raw, pos + 4)))
        pos += 4 + 4 * pw
    return out if pos == end else None

def tile_learn(start, nwords, raw, size_map, keys_ok, learned):
    """Like tile() but learns unknown (cls,fld) sizes; consistent with FIXED."""
    res = tile(start, nwords, raw, size_map, keys_ok)
    if res is not None:
        return res
    pos = start
    end = start + 4 * nwords
    while pos < end:
        k = struct.unpack_from('<I', raw, pos)[0]
        cls, fld = k >> 16, k & 0xFFFF
        if not keys_ok(cls, fld):
            return None
        pw = size_map.get((cls, fld), FIXED.get(cls))
        if pw is not None:
            pos += 4 + 4 * pw
            continue
        for cand in range(1, 10):
            if pos + 4 + 4 * cand > end:
                break
            size_map[(cls, fld)] = cand
            rest = tile_learn(pos + 4 + 4 * cand, nwords - (pos - start) // 4 - 1 - cand,
                              raw, size_map, keys_ok, learned)
            del size_map[(cls, fld)]
            if rest is not None:
                learned[(cls, fld)] = cand
                return [(pos, cls, fld, cand, struct.unpack_from('<%dI' % cand, raw, pos + 4))] + rest
        return None
    return None

def keys_ok(cls, fld):
    return cls <= 31 and fld < 0x800

def parse(path):
    raw = open(path, 'rb').read()
    a, so = open_sfl(raw)
    flag, strs = read_strtab(raw, so)
    hdr77 = struct.unpack_from('<5I', raw, 24)
    t39, n, W, z1, z2 = struct.unpack_from('<5I', raw, 44)
    size_map = {}
    learned = {}
    recs77 = tile_learn(64, W, raw, size_map, keys_ok, learned)
    assert recs77 is not None, path
    p76 = 64 + 4 * W
    hdr76 = struct.unpack_from('<5I', raw, p76)
    sub76 = struct.unpack_from('<5I', raw, p76 + 20)
    start76 = p76 + 40
    recs76 = tile_learn(start76, hdr76[4] - 5, raw, size_map, keys_ok, learned)
    p40 = p76 + 20 + 4 * hdr76[4]
    hdr40 = struct.unpack_from('<5I', raw, p40) if p40 + 20 <= so else None
    if recs76 is None:
        blob76 = struct.unpack_from('<%dI' % (hdr76[4] - 5), raw, start76)
        recs76 = None
    else:
        blob76 = None
    blob40 = None
    if hdr40:
        blob40 = struct.unpack_from('<%dI' % hdr40[4], raw, p40 + 20)
    return dict(path=path, raw=raw, a=a, strtab=so, flag=flag, strings=strs,
                hdr77=hdr77, sub77=(t39, n, W, z1, z2), recs77=recs77,
                hdr76=hdr76, sub76=sub76, recs76=recs76, blob76=blob76,
                p40=p40, hdr40=hdr40, blob40=blob40, learned=learned,
                size_map=dict(size_map))

if __name__ == '__main__':
    recs_by_field = collections.defaultdict(collections.Counter)
    all_learned = collections.defaultdict(collections.Counter)
    bad = []
    parsed = []
    for f in FILES:
        try:
            d = parse(f)
        except Exception as e:
            bad.append((f, repr(e)))
            continue
        parsed.append(d)
        for off, cls, fld, pw, pl in (d['recs77'] or []):
            recs_by_field[('77', cls, fld)][pw] += 1
        for off, cls, fld, pw, pl in (d['recs76'] or []):
            recs_by_field[('76', cls, fld)][pw] += 1
        for k, v in d['learned'].items():
            all_learned[k][v] += 1
    print('parsed %d/%d, bad=%d' % (len(parsed), len(FILES), len(bad)))
    for b in bad[:10]:
        print(' BAD', b)
    print('\nlearned sizes (ambiguous sizes = bracket underdetermination):')
    for k in sorted(all_learned):
        print('  cls=%d fld=%d -> %s' % (k[0], k[1], dict(all_learned[k])))
    print('\nfield inventory (section,cls,fld -> payload words: files):')
    for k in sorted(recs_by_field):
        print('  sec=%s cls=%2d fld=%3d sizes=%s' % (k[0], k[1], k[2], dict(recs_by_field[k])))
    print('\nsubheads77:', collections.Counter(d['sub77'][:1] + d['sub77'][3:] for d in parsed).most_common())
    print('n recs sec77:', collections.Counter(len(d['recs77']) for d in parsed).most_common())
    print('hdr77 (x,y,z):', collections.Counter(d['hdr77'][1:4] for d in parsed).most_common())
    print('hdr76 (x,y,z):', collections.Counter(d['hdr76'][1:4] for d in parsed).most_common())
    print('sub76:', collections.Counter(d['sub76'] for d in parsed).most_common(8))
    print('hdr40 (id,x,y,z,len):', collections.Counter(d['hdr40'] for d in parsed).most_common(12))
    print('blob40 len(words) hist:', collections.Counter(len(d['blob40'] or ()) for d in parsed).most_common(15))
    print('recs76 None:', sum(1 for d in parsed if d['recs76'] is None))
    print('strtab flag:', collections.Counter(d['flag'] for d in parsed).most_common())
    print('strtab count hist:', collections.Counter(len(d['strings']) for d in parsed).most_common())
    json.dump([{k: v for k, v in d.items() if k in
                ('path', 'strtab', 'flag', 'hdr77', 'sub77', 'hdr76', 'sub76', 'p40', 'hdr40')}
               | {'strings': [[s, h] for s, h in d['strings']],
                  'recs77': [[o, c, f, p, list(v)] for o, c, f, p, v in (d['recs77'] or [])],
                  'recs76': [[o, c, f, p, list(v)] for o, c, f, p, v in (d['recs76'] or [])] if d['recs76'] is not None else None,
                  'blob76': list(d['blob76'] or ()),
                  'blob40': list(d['blob40'] or ())}
               for d in parsed],
              open(os.path.join(r'D:\TLGL\.scratch', 'sfl_dump.json'), 'w', encoding='utf-8'))
    print('wrote sfl_dump.json')
