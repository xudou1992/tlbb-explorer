# -*- coding: utf-8 -*-
"""sfl_fields.py — READ-ONLY master parser/census for all 297 .sfl files.

Layout grammar (validated on 297/297 here):
  JBCF header, root chunk id 86, strtab id 85 at r8(root_words)+24.
  root data [24,strtab): chunk [77,0,0,3,L]
    @44 subhead [39, n, W, 0, 0]; n records tile exactly W words @64;
    then sibling chunk [76,0,0,4,L76]
        @+20 subhead [4,1,2,0,0]; record stream; the stream stops before a
        nested 5-word chunk chain (e.g. empty chunks 6,8) that ends the payload;
    then sibling chunk [40,0,0,z,L40] whose payload is class-4 records.
  record key = (cls<<16)|fld; payload words: cls1/3/16=1, cls6=3, cls7/8=4,
  cls2=1, cls10=2, cls4: (4,5)=6,(4,38)=1,(4,57)=1,(4,63)=1,(4,64)=1,
  (4,94)=6,(4,111)=6 (others observed with width census below).
Output: sfl_fields.json (machine-readable census) + stdout summary tables.
"""
import struct, glob, os, re, collections, json, sys

TREE = r'D:\TLGL\.scratch\out\tree'
FILES = sorted(glob.glob(os.path.join(TREE, 'mobile_maps', '*', '*.sfl')))
FIXED = {1: 1, 2: 1, 3: 1, 6: 3, 7: 4, 8: 4, 10: 2, 16: 1}
VAR4 = {(4, 5): 6, (4, 38): 1, (4, 57): 1, (4, 63): 1, (4, 64): 1,
        (4, 158): 6, (4, 175): 6}
ALLOWED = set(FIXED) | {4}
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

def width(key):
    return VAR4.get(key, FIXED.get(key[0]))

def tile_stream(words, start=0, relaxed=False):
    """Greedy forward tiling; returns (recs, stop_index). recs=(i,cls,fld,pw)."""
    recs, i, N = [], start, len(words)
    while i < N:
        k = words[i]
        c, f = k >> 16, k & 0xFFFF
        if (c not in ALLOWED and not (relaxed and c == 0)) or (not relaxed and f >= 0x800):
            return recs, i
        if relaxed and c == 0 and i + 2 > N:
            return recs, i
        w = width((c, f)) if c != 0 else 1
        if w is None or i + 1 + w > N:
            return recs, i
        recs.append((i, c, f, w))
        i += 1 + w
    return recs, i

def parse_file(path):
    raw = open(path, 'rb').read()
    a = struct.unpack_from('<6I', raw, 0)
    if a[0] != 0x4643424A or a[3] + 16 != len(raw) or a[4] != 86:
        raise ValueError('hdr')
    so = r8(a[5]) + 24
    sid, ssize, flag, cnt = struct.unpack_from('<4I', raw, so)
    if sid != 85:
        raise ValueError('strtab')
    strs, p = [], so + 16 + 8 * cnt
    for i in range(cnt):
        ln, hv = struct.unpack_from('<2I', raw, so + 16 + 8 * i)
        strs.append((sdecode(raw[p:p + ln]), hv))
        p += ln
    h77 = struct.unpack_from('<5I', raw, 24)
    t39, n, W = struct.unpack_from('<3I', raw, 44)
    words77 = struct.unpack_from('<%dI' % W, raw, 64)
    recs77, stop77 = tile_stream(words77)
    ok77 = (stop77 == W and len(recs77) == n)
    p76 = 64 + 4 * W
    h76 = struct.unpack_from('<5I', raw, p76)
    sub76 = struct.unpack_from('<5I', raw, p76 + 20)
    words76 = struct.unpack_from('<%dI' % (h76[4] - 5), raw, p76 + 40)
    recs76, stop76 = tile_stream(words76)
    # the words after the record stream should be a chain of 5-word zero-len chunks
    tail_chunks = []
    rem = words76[stop76:]
    chain_ok = len(rem) % 5 == 0
    if chain_ok:
        for j in range(0, len(rem), 5):
            tail_chunks.append(tuple(rem[j:j + 5]))
        chain_ok = all(t[1] == 0 and t[2] == 0 and t[3] == 0 and t[4] == 0 for t in tail_chunks)
    p40 = p76 + 20 + 4 * h76[4]
    h40 = struct.unpack_from('<5I', raw, p40) if p40 + 20 <= so else None
    sub40 = struct.unpack_from('<5I', raw, p40 + 20) if h40 and h40[4] >= 5 else None
    words40 = recs40 = None
    if h40:
        if h40[4] > 5:
            words40 = struct.unpack_from('<%dI' % (h40[4] - 5), raw, p40 + 40)
            recs40, stop40 = tile_stream(words40)
        else:
            words40, recs40 = (), []
    # nested child chunks inside chunk76 tail: list their ids
    kids76 = []
    kq = stop76
    while kq + 5 <= len(words76):
        kid = tuple(words76[kq:kq + 5])
        kids76.append((kid[0], kid[3], kid[4], kq))
        kq += 5 + kid[4]
    return dict(path=path, size=len(raw), hdr=a, strtab=so, strflag=flag,
                strings=strs, h77=h77, n77=n, W77=W, ok77=ok77, recs77=recs77,
                words77=words77, p76=p76, h76=h76, sub76=sub76, recs76=recs76,
                words76=words76, stop76=stop76, tail76=tail_chunks,
                p40=p40, h40=h40, sub40=sub40, words40=words40, recs40=recs40,
                kids76=kids76, kids76_pos=[(k[:3], k[3]) for k in kids76],
                chain76_ok=chain_ok)

