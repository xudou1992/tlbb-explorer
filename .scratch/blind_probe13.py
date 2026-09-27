import collections, os, struct, hashlib

jr = {}
with open('D:/TLGL/.scratch/names_jrpc.tsv', encoding='utf-8') as f:
    f.readline()
    for l in f:
        a = l.rstrip('\n').split('\t')
        if len(a) >= 2 and a[0] and a[1]:
            jr[a[0]] = a[1]
print('jrpc rows', len(jr))
print('ext hist', collections.Counter(os.path.splitext(v)[1].lower() for v in jr.values()).most_common(12))
sc = [v for v in jr.values() if v.lower().endswith('.scene')]
print('scene paths', len(sc), sc[:6])
print('top dirs', collections.Counter(v.split('/')[0] for v in jr.values()).most_common(8))
print('dirs mobile_maps/*', sum(1 for v in sc if v.startswith('mobile_maps/')))

import sqlite3
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
nameless = [r['hash'] for r in c.execute('select hash from resources where named=0')]
cls = {r['hash']: (r['type'], r['subtype']) for r in c.execute('select hash,type,subtype from resources where named=0')}
hit = [h for h in nameless if h in jr]
print('nameless rows', len(nameless), 'of which present in jrpc tsv:', len(hit))
print('  by class:', collections.Counter(cls[h] for h in hit).most_common(6))
paths = [r[0] for r in c.execute('select path from resources where path is not null')]
print('db named paths', len(paths), 'jrpc paths not in db:', len(set(jr.values()) - set(paths)))

# ---- path -> hash crack attempts on confirmed pairs ----
tests = list(jr.items())[:6]


def fnv1a64(b):
    h = 0xcbf29ce484222325
    for x in b:
        h = ((h ^ x) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def crc64(b, poly=0xC96C5795D7870F42):
    h = 0xFFFFFFFFFFFFFFFF
    for x in b:
        h ^= x << 56
        for _ in range(8):
            h = ((h << 1) & 0xFFFFFFFFFFFFFFFF) ^ (poly if h >> 63 else 0)
    return h ^ 0xFFFFFFFFFFFFFFFF


cands = {}
cands['fnv1a'] = fnv1a64
cands['crc64-xz'] = crc64
for h, p in tests[:4]:
    print('\n', p, '-> expected', h)
    variants = {
        'as-is': p,
        'lower': p.lower(),
        'backslash': p.replace('/', '\\'),
        'bs-lower': p.replace('/', '\\').lower(),
        'noext': os.path.splitext(p)[0],
        'base': os.path.basename(p),
        'base-lower': os.path.basename(p).lower(),
    }
    found = False
    for cn, fn in cands.items():
        for vn, v in variants.items():
            if '%016x' % fn(v.encode('utf-8')) == h:
                print('   MATCH', cn, vn)
                found = True
    for hn in ('md5', 'sha1'):
        for vn, v in variants.items():
            d = getattr(hashlib, hn)(v.encode()).hexdigest()
            if d[:16] == h or d[-16:] == h:
                print('   MATCH', hn, vn)
                found = True
    if not found:
        print('   no match among fnv1a64/crc64/md5/sha1 variants')
