"""Decompose particle section + tail. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
OUT = Path(__file__).resolve().parent
HDR = 0x140
STRIDE = 0x318

def cstrings(b, base=0, minlen=4):
    out = []
    i = 0
    while i < len(b):
        if 32 <= b[i] < 127:
            j = i
            while j < len(b) and 32 <= b[j] < 127:
                j += 1
            if j - i >= minlen and j < len(b) and b[j] == 0:
                out.append((base + i, b[i:j].decode("latin1")))
            i = j + 1
        else:
            i += 1
    return out

files = []
for p in sorted(TREE.glob("*.tani")):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))

# classify
cls = collections.Counter()
examples = {}
tails = collections.defaultdict(list)  # extra_len -> list of (name, n, tailbytes)

for name, b, z in files:
    L = len(b)
    if L < HDR or z >= 0x100:
        cls[f"short_or_longpath {L}"] += 1
        examples.setdefault(f"short {L}", name)
        continue
    c10c = struct.unpack_from("<I", b, 0x10C)[0]
    n138 = struct.unpack_from("<I", b, 0x138)[0]
    n13c = struct.unpack_from("<I", b, 0x13C)[0]
    if n138 > 64 or n138 == 0:
        key = f"bad_n138 {n138} len={L} c10c={c10c} c13c={n13c}"
        cls[key] += 1
        examples.setdefault(key, name)
        continue
    pend = HDR + n138 * STRIDE
    if pend > L:
        key = f"overrun n={n138} len={L} c10c={c10c}"
        cls[key] += 1
        examples.setdefault(key, name)
        continue
    extra = L - pend
    key = f"c10c={c10c} n={n138} c13c={n13c} extra={extra}"
    cls[key] += 1
    if extra not in examples:
        examples[extra] = name
    if len(tails[extra]) < 2:
        tails[extra].append((name, n138, b[pend:], b))

print("classes", len(cls))
for k, c in cls.most_common(40):
    print(f"  {c:4d}  {k}")

# for each distinct extra, show tail strings and a small hex of head/tail
print("\n===== TAIL SAMPLES =====")
for extra in sorted(tails):
    if extra == 0:
        continue
    name, n138, tail, full = tails[extra][0]
    print(f"\n-- extra={extra} example={name} n138={n138} tail_len={len(tail)}")
    ss = cstrings(tail, 0, 5)
    # only resource-like or first 12
    shown = 0
    deltas = []
    prev = None
    for off, s in ss:
        if s.endswith((".pu", ".wav", ".ogg", ".mp3")) or "sound" in s or shown < 3:
            print(f"   str {off:#x} {s[:70]}")
            if s.endswith((".wav", ".ogg", ".pu", ".mp3")):
                if prev is not None:
                    deltas.append(off - prev)
                prev = off
            shown += 1
            if shown > 14:
                break
    print("   res deltas", deltas[:8], "unique", sorted(set(deltas))[:6])
    # hex head 48 and last 32
    def hx(buf, n=48):
        h = " ".join(f"{x:02x}" for x in buf[:n])
        return h
    print("   head", hx(tail, 64))
    print("   end ", hx(tail[-32:], 32) if len(tail) >= 32 else hx(tail, len(tail)))
    # u32s in first 32
    us = []
    for i in range(0, min(32, len(tail) - 3), 4):
        us.append(str(struct.unpack_from("<I", tail, i)[0]))
    print("   u32head", us)

# Does extra factor as a*0x4B0 + b across the observed extras?
print("\n===== extra factorization =====")
extras = sorted(k for k in tails if k)
print("distinct extras", extras)

# try footer in 0..128 and stride candidates
strides = [0x4B0, 0x318, 0x130, 0x4B0 + 4, 1204, 1192, 0x4C0, 0x4A0, 0x260, 792, 600, 304]
for stride in (0x4B0, 0x318, 0x130, 0x260, 0x4A8, 0x4B8, 0x500, 0x2A0, 0x178):
    foots = set()
    ok = True
    for e in extras:
        # e = q*stride + foot, foot in 0..stride
        foot = e % stride
        foots.add(foot)
    print(f"  stride {stride:#x} ({stride}) distinct remainders {sorted(foots)[:12]} n={len(foots)}")
