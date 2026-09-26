import sqlite3, zlib, struct, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
print('hash distinct:', c.execute('select count(distinct hash) from resources').fetchone()[0],
      '/ total', c.execute('select count(*) from resources').fetchone()[0])
rows = c.execute("select path, hash, filecrc from resources where named=1 and path is not null limit 20000").fetchall()
print('pairs:', len(rows), 'sample:', rows[:2])

def fnv1a(b, bits):
    h = 0xcbf29ce484222325 if bits==64 else 0x811c9dc5
    m = (1<<bits)-1; p = 0x100000001b3 if bits==64 else 0x01000193
    for x in b: h = ((h ^ x) * p) & m
    return h
def fnv1(b, bits):
    h = 0xcbf29ce484222325 if bits==64 else 0x811c9dc5
    m = (1<<bits)-1; p = 0x100000001b3 if bits==64 else 0x01000193
    for x in b: h = ((h * p) & m) ^ x
    return h
def djb2(b):
    h = 5381
    for x in b: h = (h*33 + x) & 0xffffffff
    return h
def djb2a(b):
    h = 5381
    for x in b: h = ((h*33) ^ x) & 0xffffffff
    return h
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
def joaat(b):
    h = 0
    for x in b:
        h = (h + x) & 0xffffffff
        h = (h + (h<<10)) & 0xffffffff
        h ^= h >> 6
    h = (h + (h<<3)) & 0xffffffff
    h ^= h >> 11
    h = (h + (h<<15)) & 0xffffffff
    return h
def elfhash(b):
    h = 0
    for x in b:
        h = ((h << 4) + x) & 0xffffffff
        g = h & 0xf0000000
        if g: h ^= g >> 24
        h &= ~g & 0xffffffff
    return h
def java(b):
    h = 0
    for x in b: h = (h*31 + x) & 0xffffffff
    return h

def variants(p):
    f = p.replace(chr(92),'/')
    base = f.rsplit('/',1)[-1]
    stem = base.rsplit('.',1)[0] if '.' in base else base
    yield 'fwd', f.encode()
    yield 'fwd_l', f.lower().encode()
    yield 'fwd_u', f.upper().encode()
    yield 'back', p.encode()
    yield 'base', base.encode()
    yield 'base_l', base.lower().encode()
    yield 'stem', stem.encode()
    yield 'stem_l', stem.lower().encode()
    yield 'nul', (f+chr(0)).encode()
    yield 'nodata', (f[5:] if f.lower().startswith('data/') else f).encode()
    yield 'lead', ('/'+f).encode()

hashes_u32 = {
    'crc32': lambda b: zlib.crc32(b) & 0xffffffff,
    'adler32': lambda b: zlib.adler32(b) & 0xffffffff,
    'fnv1a32': lambda b: fnv1a(b,32), 'fnv1_32': lambda b: fnv1(b,32),
    'djb2': djb2, 'djb2a': djb2a, 'sdbm': sdbm, 'joaat': joaat, 'elf': elfhash, 'java31': java,
}
hashes_u64 = {
    'fnv1a64': lambda b: fnv1a(b,64), 'fnv1_64': lambda b: fnv1(b,64),
    'crc32_x2': lambda b: (zlib.crc32(b)<<32) | (zlib.crc32(b[::-1]) & 0xffffffff),
}
sample = rows[::4]  # 5000 pairs
targets_u32 = []
for p,h,fc in sample:
    hi = int(h,16)
    targets_u32.append((hi & 0xffffffff, hi>>32, fc))
print('\nhunting on', len(sample), 'pairs...')
for vname,_ in variants('x'):
    vs = [(p, bytes(variants(p) and [] or [])) for p in []]  # noop
for vname in ['fwd','fwd_l','fwd_u','back','base','base_l','stem','stem_l','nul','nodata','lead']:
    # build variant bytes per path
    vb = []
    for p,h,fc in sample:
        f = p.replace(chr(92),'/'); base = f.rsplit('/',1)[-1]
        stem = base.rsplit('.',1)[0] if '.' in base else base
        d = {'fwd':f,'fwd_l':f.lower(),'fwd_u':f.upper(),'back':p,'base':base,'base_l':base.lower(),
             'stem':stem,'stem_l':stem.lower(),'nul':f+chr(0),
             'nodata':(f[5:] if f.lower().startswith('data/') else f),'lead':'/'+f}
        vb.append((d[vname].encode('utf-8','replace'), int(h,16), fc))
    for hname, hf in hashes_u32.items():
        m1 = m2 = m3 = 0
        for b, hi, fc in vb:
            v = hf(b)
            if v == (hi & 0xffffffff): m1 += 1
            if v == (hi >> 32): m2 += 1
            if v == fc: m3 += 1
        if m1 or m2 or m3:
            print(f'  u32 {vname:6s} {hname:9s}: hash_low={m1} hash_high={m2} filecrc={m3} / {len(vb)}')
    for hname, hf in hashes_u64.items():
        m = 0
        for b, hi, fc in vb:
            if hf(b) == hi: m += 1
        if m: print(f'  u64 {vname:6s} {hname:9s}: hash={m} / {len(vb)}')
print('done')
