"""Test fixed-offset fields and 0x130 stride. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
files = []
for p in sorted(TREE.glob("*.tani")):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))

# first nonzero after NUL
nz_at = collections.Counter()
for name, b, z in files:
    i = z + 1
    while i < len(b) and b[i] == 0:
        i += 1
    nz_at[i if i < len(b) else -1] += 1
print("first nonzero abs offset top", nz_at.most_common(15))
print("distinct first-nonzero offs", len(nz_at))

# u32 at fixed offsets 0x50..0x140: value histogram if highly peaked
print("\n== peaked u32 (files with off past NUL) ==")
for off in range(0x50, 0x150, 4):
    vals = collections.Counter()
    n = 0
    for name, b, z in files:
        if off <= z or off + 4 > len(b):
            continue
        vals[struct.unpack_from("<I", b, off)[0]] += 1
        n += 1
    if n < 2000:
        continue
    top, c = vals.most_common(1)[0]
    frac = c / n
    if frac >= 0.5 or len(vals) <= 8:
        show = top if top < 10000 or top in (0x3f800000, 0xffffffff, 0x80000000) else hex(top)
        print(f"  {off:#06x} n={n:4d} distinct={len(vals):4d} top={show!s:>12} {frac:6.1%}")

# correlate u32@0x10c with pu-count and size
def pu_at_slots(b):
    n = 0
    offs = []
    off = 0x140
    while off + 4 <= len(b):
        # cstring?
        if 32 <= b[off] < 127:
            j = off
            while j < len(b) and 32 <= b[j] < 127:
                j += 1
            if j < len(b) and b[j] == 0 and j - off >= 4:
                s = b[off:j].decode("latin1")
                if "." in s:
                    n += 1
                    offs.append((off, s[:48]))
        off += 0x130
    return offs

print("\n== u32 candidates vs slot count ==")
# try several count offsets
for coff in (0x100, 0x104, 0x108, 0x10c, 0x110, 0x130, 0x134, 0x138, 0x13c):
    agree = 0
    n = 0
    bad = collections.Counter()
    for name, b, z in files:
        if coff + 4 > len(b) or coff <= z:
            continue
        c = struct.unpack_from("<I", b, coff)[0]
        slots = pu_at_slots(b)
        n += 1
        if c == len(slots):
            agree += 1
        else:
            bad[(c if c < 20 else "big", len(slots))] += 1
    print(f"  count@{coff:#x} == pu-slots {agree}/{n}  mismatch top {bad.most_common(4)}")

# file size vs slot count
print("\n== size vs n slots ==")
sz_slot = collections.Counter()
for name, b, z in files:
    sz_slot[(len(pu_at_slots(b)), len(b))] += 1
# for each slot count, size set
byc = collections.defaultdict(collections.Counter)
for (ns, sz), c in sz_slot.items():
    byc[ns][sz] += c
for ns in sorted(byc):
    sizes = byc[ns]
    print(f"  slots={ns:2d} files={sum(sizes.values()):4d} distinct sizes={len(sizes)} "
          f"size-range {min(sizes)}..{max(sizes)} top {sizes.most_common(3)}")

# Within one 1904 file, compare two 0x130 windows at a few bases
name, b, z = next(rec for rec in files if len(rec[1]) == 1904)
print("\nSAMPLE", name, "len", len(b), "nul", z)
bases = [0x00, 0x10, 0x130, 0x140]
for base in (0xD0, 0x100, 0x130, 0x140):
    stride = 0x130
    w0 = b[base:base + stride]
    w1 = b[base + stride:base + 2 * stride]
    if len(w1) < stride:
        print(f"  base {base:#x} window short")
        continue
    nd = sum(x != y for x, y in zip(w0, w1))
    print(f"  base {base:#x} stride 0x130  differing bytes {nd}/{stride}")

# dump annotated 1112 from 0xE0 to end, grouped
name, b, z = next(rec for rec in files if len(rec[1]) == 1112)
print("\nANNOT 1112", name)
for off in range(0xE0, len(b), 16):
    chunk = b[off:off + 16]
    u = []
    if off + 16 <= len(b):
        a, c, d, e = struct.unpack_from("<4I", b, off)
        fa, fb_, fc, fd = struct.unpack_from("<4f", b, off)
        def fmt(v, f):
            if v == 0:
                return "0"
            if abs(f) < 1000 and f == f and abs(f) > 1e-6:
                return f"f{f:.4g}"
            if v < 100000:
                return str(v)
            return hex(v)
        cells = " ".join(fmt(v, f) for v, f in zip((a, c, d, e), (fa, fb_, fc, fd)))
    else:
        cells = ""
    t = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
    print(f"  {off:04x} {cells:48} {t}")

print("\nANNOT 1904 second slot around 0x260-0x3a0")
name, b, z = next(rec for rec in files if len(rec[1]) == 1904 and b[0x270:0x274] == b"w135")
print(" ", name)
for off in range(0x240, 0x3C0, 16):
    a, c, d, e = struct.unpack_from("<4I", b, off)
    fa, fb_, fc, fd = struct.unpack_from("<4f", b, off)
    def fmt(v, f):
        if v == 0:
            return "0"
        if f == f and abs(f) < 1e6 and abs(f) > 1e-8 and not (v > 100000 and abs(f) > 1e5):
            # prefer float if it looks like a nice float
            if v in (0x3f800000, 0x40000000, 0x3f000000) or (abs(f) <= 100 and abs(f - round(f, 3)) < 1e-4):
                return f"f{f:.4g}"
        if v < 100000:
            return str(v)
        return hex(v)
    cells = " ".join(fmt(v, f) for v, f in zip((a, c, d, e), (fa, fb_, fc, fd)))
    t = "".join(chr(x) if 32 <= x < 127 else "." for x in b[off:off + 16])
    print(f"  {off:04x} {cells:48} {t}")
