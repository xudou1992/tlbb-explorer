"""Recover the two-lane 65601-based path hash from the 154 (path, uHash) pairs."""
import json

M32 = 0xFFFFFFFF
B = 65601
rows = json.load(open(r'D:\TLGL'.replace('\\', '/') + '/.scratch/out/loose_index.json', encoding='utf-8'))
pairs = [(r['path'], int(r['hash'], 16)) for r in rows]


def sdbm32(s, seed=0, base=B, enc='utf-8'):
    h = seed
    for c in s.encode(enc):
        h = (c + h * base) & M32
    return h


def lanes(p):
    h = int(p[1])
    return (h >> 32) & M32, h & M32


path, hv = pairs[0]
lo, hi = lanes((path, hv))
S0 = sdbm32(path)
L = len(path)
print('path=%r len=%d want hi=%08x lo=%08x  sdbm32(seed0)=%08x' % (path, L, lo, hi, S0))
inv = pow(pow(B, L, 1 << 32), -1, 1 << 32)
for name, target in (('hi', lo), ('lo', hi)):
    seed = ((target - S0) * inv) & M32
    print('  seed for %s lane: 0x%08x (%d)' % (name, seed, seed))

# Try: which lane is sdbm32 with seed 0? check all 154
for seedname, seed in (('hi0', 0), ):
    pass

# candidate model A: hi = sdbm32(seedA), lo = sdbm32(seedB)
best = None
for target_lane in ('hi', 'lo'):
    seeds = set()
    for p, v in pairs:
        lo, hi = lanes((p, v))
        t = lo if target_lane == 'hi' else hi
        L = len(p)
        inv = pow(pow(B, L, 1 << 32), -1, 1 << 32)
        seeds.add(((t - sdbm32(p)) * inv) & M32)
    print('%s lane consistent seed set size = %d %s' % (target_lane, len(seeds), [hex(x) for x in list(seeds)[:5]]))