if __name__ == '__main__':
    docs = []
    fails = []
    for f in FILES:
        try:
            d = parse_file(f)
        except Exception as e:
            fails.append((f, repr(e)))
            continue
        docs.append(d)
    # decode child-8 rows (cloud-layer blocks) into d['rows8']
    for d in docs:
        rows = []
        for kid, koff in d['kids76_pos']:
            if kid[0] == 8 and kid[2] > 0:
                w = d['words76'][koff + 5:koff + 5 + kid[2]]
                for r in range(kid[2] // 36):
                    row = w[r * 36 + 5:r * 36 + 36]
                    recs, stop = tile_stream(row, relaxed=True)
                    rows.append((tuple(w[r * 36:r * 36 + 5]), recs, stop, row))
        d['rows8'] = rows
    print('parsed %d/%d fails %s' % (len(docs), len(FILES), fails[:5]))
    print('ok77 (all n records tile W): %d/%d' % (sum(d['ok77'] for d in docs), len(docs)))
    print('chain76 tail all-zero-chunks: %d/%d' % (sum(d['chain76_ok'] for d in docs), len(docs)))
    print('sub40:', collections.Counter(tuple(d['sub40'] or ()) for d in docs).most_common(6))
    print('kids76 ids:', collections.Counter(tuple(k[0] for k in d['kids76']) for d in docs).most_common(8))
    print('kids76 (id,z,len) sample:', collections.Counter(tuple(k[:3] for k in d['kids76']) for d in docs).most_common(6))
    print('rows8 exact (14 recs, 31 words):', collections.Counter((len(d['rows8']), all(len(recs) == sub[1] and stop == 31 and sub[1] == 14 for sub, recs, stop, row in d['rows8'])) if d['rows8'] else None for d in docs).most_common(10))
    print('rows8 n:', collections.Counter(len(d['rows8']) for d in docs).most_common(8))
    print('sub76 constant:', collections.Counter(d['sub76'] for d in docs).most_common())
    print('h77 word2/3:', collections.Counter((d['h77'][1], d['h77'][2], d['h77'][3]) for d in docs).most_common())
    print('h76 w1/2/3:', collections.Counter((d['h76'][1], d['h76'][2], d['h76'][3]) for d in docs).most_common())
    print('h40 id,x,y:', collections.Counter((d['h40'][0], d['h40'][1], d['h40'][2]) if d['h40'] else 'no40' for d in docs).most_common())
    print('z40 hist:', collections.Counter(d['h40'][3] if d['h40'] else None for d in docs).most_common())
    print('L40/14 vs z40 mismatch:', collections.Counter((d['h40'][3], d['h40'][4] % 14, d['h40'][4] // max(d['h40'][3],1)) for d in docs if d['h40']).most_common(10))
    print('tail76 chunks:', collections.Counter(tuple(t[0] for t in d['tail76']) for d in docs).most_common(10))
    print('n77 hist:', collections.Counter(d['n77'] for d in docs).most_common())
    print('recs76 stop==end (clean 76 stream):', collections.Counter((d['stop76'] == len(d['words76']), d['stop76'] == len(d['words76']) - 10) for d in docs).most_common())
    print('recs40 full tile:', collections.Counter(len(d['recs40']) == len(d['words40']) // 7 if d['words40'] else None for d in docs).most_common())

    # field presence/value census
    fp = collections.defaultdict(lambda: dict(files=0, hist=collections.Counter(), vals=collections.defaultdict(collections.Counter)))
    for d in docs:
        for row_sub, recs8, stop8, row in d['rows8']:
            seen = set()
            for i, c, f, w in recs8:
                key = '8/%d/%d' % (c, f)
                rec = fp[key]
                if (c, f) not in seen:
                    rec['files'] += 1
                    seen.add((c, f))
                pl = row[i + 1:i + 1 + w]
                if c in (0, 1, 2, 3, 10, 16) and w == 1:
                    rec['vals']['f'].update([round(f32(pl[0]), 6)])
                    rec['vals']['i'].update([pl[0]])
                elif c in (6, 7, 8):
                    rec['vals']['f'].update([tuple(round(f32(x), 4) for x in pl[:3])])
                elif w > 1:
                    rec['vals']['tuple'].update([tuple(pl)])
    for d in docs:
        for sec, recs, words in (('77', d['recs77'], d['words77']), ('76', d['recs76'], d['words76']), ('40', d['recs40'] or [], d['words40'] or ())):
            seen = set()
            for i, c, f, w in recs:
                key = '%s/%d/%d' % (sec, c, f)
                rec = fp[key]
                if (c, f) not in seen:
                    rec['files'] += 1
                    seen.add((c, f))
                pl = words[i + 1:i + 1 + w]
                if c in (1, 2, 3, 10, 16) and w == 1:
                    rec['vals']['f'].update([round(f32(pl[0]), 6)])
                    rec['vals']['i'].update([pl[0]])
                elif c in (6, 7, 8):
                    rec['vals']['f'].update([tuple(round(f32(x), 4) for x in pl[:3])])
                elif w > 1:
                    rec['vals']['tuple'].update([tuple(pl)])
    out = {}
    print('\n=== field presence census (section/class/field -> files, distinct payloads) ===')
    for key in sorted(fp, key=lambda k: (k.split('/')[0], int(k.split('/')[1]), int(k.split('/')[2]))):
        r = fp[key]
        dv = len(r['vals']['f'])
        top = r['vals']['f'].most_common(2)
        print('%-10s files=%3d distinct=%4d top=%s' % (key, r['files'], dv, top if dv > 1 else top))
        out[key] = dict(files=r['files'], distinct=dv, top=[str(t) for t in top[:4]])
    json.dump(dict(fields=out,
                   per_file={os.path.basename(d['path']): dict(
                       size=d['size'], n77=d['n77'], W77=d['W77'],
                       h76=d['h76'][4], z40=d['h40'][3] if d['h40'] else 0,
                       L40=d['h40'][4] if d['h40'] else 0,
                       strtab_count=len(d['strings']), strtab_size=d['h77'] and None,
                       recs77=[[i, c, f, list(d['words77'][i+1:i+1+w])] for i, c, f, w in d['recs77']],
                       recs76=[[i, c, f, list(d['words76'][i+1:i+1+w])] for i, c, f, w in d['recs76']],
                       recs40=[[i, c, f, list(d['words40'][i+1:i+1+w])] for i, c, f, w in (d['recs40'] or [])],
                       rows8=[[list(r), [[i, c, f, list(row[i+1:i+1+w])] for i, c, f, w in recs], stop] for r, recs, stop, row in d['rows8']],
                       strings=d['strings'],
                   ) for d in docs}),
              open(os.path.join(r'D:\TLGL\.scratch', 'sfl_fields.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, default=str)
    print('\nwrote sfl_fields.json')
