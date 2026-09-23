import json

M32 = 0xFFFFFFFF
rows = json.load(open(r'D:\TLGL\.scratch\out\loose_index.json', encoding='utf-8'))
pairs = [(r['path'], int(r['hash'], 16)) for r in rows]


def sdbm(s, seed=0, mult=65599, mask=M32, enc='utf-8'):
    h = seed
    for c in s.encode(enc):
        h = (c + (h << 6) + (h << 16) - h) & mask
    return h


def sdbm2(s, seed=0, mult=65599, mask=M32, enc='utf-8'):
    h = seed
    for c in s.encode(enc):
        h = (c + h * mult) & mask
    return h


for name, fn in (('classic65599', sdbm), ('mult65601', lambda s, seed=0: sdbm2(s, seed, 65601))):
    a = fn(pairs[0][0])
    print('%-13s sdbm32(0)=%08x  sdbm64(0)=%016x want=%016x' % (
        name, a, fn(pairs[0][0], 0, mask=M32 * 2 + 1) if name == 'classic65599' else 0, int(pairs[0][1])))

# confirm low lane of 64-bit classic sdbm equals want>>32
hit = sum(1 for p, v in pairs if sdbm(p, mask=(1 << 64) - 1) & M32 == (v >> 32) & M32)
print('hi-lane == sdbm64(path) & 0xffffffff : %d/%d' % (hit, len(pairs)))
hit2 = sum(1 for p, v in pairs if sdbm2(p, mask=(1 << 64) - 1) & M32 == (v >> 32) & M32)
print('hi-lane == mult65601_64 & 0xffffffff : %d/%d' % (hit2, len(pairs)))

# solve the low lane seed assuming low = sdbm32(path, seedK)
mult = 65599
seeds = set()
for p, v in pairs:
    L = len(p.encode('utf-8'))
    t = v & M32
    s0 = sdbm(p)
    try:
        inv = pow(pow(mult, L, 1 << 32), -1, 1 << 32)
    except ValueError:
        continue
    seeds.add(((t - s0) * inv) & M32)
print('low-lane seed candidates:', len(seeds), [hex(x) for x in list(seeds)[:6]])
