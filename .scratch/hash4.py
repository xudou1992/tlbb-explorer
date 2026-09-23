import json

M32 = 0xFFFFFFFF
rows = json.load(open(r'D:\TLGL\.scratch\out\loose_index.json', encoding='utf-8'))
pairs = [(r['path'], int(r['hash'], 16)) for r in rows]


def h(s, seed=0, mult=65599, mask=M32, enc='utf-8', rev=False, n=1):
    b = s.encode(enc)
    if rev:
        b = b[::-1]
    x = seed
    for c in b:
        x = (c + x * mult) & mask
    return x


def sdbm_shift(s, seed=0, mask=M32, enc='utf-8'):
    x = seed
    for c in s.encode(enc):
        x = (c + (x << 6) + (x << 16) - x) & mask
    return x


def show(name, fn):
    ok_hi = sum(1 for p, v in pairs if fn(p) == (v >> 32) & M32)
    ok_lo = sum(1 for p, v in pairs if fn(p) == v & M32)
    print('%-28s hi=%3d/%d lo=%3d/%d  sample=%08x' % (name, ok_hi, len(pairs), ok_lo, len(pairs), fn(pairs[0][0])))


tgt_lo = pairs[0][1] & M32
print('want lo lane for', pairs[0][0], '=', format(tgt_lo, '08x'))
show('sdbm utf8', lambda p: sdbm_shift(p))
show('sdbm utf16le', lambda p: sdbm_shift(p, enc='utf-16-le'))
show('sdbm utf16le+null', lambda p: sdbm_shift(p + '\0', enc='utf-16-le'))
show('sdbm utf8 null-term', lambda p: sdbm_shift(p + '\0'))
show('sdbm upper', lambda p: sdbm_shift(p.upper()))
show('sdbm lower', lambda p: sdbm_shift(p.lower()))
show('sdbm rev', lambda p: sdbm_shift(p[::-1]))
show('sdbm base(1)', lambda p: sdbm_shift(p, seed=1))
show('sdbm len0', lambda p: sdbm_shift(p, seed=len(p)))
show('mult65601', lambda p: h(p, mult=65601))
show('mult65599 seed-1', lambda p: h(p, seed=M32))
show('basename', lambda p: sdbm_shift(p.rsplit('/', 1)[-1]))
show('basename lower', lambda p: sdbm_shift(p.rsplit('/', 1)[-1].lower()))
show('dir', lambda p: sdbm_shift(p.rsplit('/', 1)[0]))
show('sdbm bs', lambda p: sdbm_shift(p.replace('/', '\\')))
show('sdbm utf16 upper', lambda p: sdbm_shift(p.upper(), enc='utf-16-le'))
show('sdbm utf16 lower', lambda p: sdbm_shift(p.lower(), enc='utf-16-le'))
